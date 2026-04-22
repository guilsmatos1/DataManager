from __future__ import annotations

from datetime import UTC, date, datetime
from typing import cast

import pandas as pd
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session
from trademachine.datamanager.db.models import (
    EconomicObservation,
    EconomicSeries,
    Source,
)
from trademachine.datamanager.infrastructure.database import SessionLocal, engine


class SeriesStorageManager:
    """Persistence layer for economic time series such as FRED."""

    _INSERT_BATCH_SIZE = 5_000

    def _get_db(self) -> Session:
        return cast(Session, SessionLocal())

    @staticmethod
    def _coerce_datetime(value: object | None) -> datetime | None:
        if value in (None, ""):
            return None
        dt = pd.to_datetime(value, errors="coerce")
        if pd.isna(dt):
            return None
        if isinstance(dt, pd.Timestamp):
            if dt.tzinfo is None:
                dt = dt.tz_localize(UTC)
            return dt.to_pydatetime()  # type: ignore[no-any-return]
        return cast(datetime, dt)

    @classmethod
    def _to_json_safe(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, pd.Timestamp):
            return value.isoformat()
        if isinstance(value, datetime | date):
            return value.isoformat()
        if isinstance(value, dict):
            return {str(k): cls._to_json_safe(v) for k, v in value.items()}
        if isinstance(value, list):
            return [cls._to_json_safe(item) for item in value]
        if isinstance(value, tuple):
            return [cls._to_json_safe(item) for item in value]
        return value

    @staticmethod
    def _normalize_index(df: pd.DataFrame) -> pd.DataFrame:
        if isinstance(df.index, pd.DatetimeIndex):
            result = df.copy()
        else:
            result = df.copy()
            for candidate in [
                "timestamp",
                "date",
                "datetime",
                "observation_date",
            ]:
                if candidate in result.columns:
                    result[candidate] = pd.to_datetime(
                        result[candidate], errors="coerce"
                    )
                    result.set_index(candidate, inplace=True)
                    break

        if not isinstance(result.index, pd.DatetimeIndex):
            raise ValueError("Series data must have a DatetimeIndex or date column.")

        if result.index.tz is not None:
            result.index = result.index.tz_convert(None)

        result.index.name = "timestamp"
        result.sort_index(inplace=True)
        result = result[~result.index.duplicated(keep="last")]
        return result

    def check_connection(self) -> None:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

    def get_or_create_source(self, db: Session, name: str) -> Source:
        source = db.execute(
            select(Source).where(Source.name == name.lower())
        ).scalar_one_or_none()
        if not source:
            source = Source(name=name.lower())
            db.add(source)
            db.flush()
        return source

    def get_or_create_series(
        self,
        db: Session,
        source_id: int,
        series_id: str,
        metadata: dict | None = None,
    ) -> EconomicSeries:
        normalized_series_id = series_id.upper()
        series = db.execute(
            select(EconomicSeries).where(
                EconomicSeries.source_id == source_id,
                EconomicSeries.series_id == normalized_series_id,
            )
        ).scalar_one_or_none()
        if not series:
            series = EconomicSeries(
                source_id=source_id,
                series_id=normalized_series_id,
            )
            db.add(series)
            db.flush()

        if metadata:
            series.title = metadata.get("title") or metadata.get("name") or series.title
            series.native_frequency = (
                metadata.get("frequency")
                or metadata.get("native_frequency")
                or series.native_frequency
            )
            series.units = metadata.get("units") or series.units
            series.seasonal_adjustment = (
                metadata.get("seasonal_adjustment") or series.seasonal_adjustment
            )
            series.metadata_json = cast(dict, self._to_json_safe(metadata))
            series.observation_start = (
                self._coerce_datetime(
                    metadata.get("observation_start") or metadata.get("start_date")
                )
                or series.observation_start
            )
            series.observation_end = (
                self._coerce_datetime(
                    metadata.get("observation_end")
                    or metadata.get("end_date")
                    or metadata.get("last_updated")
                )
                or series.observation_end
            )

        return series

    def _update_series_stats(self, db: Session, series_id: int) -> None:
        stats = db.execute(
            select(
                func.min(EconomicObservation.timestamp).label("min_ts"),
                func.max(EconomicObservation.timestamp).label("max_ts"),
                func.count(EconomicObservation.timestamp).label("count"),
            ).where(EconomicObservation.series_ref_id == series_id)
        ).first()

        series = db.get(EconomicSeries, series_id)
        if not series:
            return

        series.observation_start = stats.min_ts if stats and stats.min_ts else None
        series.observation_end = stats.max_ts if stats and stats.max_ts else None
        if series.last_fetched_at is None:
            series.last_fetched_at = datetime.now(UTC)
        db.flush()

    def save_series_data(
        self,
        df: pd.DataFrame,
        source: str,
        series_id: str,
        metadata: dict | None = None,
        update_stats: bool = True,
    ) -> int:
        if df.empty:
            return 0

        normalized = self._normalize_index(df)

        with self._get_db() as db:
            src = self.get_or_create_source(db, source)
            series = self.get_or_create_series(db, src.id, series_id, metadata=metadata)

            records_df = normalized.copy()
            records_df.columns = [str(col).lower() for col in records_df.columns]

            value_column = None
            for candidate in ["value", "values", "observation_value"]:
                if candidate in records_df.columns:
                    value_column = candidate
                    break
            if value_column is None:
                non_index_columns = [
                    col for col in records_df.columns if col != "timestamp"
                ]
                if len(non_index_columns) == 1:
                    value_column = non_index_columns[0]
                else:
                    raise ValueError(
                        "Series data must include a numeric 'value' column."
                    )

            records_df = records_df.reset_index()
            if getattr(records_df["timestamp"].dt, "tz", None) is not None:
                records_df["timestamp"] = records_df["timestamp"].dt.tz_convert(None)

            records_df["series_ref_id"] = series.id
            records_df["value"] = pd.to_numeric(
                records_df[value_column], errors="coerce"
            )
            records_df = records_df.dropna(subset=["value"])

            if records_df.empty:
                return 0

            records = records_df[["timestamp", "series_ref_id", "value"]].to_dict(
                orient="records"
            )

            for i in range(0, len(records), self._INSERT_BATCH_SIZE):
                batch = records[i : i + self._INSERT_BATCH_SIZE]
                stmt = pg_insert(EconomicObservation).values(batch)
                upsert_stmt = stmt.on_conflict_do_update(
                    constraint="uq_economic_observation_timestamp",
                    set_={"value": stmt.excluded.value},
                )
                db.execute(upsert_stmt)

            series.last_fetched_at = datetime.now(UTC)
            db.commit()

            if update_stats:
                self._update_series_stats(db, series.id)
                db.commit()

            return len(records)

    def load_series_data(self, source: str, series_id: str) -> pd.DataFrame:
        with self._get_db() as db:
            src = db.execute(
                select(Source).where(Source.name == source.lower())
            ).scalar_one_or_none()
            if not src:
                raise FileNotFoundError(f"Source not found: {source}")

            series = db.execute(
                select(EconomicSeries).where(
                    EconomicSeries.source_id == src.id,
                    EconomicSeries.series_id == series_id.upper(),
                )
            ).scalar_one_or_none()
            if not series:
                raise FileNotFoundError(f"Series not found: {source} -> {series_id}")

            query = (
                "SELECT timestamp, value FROM economic_observations "
                "WHERE series_ref_id = :sid ORDER BY timestamp ASC"
            )
            df = pd.read_sql(
                text(query),
                con=engine,
                params={"sid": series.id},
                index_col="timestamp",
                parse_dates=["timestamp"],
            )

            if df.empty:
                return pd.DataFrame(columns=["Value"])

            df.columns = ["Value"]
            return df

    def list_series(self) -> list[dict]:
        with self._get_db() as db:
            query = (
                select(
                    Source.name.label("source"),
                    EconomicSeries.series_id,
                    EconomicSeries.title,
                    EconomicSeries.native_frequency,
                    EconomicSeries.units,
                    EconomicSeries.seasonal_adjustment,
                    EconomicSeries.observation_start,
                    EconomicSeries.observation_end,
                    EconomicSeries.last_fetched_at,
                    func.count(EconomicObservation.timestamp).label("rows"),
                )
                .join(EconomicSeries, EconomicSeries.source_id == Source.id)
                .outerjoin(
                    EconomicObservation,
                    EconomicObservation.series_ref_id == EconomicSeries.id,
                )
                .group_by(
                    Source.name,
                    EconomicSeries.id,
                    EconomicSeries.series_id,
                    EconomicSeries.title,
                    EconomicSeries.native_frequency,
                    EconomicSeries.units,
                    EconomicSeries.seasonal_adjustment,
                    EconomicSeries.observation_start,
                    EconomicSeries.observation_end,
                    EconomicSeries.last_fetched_at,
                )
                .order_by(Source.name, EconomicSeries.series_id)
            )
            rows = db.execute(query).all()

            return [
                {
                    "source": row.source,
                    "series_id": row.series_id,
                    "title": row.title,
                    "frequency": row.native_frequency,
                    "units": row.units,
                    "seasonal_adjustment": row.seasonal_adjustment,
                    "observation_start": str(row.observation_start)
                    if row.observation_start
                    else None,
                    "observation_end": str(row.observation_end)
                    if row.observation_end
                    else None,
                    "last_updated": str(row.last_fetched_at)
                    if row.last_fetched_at
                    else None,
                    "rows": row.rows,
                }
                for row in rows
            ]

    def get_series_info(self, source: str, series_id: str) -> dict:
        with self._get_db() as db:
            src = db.execute(
                select(Source).where(Source.name == source.lower())
            ).scalar_one_or_none()
            if not src:
                return {"status": "Not Found"}

            series = db.execute(
                select(EconomicSeries).where(
                    EconomicSeries.source_id == src.id,
                    EconomicSeries.series_id == series_id.upper(),
                )
            ).scalar_one_or_none()
            if not series:
                return {"status": "Not Found"}

            row_count = db.execute(
                select(func.count(EconomicObservation.timestamp)).where(
                    EconomicObservation.series_ref_id == series.id
                )
            ).scalar()

            return {
                "status": "ok",
                "source": source.lower(),
                "series_id": series.series_id,
                "title": series.title,
                "native_frequency": series.native_frequency,
                "units": series.units,
                "seasonal_adjustment": series.seasonal_adjustment,
                "observation_start": str(series.observation_start)
                if series.observation_start
                else None,
                "observation_end": str(series.observation_end)
                if series.observation_end
                else None,
                "last_fetched_at": str(series.last_fetched_at)
                if series.last_fetched_at
                else None,
                "rows": int(row_count or 0),
                "metadata": series.metadata_json or {},
            }

    def delete_series(self, source: str, series_id: str) -> bool:
        with self._get_db() as db:
            src = db.execute(
                select(Source).where(Source.name == source.lower())
            ).scalar_one_or_none()
            if not src:
                return False

            series = db.execute(
                select(EconomicSeries).where(
                    EconomicSeries.source_id == src.id,
                    EconomicSeries.series_id == series_id.upper(),
                )
            ).scalar_one_or_none()
            if not series:
                return False

            db.execute(
                delete(EconomicObservation).where(
                    EconomicObservation.series_ref_id == series.id
                )
            )
            db.delete(series)
            db.commit()
            return True
