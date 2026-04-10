from typing import cast

import pandas as pd
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session
from trademachine.datamanager.db.models import (
    Asset,
    EconomicObservation,
    EconomicSeries,
    OhlcvM1,
    OhlcvResampled,
    Source,
)
from trademachine.datamanager.db.processor import DataProcessor
from trademachine.datamanager.infrastructure.database import SessionLocal, engine


class StorageManager:
    """Manages OHLCV storage using TimescaleDB (PostgreSQL).

    Layout:
        - Relational tables: sources, assets (metadata catalog)
        - Hypertable: ohlcv_m1 (primary 1-minute data)
        - Table: ohlcv_resampled (persisted derived timeframes)
    """

    SUPPORTED_TIMEFRAMES = frozenset(DataProcessor.TF_MAPPING)

    def __init__(self):
        pass

    def check_connection(self) -> None:
        """Simple health check to verify DB connectivity on startup."""
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

    def _get_db(self) -> Session:
        return cast(Session, SessionLocal())

    def _normalize_timeframe(self, timeframe: str) -> str:
        normalized = timeframe.upper()
        if normalized not in self.SUPPORTED_TIMEFRAMES:
            raise ValueError(
                f"Timeframe {timeframe} not supported. Use {sorted(self.SUPPORTED_TIMEFRAMES)}."
            )
        return normalized

    def _get_source(self, db: Session, name: str) -> Source | None:
        return db.execute(
            select(Source).where(Source.name == name.lower())
        ).scalar_one_or_none()

    def _get_asset(self, db: Session, ticker: str, source_id: int) -> Asset | None:
        return db.execute(
            select(Asset).where(
                Asset.ticker == ticker.upper(), Asset.source_id == source_id
            )
        ).scalar_one_or_none()

    def _prepare_ohlcv_records(self, df: pd.DataFrame, asset_id: int) -> pd.DataFrame:
        if not isinstance(df.index, pd.DatetimeIndex):
            for col in ["datetime", "date", "time"]:
                if col in df.columns:
                    df = df.copy()
                    df[col] = pd.to_datetime(df[col])
                    df.set_index(col, inplace=True)
                    break

        df_records = df.copy()
        df_records.index.name = "timestamp"
        df_records = df_records.reset_index()

        if getattr(df_records["timestamp"].dt, "tz", None) is not None:
            df_records["timestamp"] = df_records["timestamp"].dt.tz_convert(None)

        df_records["asset_id"] = asset_id
        df_records.columns = df_records.columns.str.lower()

        for col in ["open", "high", "low", "close", "volume"]:
            df_records[col] = df_records[col].astype(float)

        return df_records

    def _upsert_ohlcv_records(
        self,
        db: Session,
        model: type,
        index_elements: list,
        records: list[dict],
        desc: str,
    ) -> None:
        from tqdm import tqdm

        total_batches = (
            len(records) + self._INSERT_BATCH_SIZE - 1
        ) // self._INSERT_BATCH_SIZE
        with tqdm(total=total_batches, desc=desc, unit="batch", leave=False) as pbar:
            for i in range(0, len(records), self._INSERT_BATCH_SIZE):
                batch = records[i : i + self._INSERT_BATCH_SIZE]
                stmt = pg_insert(model).values(batch)
                upsert_stmt = stmt.on_conflict_do_update(
                    index_elements=index_elements,
                    set_={
                        "open": stmt.excluded.open,
                        "high": stmt.excluded.high,
                        "low": stmt.excluded.low,
                        "close": stmt.excluded.close,
                        "volume": stmt.excluded.volume,
                    },
                )
                db.execute(upsert_stmt)
                pbar.update(1)

    def _upsert_m1_records(self, db: Session, records: list[dict]) -> None:
        self._upsert_ohlcv_records(
            db,
            OhlcvM1,
            [OhlcvM1.timestamp, OhlcvM1.asset_id],
            records,
            "Saving M1 to DB",
        )

    def _upsert_resampled_records(self, db: Session, records: list[dict]) -> None:
        self._upsert_ohlcv_records(
            db,
            OhlcvResampled,
            [
                OhlcvResampled.timestamp,
                OhlcvResampled.asset_id,
                OhlcvResampled.timeframe,
            ],
            records,
            "Saving resampled data to DB",
        )

    # ------------------------------------------------------------------
    # Catalog operations (SQLAlchemy)
    # ------------------------------------------------------------------

    def get_or_create_source(self, db: Session, name: str) -> Source:
        source = self._get_source(db, name)
        if not source:
            source = Source(name=name.lower())
            db.add(source)
            db.flush()
        return source

    def get_or_create_asset(self, db: Session, ticker: str, source_id: int) -> Asset:
        asset = self._get_asset(db, ticker, source_id)
        if not asset:
            asset = Asset(ticker=ticker.upper(), source_id=source_id)
            db.add(asset)
            db.flush()
        return asset

    def _update_asset_stats(self, db: Session, asset_id: int) -> None:
        """Update min_date, max_date, and row_count for an asset based on M1 data."""
        stats = db.execute(
            select(
                func.min(OhlcvM1.timestamp).label("min_ts"),
                func.max(OhlcvM1.timestamp).label("max_ts"),
                func.count(OhlcvM1.timestamp).label("count"),
            ).where(OhlcvM1.asset_id == asset_id)
        ).first()

        asset = db.get(Asset, asset_id)
        if asset:
            asset.min_date = stats.min_ts if stats else None
            asset.max_date = stats.max_ts if stats else None
            asset.row_count = stats.count if stats else 0
            db.flush()

    def list_databases(self) -> list[dict]:
        """Return all catalog entries (Source/Asset/Timeframe combinations)."""
        with self._get_db() as db:
            m1_query = (
                select(
                    Source.name.label("source"),
                    Asset.ticker.label("asset"),
                    Asset.min_date,
                    Asset.max_date,
                    Asset.row_count.label("rows"),
                )
                .join(Asset, Asset.source_id == Source.id)
                .where(Asset.row_count > 0)
            )

            derived_query = (
                select(
                    Source.name.label("source"),
                    Asset.ticker.label("asset"),
                    OhlcvResampled.timeframe.label("timeframe"),
                    func.min(OhlcvResampled.timestamp).label("min_date"),
                    func.max(OhlcvResampled.timestamp).label("max_date"),
                    func.count(OhlcvResampled.timestamp).label("rows"),
                )
                .join(Asset, Asset.id == OhlcvResampled.asset_id)
                .join(Source, Source.id == Asset.source_id)
                .group_by(Source.name, Asset.ticker, OhlcvResampled.timeframe)
            )

            m1_results = db.execute(m1_query).all()
            derived_results = db.execute(derived_query).all()

            dbs = [
                {
                    "source": r.source,
                    "asset": r.asset,
                    "timeframe": "M1",
                    "rows": int(r.rows),
                    "start_date": str(r.min_date) if r.min_date else None,
                    "end_date": str(r.max_date) if r.max_date else None,
                }
                for r in m1_results
            ]
            dbs.extend(
                {
                    "source": r.source,
                    "asset": r.asset,
                    "timeframe": r.timeframe,
                    "rows": int(r.rows),
                    "start_date": str(r.min_date) if r.min_date else None,
                    "end_date": str(r.max_date) if r.max_date else None,
                }
                for r in derived_results
            )
            return sorted(
                dbs, key=lambda item: (item["source"], item["asset"], item["timeframe"])
            )

    def get_stats(self) -> dict:
        """Return aggregate statistics across all stored databases."""
        with self._get_db() as db:
            sources_count = db.execute(select(func.count(Source.id))).scalar()
            assets_count = db.execute(select(func.count(Asset.id))).scalar()
            total_rows = db.execute(select(func.sum(Asset.row_count))).scalar() or 0

            sources_stats = db.execute(
                select(Source.name, func.count(Asset.id))
                .join(Asset)
                .group_by(Source.name)
            ).all()

            return {
                "sources_count": sources_count,
                "assets_count": assets_count,
                "sources": {name: count for name, count in sources_stats},
                "total_rows": total_rows,
            }

    # ------------------------------------------------------------------
    # Core I/O (TimescaleDB)
    # ------------------------------------------------------------------

    # Maximum number of rows per INSERT statement to stay below
    # PostgreSQL's per-statement parameter limit (~32 767).
    # 5 000 rows × 7 columns = 35 000 params — well within bounds.
    _INSERT_BATCH_SIZE = 5_000

    def save_data(
        self,
        df: pd.DataFrame,
        source: str,
        asset: str,
        timeframe: str,
        update_stats: bool = True,
    ) -> None:
        """Save data to TimescaleDB.

        M1 writes target the hypertable. Derived timeframes target the
        persisted resampled table.
        """
        normalized_timeframe = self._normalize_timeframe(timeframe)

        if df.empty:
            return

        with self._get_db() as db:
            if normalized_timeframe == "M1":
                src = self.get_or_create_source(db, source)
                ast = self.get_or_create_asset(db, asset, src.id)
            else:
                src = self._get_source(db, source)
                if not src:
                    raise FileNotFoundError(
                        f"Cannot save {normalized_timeframe}: source not found: {source}"
                    )
                ast = self._get_asset(db, asset, src.id)
                if not ast:
                    raise FileNotFoundError(
                        f"Cannot save {normalized_timeframe}: asset not found: {source} -> {asset}"
                    )

            df_records = self._prepare_ohlcv_records(df, ast.id)

            if normalized_timeframe == "M1":
                records = df_records[
                    ["timestamp", "asset_id", "open", "high", "low", "close", "volume"]
                ].to_dict(orient="records")
                self._upsert_m1_records(db, records)
            else:
                df_records["timeframe"] = normalized_timeframe
                records = df_records[
                    [
                        "timestamp",
                        "asset_id",
                        "timeframe",
                        "open",
                        "high",
                        "low",
                        "close",
                        "volume",
                    ]
                ].to_dict(orient="records")
                self._upsert_resampled_records(db, records)

            db.commit()

            if update_stats and normalized_timeframe == "M1":
                # Update asset metadata
                self._update_asset_stats(db, ast.id)
                db.commit()

    def append_data(
        self,
        df: pd.DataFrame,
        source: str,
        asset: str,
        timeframe: str,
        update_stats: bool = True,
    ) -> None:
        """Append data (same as save_data due to ON CONFLICT logic)."""
        return self.save_data(df, source, asset, timeframe, update_stats=update_stats)

    def replace_data(
        self, df: pd.DataFrame, source: str, asset: str, timeframe: str
    ) -> None:
        """Replace all persisted rows for a derived timeframe."""
        normalized_timeframe = self._normalize_timeframe(timeframe)
        if normalized_timeframe == "M1":
            raise ValueError("replace_data only supports derived timeframes.")

        with self._get_db() as db:
            src = self._get_source(db, source)
            if not src:
                raise FileNotFoundError(f"Source not found: {source}")

            ast = self._get_asset(db, asset, src.id)
            if not ast:
                raise FileNotFoundError(f"Asset not found: {source} -> {asset}")

            db.execute(
                delete(OhlcvResampled).where(
                    OhlcvResampled.asset_id == ast.id,
                    OhlcvResampled.timeframe == normalized_timeframe,
                )
            )

            if not df.empty:
                df_records = self._prepare_ohlcv_records(df, ast.id)
                df_records["timeframe"] = normalized_timeframe
                records = df_records[
                    [
                        "timestamp",
                        "asset_id",
                        "timeframe",
                        "open",
                        "high",
                        "low",
                        "close",
                        "volume",
                    ]
                ].to_dict(orient="records")
                self._upsert_resampled_records(db, records)

            db.commit()

    def update_stats(self, source: str, asset: str) -> None:
        """Manually trigger asset statistics recalculation. Useful after bulk uploads."""
        with self._get_db() as db:
            src = self.get_or_create_source(db, source)
            ast = self.get_or_create_asset(db, asset, src.id)
            self._update_asset_stats(db, ast.id)
            db.commit()

    def load_data(self, source: str, asset: str, timeframe: str) -> pd.DataFrame:
        """Load data from TimescaleDB."""
        normalized_timeframe = self._normalize_timeframe(timeframe)

        with self._get_db() as db:
            src = self._get_source(db, source)
            if not src:
                raise FileNotFoundError(f"Source not found: {source}")

            ast = self._get_asset(db, asset, src.id)
            if not ast:
                raise FileNotFoundError(f"Asset not found: {source} -> {asset}")

            if normalized_timeframe == "M1":
                query = """
                    SELECT timestamp, open, high, low, close, volume
                    FROM ohlcv_m1
                    WHERE asset_id = :aid
                    ORDER BY timestamp ASC
                """
                params = {"aid": ast.id}
            else:
                query = """
                    SELECT timestamp, open, high, low, close, volume
                    FROM ohlcv_resampled
                    WHERE asset_id = :aid AND timeframe = :timeframe
                    ORDER BY timestamp ASC
                """
                params = {"aid": ast.id, "timeframe": normalized_timeframe}

            df = pd.read_sql(
                text(query),
                con=engine,
                params=params,
                index_col="timestamp",
                parse_dates=["timestamp"],
            )

            if df.empty:
                raise FileNotFoundError(
                    f"Timeframe not found: {source} -> {asset} ({normalized_timeframe})"
                )

            # Capitalize columns to maintain compatibility with DataManager expectations
            df.columns = ["Open", "High", "Low", "Close", "Volume"]
            return df

    def delete_database(
        self, source: str, asset: str, timeframe: str | None = None
    ) -> bool:
        """Delete data for an asset.

        Deleting timeframe=None removes the entire asset metadata and all OHLCV data.
        """
        with self._get_db() as db:
            src = self._get_source(db, source)
            if not src:
                return False

            ast = self._get_asset(db, asset, src.id)
            if not ast:
                return False

            normalized_timeframe = (
                self._normalize_timeframe(timeframe) if timeframe else None
            )

            if not normalized_timeframe:
                db.execute(
                    delete(OhlcvResampled).where(OhlcvResampled.asset_id == ast.id)
                )
                db.execute(delete(OhlcvM1).where(OhlcvM1.asset_id == ast.id))
                db.delete(ast)
                db.commit()
                return True

            if normalized_timeframe == "M1":
                result = db.execute(delete(OhlcvM1).where(OhlcvM1.asset_id == ast.id))
                self._update_asset_stats(db, ast.id)
                db.commit()
                return result.rowcount > 0

            result = db.execute(
                delete(OhlcvResampled).where(
                    OhlcvResampled.asset_id == ast.id,
                    OhlcvResampled.timeframe == normalized_timeframe,
                )
            )
            db.commit()
            return result.rowcount > 0

    def delete_all(self) -> bool:
        """Delete all sources, assets and data."""
        with self._get_db() as db:
            db.execute(delete(EconomicObservation))
            db.execute(delete(EconomicSeries))
            db.execute(delete(OhlcvResampled))
            db.execute(delete(OhlcvM1))
            db.execute(delete(Asset))
            db.execute(delete(Source))
            db.commit()
            return True

    def get_database_info(self, source: str, asset: str, timeframe: str) -> dict:
        """Return metadata for a specific database."""
        normalized_timeframe = self._normalize_timeframe(timeframe)

        with self._get_db() as db:
            src = self._get_source(db, source)
            if not src:
                return {"status": "Not Found"}

            ast = self._get_asset(db, asset, src.id)
            if not ast:
                return {"status": "Not Found"}

            if normalized_timeframe == "M1":
                if not ast.row_count or not ast.min_date or not ast.max_date:
                    return {"status": "Not Found"}

                return {
                    "source": source.lower(),
                    "asset": asset.upper(),
                    "timeframe": normalized_timeframe,
                    "rows": ast.row_count,
                    "start_date": str(ast.min_date),
                    "end_date": str(ast.max_date),
                }

            stats = db.execute(
                select(
                    func.count(OhlcvResampled.timestamp).label("rows"),
                    func.min(OhlcvResampled.timestamp).label("min_date"),
                    func.max(OhlcvResampled.timestamp).label("max_date"),
                ).where(
                    OhlcvResampled.asset_id == ast.id,
                    OhlcvResampled.timeframe == normalized_timeframe,
                )
            ).one()

            if not stats.rows or not stats.min_date or not stats.max_date:
                return {"status": "Not Found"}

            return {
                "source": source.lower(),
                "asset": asset.upper(),
                "timeframe": normalized_timeframe,
                "rows": int(stats.rows),
                "start_date": str(stats.min_date),
                "end_date": str(stats.max_date),
            }
