import logging
from typing import cast

import pandas as pd
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session
from trademachine.core.logger import LOGGER_NAME
from trademachine.datamanager.db.models import (
    Asset,
    EconomicObservation,
    EconomicSeries,
    OhlcvM1,
    Source,
)
from trademachine.datamanager.db.processor import DataProcessor
from trademachine.datamanager.infrastructure.database import SessionLocal, engine

logger = logging.getLogger(LOGGER_NAME)


class StorageManager:
    """Manages OHLCV storage using TimescaleDB (PostgreSQL).

    Layout:
        - Relational tables: sources, assets (metadata catalog)
        - Hypertable: ohlcv_m1 (primary 1-minute data, write target)
        - Continuous aggregates: ohlcv_{tf} — created on demand via resample command
    """

    SUPPORTED_TIMEFRAMES = frozenset(DataProcessor.TF_MAPPING)

    # Maps each derived timeframe to its TimescaleDB time_bucket interval string.
    TF_TO_BUCKET: dict[str, str] = {
        "M2": "2 minutes",
        "M5": "5 minutes",
        "M10": "10 minutes",
        "M15": "15 minutes",
        "M30": "30 minutes",
        "H1": "1 hour",
        "H2": "2 hours",
        "H3": "3 hours",
        "H4": "4 hours",
        "H6": "6 hours",
        "D1": "1 day",
        "W1": "7 days",
    }

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

    _INSERT_BATCH_SIZE = 5_000

    def _upsert_m1_records(self, db: Session, records: list[dict]) -> None:
        from tqdm import tqdm

        total_batches = (
            len(records) + self._INSERT_BATCH_SIZE - 1
        ) // self._INSERT_BATCH_SIZE
        with tqdm(
            total=total_batches, desc="Saving M1 to DB", unit="batch", leave=False
        ) as pbar:
            for i in range(0, len(records), self._INSERT_BATCH_SIZE):
                batch = records[i : i + self._INSERT_BATCH_SIZE]
                stmt = pg_insert(OhlcvM1).values(batch)
                upsert_stmt = stmt.on_conflict_do_update(
                    index_elements=[OhlcvM1.timestamp, OhlcvM1.asset_id],
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

    # ------------------------------------------------------------------
    # Continuous aggregate management
    # ------------------------------------------------------------------

    def aggregate_exists(self, timeframe: str) -> bool:
        """Returns True if a continuous aggregate view exists for the given timeframe."""
        view_name = f"ohlcv_{timeframe.lower()}"
        with engine.connect() as conn:
            result = conn.execute(
                text(
                    "SELECT 1 FROM timescaledb_information.continuous_aggregates "
                    "WHERE view_name = :vn"
                ),
                {"vn": view_name},
            ).scalar()
        return result is not None

    def create_continuous_aggregate(self, timeframe: str) -> None:
        """Creates a TimescaleDB continuous aggregate for the given timeframe.

        Idempotent: no-op if the aggregate already exists.
        Sets up an auto-refresh policy and backfills all existing M1 data.
        """
        tf = timeframe.upper()
        if tf not in self.TF_TO_BUCKET:
            raise ValueError(
                f"Timeframe {timeframe} not supported for continuous aggregates. "
                f"Use: {sorted(self.TF_TO_BUCKET)}"
            )

        if self.aggregate_exists(tf):
            logger.info(
                f"Continuous aggregate ohlcv_{tf.lower()} already exists — skipping."
            )
            return

        interval = self.TF_TO_BUCKET[tf]
        view_name = f"ohlcv_{tf.lower()}"

        create_sql = f"""
                CREATE MATERIALIZED VIEW {view_name}
                WITH (timescaledb.continuous) AS
                SELECT
                    time_bucket('{interval}', timestamp) AS timestamp,
                    asset_id,
                    first(open, timestamp)  AS open,
                    max(high)               AS high,
                    min(low)                AS low,
                    last(close, timestamp)  AS close,
                    sum(volume)             AS volume
                FROM ohlcv_m1
                GROUP BY time_bucket('{interval}', timestamp), asset_id
                WITH NO DATA
            """  # noqa: S608
        policy_sql = f"""
                SELECT add_continuous_aggregate_policy('{view_name}',
                    start_offset      => INTERVAL '3 {interval}',
                    end_offset        => INTERVAL '1 {interval}',
                    schedule_interval => INTERVAL '{interval}')
            """  # noqa: S608
        refresh_sql = f"CALL refresh_continuous_aggregate('{view_name}', NULL, NULL)"  # noqa: S608

        # DDL and CALL must run outside an explicit transaction (AUTOCOMMIT).
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text(create_sql))
            conn.execute(text(policy_sql))
            conn.execute(text(refresh_sql))

        logger.info(f"Continuous aggregate {view_name} created and backfilled.")

    def refresh_continuous_aggregate(self, timeframe: str) -> None:
        """Manually refresh a continuous aggregate to pick up recent M1 insertions."""
        view_name = f"ohlcv_{timeframe.lower()}"
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(
                text(f"CALL refresh_continuous_aggregate('{view_name}', NULL, NULL)")
            )

    def drop_continuous_aggregate(self, timeframe: str) -> None:
        """Drops a continuous aggregate view entirely (affects all assets)."""
        tf = timeframe.upper()
        if not self.aggregate_exists(tf):
            return
        view_name = f"ohlcv_{tf.lower()}"
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text(f"DROP MATERIALIZED VIEW IF EXISTS {view_name} CASCADE"))
        logger.info(f"Continuous aggregate {view_name} dropped.")

    # ------------------------------------------------------------------
    # Core I/O (TimescaleDB)
    # ------------------------------------------------------------------

    def save_data(
        self,
        df: pd.DataFrame,
        source: str,
        asset: str,
        timeframe: str,
        update_stats: bool = True,
    ) -> None:
        """Save M1 data to the ohlcv_m1 hypertable.

        Derived timeframes are populated automatically by TimescaleDB continuous
        aggregates — they cannot be written directly.
        """
        normalized_timeframe = self._normalize_timeframe(timeframe)
        if normalized_timeframe != "M1":
            raise ValueError(
                "save_data only supports M1. Derived timeframes are managed "
                "by continuous aggregates — use the resample command."
            )

        if df.empty:
            return

        with self._get_db() as db:
            src = self.get_or_create_source(db, source)
            ast = self.get_or_create_asset(db, asset, src.id)
            df_records = self._prepare_ohlcv_records(df, ast.id)
            records = df_records[
                ["timestamp", "asset_id", "open", "high", "low", "close", "volume"]
            ].to_dict(orient="records")
            self._upsert_m1_records(db, records)
            db.commit()

            if update_stats:
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
        """Append M1 data (same as save_data due to ON CONFLICT logic)."""
        return self.save_data(df, source, asset, timeframe, update_stats=update_stats)

    def update_stats(self, source: str, asset: str) -> None:
        """Manually trigger asset statistics recalculation. Useful after bulk uploads."""
        with self._get_db() as db:
            src = self.get_or_create_source(db, source)
            ast = self.get_or_create_asset(db, asset, src.id)
            self._update_asset_stats(db, ast.id)
            db.commit()

    def load_data(self, source: str, asset: str, timeframe: str) -> pd.DataFrame:
        """Load OHLCV data from TimescaleDB.

        M1 reads from the hypertable. Derived timeframes read from their
        continuous aggregate view (must have been created via the resample command).
        """
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
                params: dict = {"aid": ast.id}
            else:
                if not self.aggregate_exists(normalized_timeframe):
                    raise FileNotFoundError(
                        f"Timeframe {normalized_timeframe} not available. "
                        f"Run 'resample {asset} {normalized_timeframe}' first to create it."
                    )
                view_name = f"ohlcv_{normalized_timeframe.lower()}"
                query = f"""
                    SELECT timestamp, open, high, low, close, volume
                    FROM {view_name}
                    WHERE asset_id = :aid
                    ORDER BY timestamp ASC
                """  # noqa: S608
                params = {"aid": ast.id}

            df = pd.read_sql(
                text(query),
                con=engine,
                params=params,
                index_col="timestamp",
                parse_dates=["timestamp"],
            )

            if df.empty:
                raise FileNotFoundError(
                    f"No data found: {source} -> {asset} ({normalized_timeframe})"
                )

            df.columns = ["Open", "High", "Low", "Close", "Volume"]
            return df

    # ------------------------------------------------------------------
    # Catalog queries
    # ------------------------------------------------------------------

    def list_databases(self) -> list[dict]:
        """Return all catalog entries: M1 hypertable + active continuous aggregates."""
        with self._get_db() as db:
            m1_results = db.execute(
                select(
                    Source.name.label("source"),
                    Asset.ticker.label("asset"),
                    Asset.min_date,
                    Asset.max_date,
                    Asset.row_count.label("rows"),
                )
                .join(Asset, Asset.source_id == Source.id)
                .where(Asset.row_count > 0)
            ).all()

            dbs: list[dict] = [
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

            # Enumerate existing continuous aggregate views created by us.
            agg_views = db.execute(
                text(
                    "SELECT view_name FROM timescaledb_information.continuous_aggregates "
                    "WHERE view_name LIKE 'ohlcv_%'"
                )
            ).fetchall()

            for (view_name,) in agg_views:
                tf = view_name[len("ohlcv_") :].upper()
                per_asset = db.execute(
                    text(f"""
                        SELECT s.name, a.ticker,
                               COUNT(*)         AS rows,
                               MIN(v.timestamp) AS min_date,
                               MAX(v.timestamp) AS max_date
                        FROM {view_name} v
                        JOIN assets  a ON a.id = v.asset_id
                        JOIN sources s ON s.id = a.source_id
                        GROUP BY s.name, a.ticker
                    """)  # noqa: S608
                ).fetchall()

                dbs.extend(
                    {
                        "source": r[0],
                        "asset": r[1],
                        "timeframe": tf,
                        "rows": int(r[2]),
                        "start_date": str(r[3]) if r[3] else None,
                        "end_date": str(r[4]) if r[4] else None,
                    }
                    for r in per_asset
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

            if not self.aggregate_exists(normalized_timeframe):
                return {"status": "Not Found"}

            view_name = f"ohlcv_{normalized_timeframe.lower()}"
            row = db.execute(
                text(f"""
                    SELECT COUNT(*)        AS rows,
                           MIN(timestamp) AS min_date,
                           MAX(timestamp) AS max_date
                    FROM {view_name}
                    WHERE asset_id = :aid
                """),  # noqa: S608
                {"aid": ast.id},
            ).one()

            if not row.rows or not row.min_date or not row.max_date:
                return {"status": "Not Found"}

            return {
                "source": source.lower(),
                "asset": asset.upper(),
                "timeframe": normalized_timeframe,
                "rows": int(row.rows),
                "start_date": str(row.min_date),
                "end_date": str(row.max_date),
            }

    def delete_database(
        self, source: str, asset: str, timeframe: str | None = None
    ) -> bool:
        """Delete data for an asset.

        - timeframe=None: deletes M1 data and the asset record. Continuous aggregate
          views are shared across all assets and are left intact.
        - timeframe="M1": deletes only the M1 rows for this asset.
        - timeframe=<derived>: drops the entire continuous aggregate view for that
          timeframe — this affects ALL assets, not just the requested one.
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
                db.execute(delete(OhlcvM1).where(OhlcvM1.asset_id == ast.id))
                db.delete(ast)
                db.commit()
                return True

            if normalized_timeframe == "M1":
                result = db.execute(delete(OhlcvM1).where(OhlcvM1.asset_id == ast.id))
                self._update_asset_stats(db, ast.id)
                db.commit()
                return result.rowcount > 0

            # Derived timeframes are continuous aggregate views shared across all assets.
            # Dropping it will remove this timeframe for ALL assets.
            self.drop_continuous_aggregate(normalized_timeframe)
            return True

    def delete_all(self) -> bool:
        """Delete all sources, assets and data."""
        with self._get_db() as db:
            db.execute(delete(EconomicObservation))
            db.execute(delete(EconomicSeries))
            db.execute(delete(OhlcvM1))
            db.execute(delete(Asset))
            db.execute(delete(Source))
            db.commit()
            return True
