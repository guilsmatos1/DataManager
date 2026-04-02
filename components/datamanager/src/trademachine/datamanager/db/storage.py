from typing import cast

import pandas as pd
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session
from trademachine.datamanager.db.database import SessionLocal, engine
from trademachine.datamanager.db.models import (
    Asset,
    EconomicObservation,
    EconomicSeries,
    OhlcvM1,
    Source,
)


class StorageManager:
    """Manages OHLCV storage using TimescaleDB (PostgreSQL) with Continuous Aggregates.

    Layout:
        - Relational tables: sources, assets (metadata catalog)
        - Hypertable: ohlcv_m1 (primary 1-minute data)
        - Continuous Aggregates: ohlcv_m5, ohlcv_h1, etc. (derived timeframes)

    Note:
        We only store M1 data explicitly. Higher timeframes are queried from
        TimescaleDB materialized views.
    """

    TF_VIEW_MAPPING = {
        "M1": "ohlcv_m1",
        "M5": "ohlcv_m5",
        "M15": "ohlcv_m15",
        "H1": "ohlcv_h1",
        "H4": "ohlcv_h4",
        "D1": "ohlcv_d1",
    }

    def __init__(self):
        pass

    def check_connection(self) -> None:
        """Simple health check to verify DB connectivity on startup."""
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

    def _get_db(self) -> Session:
        return cast(Session, SessionLocal())

    # ------------------------------------------------------------------
    # Catalog operations (SQLAlchemy)
    # ------------------------------------------------------------------

    def get_or_create_source(self, db: Session, name: str) -> Source:
        source = db.execute(
            select(Source).where(Source.name == name.lower())
        ).scalar_one_or_none()
        if not source:
            source = Source(name=name.lower())
            db.add(source)
            db.flush()
        return source

    def get_or_create_asset(self, db: Session, ticker: str, source_id: int) -> Asset:
        asset = db.execute(
            select(Asset).where(
                Asset.ticker == ticker.upper(), Asset.source_id == source_id
            )
        ).scalar_one_or_none()
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
            query = select(
                Source.name.label("source"),
                Asset.ticker.label("asset"),
                Asset.min_date,
                Asset.max_date,
                Asset.row_count.label("rows"),
            ).join(Asset, Asset.source_id == Source.id)

            results = db.execute(query).all()

            # TimescaleDB has fixed timeframes via views.
            # We return M1 info for each asset as a baseline.
            dbs = []
            for r in results:
                dbs.append(
                    {
                        "source": r.source,
                        "asset": r.asset,
                        "timeframe": "M1",
                        "rows": r.rows,
                        "start_date": str(r.min_date) if r.min_date else None,
                        "end_date": str(r.max_date) if r.max_date else None,
                    }
                )
            return dbs

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
        """Save data to TimescaleDB. Supports only M1 for writes.

        Upserts data into the ohlcv_m1 hypertable in batches to avoid
        exceeding PostgreSQL's per-statement parameter limit.
        """
        if timeframe.upper() != "M1":
            raise ValueError(
                "TimescaleDB storage only supports direct writes to M1 timeframe."
            )

        if df.empty:
            return

        with self._get_db() as db:
            src = self.get_or_create_source(db, source)
            ast = self.get_or_create_asset(db, asset, src.id)

            # Ensure DatetimeIndex
            if not isinstance(df.index, pd.DatetimeIndex):
                for col in ["datetime", "date", "time"]:
                    if col in df.columns:
                        df[col] = pd.to_datetime(df[col])
                        df.set_index(col, inplace=True)
                        break

            # Prepare data for bulk insert
            df_records = df.copy()
            df_records.index.name = "timestamp"
            df_records = df_records.reset_index()

            # Normalize timestamp to UTC naive
            if getattr(df_records["timestamp"].dt, "tz", None) is not None:
                df_records["timestamp"] = df_records["timestamp"].dt.tz_convert(None)

            df_records["asset_id"] = ast.id
            df_records.columns = df_records.columns.str.lower()

            # Type cast to ensure float
            for col in ["open", "high", "low", "close", "volume"]:
                df_records[col] = df_records[col].astype(float)

            records = df_records[
                ["timestamp", "asset_id", "open", "high", "low", "close", "volume"]
            ].to_dict(orient="records")

            total_batches = (
                len(records) + self._INSERT_BATCH_SIZE - 1
            ) // self._INSERT_BATCH_SIZE
            from tqdm import tqdm

            with tqdm(
                total=total_batches,
                desc=f"Saving {asset} to DB",
                unit="batch",
                leave=False,
            ) as pbar:
                # Bulk upsert in batches using PostgreSQL's ON CONFLICT
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

            db.commit()

            if update_stats:
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

    def update_stats(self, source: str, asset: str) -> None:
        """Manually trigger asset statistics recalculation. Useful after bulk uploads."""
        with self._get_db() as db:
            src = self.get_or_create_source(db, source)
            ast = self.get_or_create_asset(db, asset, src.id)
            self._update_asset_stats(db, ast.id)
            db.commit()

    def load_data(self, source: str, asset: str, timeframe: str) -> pd.DataFrame:
        """Load data from TimescaleDB (hypertable or continuous aggregate)."""
        table_name = self.TF_VIEW_MAPPING.get(timeframe.upper())
        if not table_name:
            raise ValueError(
                f"Timeframe {timeframe} not supported by TimescaleDB storage."
            )

        with self._get_db() as db:
            src = db.execute(
                select(Source).where(Source.name == source.lower())
            ).scalar_one_or_none()
            if not src:
                raise FileNotFoundError(f"Source not found: {source}")

            ast = db.execute(
                select(Asset).where(
                    Asset.ticker == asset.upper(), Asset.source_id == src.id
                )
            ).scalar_one_or_none()

            if not ast:
                raise FileNotFoundError(f"Asset not found: {source} -> {asset}")

            # Use pandas read_sql for efficiency
            # We must use literal table name as it's a dynamic view.
            # Safety: table_name is strictly mapped from TF_VIEW_MAPPING.
            query = f"SELECT timestamp, open, high, low, close, volume FROM {table_name} WHERE asset_id = :aid ORDER BY timestamp ASC"  # noqa: S608

            df = pd.read_sql(
                text(query),
                con=engine,
                params={"aid": ast.id},
                index_col="timestamp",
                parse_dates=["timestamp"],
            )

            # Capitalize columns to maintain compatibility with DataManager expectations
            df.columns = ["Open", "High", "Low", "Close", "Volume"]
            return df

    def delete_database(
        self, source: str, asset: str, timeframe: str | None = None
    ) -> bool:
        """Delete data for an asset.

        Note: timeframe specific deletion is only supported for M1 (as views are derived).
        Deleting timeframe=None removes the entire asset metadata and its M1 data.
        """
        with self._get_db() as db:
            src = db.execute(
                select(Source).where(Source.name == source.lower())
            ).scalar_one_or_none()
            if not src:
                return False

            ast = db.execute(
                select(Asset).where(
                    Asset.ticker == asset.upper(), Asset.source_id == src.id
                )
            ).scalar_one_or_none()

            if not ast:
                return False

            if timeframe and timeframe.upper() != "M1":
                raise ValueError(
                    "Deletion of specific timeframe data is only supported for M1."
                )

            # Delete M1 data (this will automatically affect views)
            db.execute(delete(OhlcvM1).where(OhlcvM1.asset_id == ast.id))

            if not timeframe:
                # Delete asset metadata too
                db.delete(ast)
            else:
                # Just update stats if only data was deleted
                self._update_asset_stats(db, ast.id)

            db.commit()
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

    def get_database_info(self, source: str, asset: str, timeframe: str) -> dict:
        """Return metadata for a specific database."""
        with self._get_db() as db:
            src = db.execute(
                select(Source).where(Source.name == source.lower())
            ).scalar_one_or_none()
            if not src:
                return {"status": "Not Found"}

            ast = db.execute(
                select(Asset).where(
                    Asset.ticker == asset.upper(), Asset.source_id == src.id
                )
            ).scalar_one_or_none()

            if not ast:
                return {"status": "Not Found"}

            return {
                "source": source.lower(),
                "asset": asset.upper(),
                "timeframe": timeframe.upper(),
                "rows": ast.row_count if timeframe.upper() == "M1" else None,
                "start_date": str(ast.min_date) if ast.min_date else None,
                "end_date": str(ast.max_date) if ast.max_date else None,
            }
