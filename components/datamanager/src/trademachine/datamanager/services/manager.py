import logging
from datetime import UTC, datetime
from typing import cast

import pandas as pd
from colorama import init
from tqdm import tqdm
from trademachine.core.logger import LOGGER_NAME
from trademachine.datamanager.db.processor import DataProcessor
from trademachine.datamanager.db.storage import StorageManager
from trademachine.datamanager.fetchers import get_all_fetchers
from trademachine.datamanager.fetchers.base import BaseFetcher

# Disable excessive logging from external libraries
logging.getLogger("dukascopy_python").setLevel(logging.WARNING)
logging.getLogger("DUKASCRIPT").setLevel(logging.WARNING)

init(autoreset=True)

logger = logging.getLogger(LOGGER_NAME)

# Quality check thresholds
SPIKE_THRESHOLD = 0.50  # 50% price change considered a spike
FROZEN_BARS_WINDOW = (
    4  # consecutive identical OHLC bars to flag as frozen (bar + 3 shifts)
)


class DataManager:
    """
    Central controller of the application.
    """

    BASE_TIMEFRAME = "M1"

    def __init__(self):
        self.storage = StorageManager()

        # Dynamic discovery of supported data sources
        self._fetchers = {}
        for fetcher_class in get_all_fetchers():
            try:
                instance = fetcher_class()
                self._fetchers[instance.source_name.upper()] = instance
            except Exception as e:
                logger.warning(
                    f"Failed to initialize fetcher {fetcher_class.__name__}: {e}"
                )

    def _get_fetcher(self, source_name: str) -> BaseFetcher:
        source = source_name.upper()
        if source not in self._fetchers:
            raise ValueError(
                f"Data source not supported: {source_name}. Available: {list(self._fetchers.keys())}"
            )
        return self._fetchers[source]

    def download_data(
        self, source: str, asset: str, start_date: datetime, end_date: datetime
    ) -> None:
        """Downloads and saves data in M1 using yearly chunks to save memory."""
        info = self.storage.get_database_info(source, asset, self.BASE_TIMEFRAME)
        if info.get("status") != "Not Found":
            logger.info(
                f"Database {asset} ({self.BASE_TIMEFRAME}) already exists in {source}. Proceeding with idempotent download (upsert)."
            )

        logger.info(f"Starting chunked download of {asset} via {source.upper()}...")
        fetcher = self._get_fetcher(source)

        # Split the date range into yearly chunks
        chunks = []
        current_start = start_date
        while current_start < end_date:
            current_end = min(current_start + pd.DateOffset(years=1), end_date)
            chunks.append((current_start, current_end))
            current_start = current_end

        total_rows = 0
        failed_chunks = 0

        total_days = (end_date - start_date).days
        if total_days <= 0:
            total_days = 1

        with tqdm(total=total_days, desc=f"Downloading {asset}", unit="days") as pbar:
            for c_start, c_end in chunks:
                try:
                    df_chunk = fetcher.fetch_data(asset, c_start, c_end, pbar=pbar)

                    if df_chunk is not None and not df_chunk.empty:
                        self.storage.append_data(
                            df_chunk,
                            source,
                            asset,
                            timeframe=self.BASE_TIMEFRAME,
                            update_stats=False,
                        )
                        total_rows += len(df_chunk)
                    else:
                        failed_chunks += 1

                except ValueError as e:
                    logger.error(f"    [ABORT] Critical error for {asset}: {e}")
                    break
                except Exception as e:
                    failed_chunks += 1
                    logger.error(
                        f"    [ERROR] Failed to fetch/save chunk {c_start.date()}: {e}"
                    )

        if total_rows > 0:
            # Refresh global statistics once after all batches
            logger.info(
                "Recalculating metadata catalog (this briefly takes a few seconds)..."
            )
            self.storage.update_stats(source, asset)

            logger.info(
                f"Database {asset} (M1) download complete! Total: {total_rows:,} rows."
            )
            if failed_chunks > 0:
                logger.warning(
                    f"    ⚠ {failed_chunks} chunk(s) failed — "
                    f"data may have gaps. Review errors above."
                )
        else:
            logger.error(f"No data was downloaded for {asset} (M1).")
            raise RuntimeError(
                f"Download failed: all {len(chunks)} chunk(s) returned no data for "
                f"{asset} via {source.upper()}. Check logs for details."
            )

    def resample_data(self, source: str, asset: str, timeframe: str) -> None:
        """Rebuilds and persists a derived timeframe from M1."""
        target_timeframe = timeframe.upper()
        if target_timeframe == self.BASE_TIMEFRAME:
            raise ValueError(
                "M1 is the source timeframe and cannot be rebuilt via resample."
            )
        if target_timeframe not in DataProcessor.TF_MAPPING:
            raise ValueError(
                f"Target timeframe not supported: {timeframe}. Use {list(DataProcessor.TF_MAPPING.keys())}"
            )

        try:
            m1_df = self.storage.load_data(source, asset, self.BASE_TIMEFRAME)
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                f"Cannot resample {asset} ({target_timeframe}) because the M1 base does not exist."
            ) from exc

        if m1_df.empty:
            raise ValueError(
                f"Cannot resample {asset} ({target_timeframe}) because the M1 base is empty."
            )

        resampled_df = DataProcessor.resample_ohlc(m1_df, target_timeframe)
        self.storage.replace_data(resampled_df, source, asset, target_timeframe)
        logger.info(
            f"Database {asset} ({target_timeframe}) rebuilt successfully with {len(resampled_df):,} rows."
        )

    def resample_database(self, source: str, asset: str, timeframe: str) -> None:
        """Backward-compatible alias for the explicit resample operation."""
        self.resample_data(source, asset, timeframe)

    def update_data(self, source: str, asset: str, timeframe: str = "M1") -> None:
        """Updates the M1 database with new data.

        If a derived timeframe is requested, it is rebuilt from the refreshed
        M1 base after the update step completes.
        """
        target_timeframe = timeframe.upper()
        # Always operate on M1 as the base — check its existence and freshness
        m1_info = self.storage.get_database_info(source, asset, self.BASE_TIMEFRAME)
        if m1_info.get("status") == "Not Found":
            logger.error(f"Database {asset} (M1) does not exist. Use 'download' first.")
            return

        last_date = datetime.fromisoformat(m1_info["end_date"])
        # Normalize to UTC-aware so the comparison with now (UTC) is consistent
        if last_date.tzinfo is None:
            last_date = last_date.replace(tzinfo=UTC)
        now = datetime.now(UTC)

        if last_date.date() >= now.date() and (now - last_date).total_seconds() < 3600:
            logger.info(f"{asset} M1 is already up to date.")
        else:
            logger.info(f"Updating {asset} M1 from {last_date}...")
            fetcher = self._get_fetcher(source)
            new_df = fetcher.fetch_data(asset, last_date, now)

            if new_df is not None and not new_df.empty:
                self.storage.append_data(new_df, source, asset, self.BASE_TIMEFRAME)
                logger.info(f"Database {asset} (M1) updated successfully!")
            else:
                logger.warning(
                    f"No new data returned for {asset} M1. Nothing appended."
                )

        if target_timeframe != self.BASE_TIMEFRAME:
            self.resample_data(source, asset, target_timeframe)

    def update_all_databases(self) -> None:
        """Updates all M1 databases in TimescaleDB."""
        dbs = self.list_all()
        if not dbs:
            logger.info("No databases found to update.")
            return

        logger.info("=== GLOBAL DATABASE UPDATE (TimescaleDB) ===")

        # In TimescaleDB mode, we only need to update M1
        m1_dbs = [db for db in dbs if db["timeframe"] == "M1"]

        if not m1_dbs:
            logger.info("No M1 databases found to update.")
            return

        logger.info(f"Detected {len(m1_dbs)} original database(s) (M1).")

        ok, failed = 0, []

        with tqdm(m1_dbs, desc="Updating M1 databases") as pbar:
            for db in pbar:
                pbar.set_description(f"Updating {db['asset']}")
                try:
                    self.update_data(db["source"], db["asset"], "M1")
                    ok += 1
                except Exception as e:
                    failed.append(f"{db['source']}/{db['asset']} (M1)")
                    logger.error(
                        f"Error updating M1 database ({db['source']}/{db['asset']}): {e}"
                    )

        if failed:
            logger.warning(
                f"=== UPDATE COMPLETE: {ok}/{len(m1_dbs)} succeeded — {len(failed)} failed ==="
            )
            for entry in failed:
                logger.warning(f"  ✗ {entry}")
        else:
            logger.info(f"=== UPDATE COMPLETE: {ok}/{len(m1_dbs)} succeeded ===")

    def delete_database(
        self, source: str, asset: str, timeframe: str | None = None
    ) -> None:
        """Deletes database (or all timeframes of the asset)"""
        success = self.storage.delete_database(source, asset, timeframe)
        target = f"{source}/{asset}/{timeframe if timeframe else 'ALL'}"
        if success:
            logger.info(f"Database deleted: {target}")
        else:
            logger.warning(f"Database not found: {target}")

    def delete_all_databases(self) -> None:
        """Deletes all databases from all sources"""
        success = self.storage.delete_all()
        if success:
            logger.info("All databases were successfully deleted from TimescaleDB.")
        else:
            logger.error("Error deleting databases.")

    def info(self, source: str, asset: str, timeframe: str) -> dict:
        return cast(dict, self.storage.get_database_info(source, asset, timeframe))

    def list_all(self) -> list[dict]:
        """Returns the complete list of databases with their info."""
        return cast(list[dict], self.storage.list_databases())

    def show_search_summary(self) -> None:
        """Displays the total amount of assets from each source without listing."""
        logger.info("Summary of available assets for search:")

        for source_name, fetcher in self._fetchers.items():
            try:
                df = fetcher.search(query="")
                logger.info(f"  ● {source_name.capitalize()}: {len(df)} assets found")
            except Exception:
                # If search is not implemented or fails, show a generic message
                logger.info(
                    f"  ● {source_name.capitalize()}: Supports searching (Details via search command)"
                )

    def search_assets(
        self,
        source: str = "openbb",
        query: str | None = None,
        exchange: str | None = None,
    ) -> pd.DataFrame:
        """Search assets via the specified fetcher."""
        source_key = source.upper()
        if source_key not in self._fetchers:
            logger.warning(
                f"Source {source} not supported for search. Available: {list(self._fetchers.keys())}"
            )
            return pd.DataFrame()

        fetcher = self._fetchers[source_key]
        logger.info(f"Searching assets in {source_key}...")

        try:
            df = fetcher.search(query=query, exchange=exchange)

            if df.empty:
                logger.info(f"No asset found for these parameters in {source_key}.")
                return pd.DataFrame()

            return df

        except Exception as e:
            logger.error(f"Error searching assets in {source_key}: {e}")
            return pd.DataFrame()

    def check_quality(self, source: str, asset: str, timeframe: str = "M1") -> dict:
        """Performs advanced integrity and quality validations on the specified database."""
        df = self.storage.load_data(source, asset, timeframe)

        logger.info(
            f"=== QUALITY REPORT: {asset.upper()} ({timeframe}) - {source.upper()} ==="
        )
        logger.info(f"Total Registers Analyzed: {len(df):,}")

        failures_ohlc = 0
        failures_positive = 0
        failures_spikes = 0
        failures_frozen = 0
        first_failure_timestamps: list[str] = []

        # 1. OHLC Relations Test
        try:
            relations_mask = (
                (df["High"] >= df["Low"])
                & (df["High"] >= df["Open"])
                & (df["High"] >= df["Close"])
                & (df["Low"] <= df["Open"])
                & (df["Low"] <= df["Close"])
            )
            failures_ohlc = int((~relations_mask).sum())
            logger.info(f"1. OHLC Mathematical Relations : {failures_ohlc} error(s)")

            positive_mask = (
                (df["Open"] > 0)
                & (df["High"] > 0)
                & (df["Low"] > 0)
                & (df["Close"] > 0)
            )
            failures_positive = int((~positive_mask).sum())
            logger.info(f"2. Positive Prices Check      : {failures_positive} error(s)")

            price_change = df["Close"].pct_change().abs()
            failures_spikes = int((price_change > SPIKE_THRESHOLD).sum())
            logger.info(f"3. Abnormal Price Spikes (>50%): {failures_spikes} error(s)")

            is_static = (
                (df["Open"] == df["High"])
                & (df["High"] == df["Low"])
                & (df["Low"] == df["Close"])
            )
            frozen_mask = is_static
            for i in range(1, FROZEN_BARS_WINDOW):
                frozen_mask = frozen_mask & is_static.shift(i)
            failures_frozen = int(frozen_mask.sum())
            logger.info(f"4. Frozen Prices (Static OHLC) : {failures_frozen} error(s)")

            if failures_ohlc > 0 or failures_positive > 0:
                bad_data = df[~relations_mask | ~positive_mask].head(5)
                logger.warning("   ↳ First failure timestamps:")
                for ts in bad_data.index:
                    logger.warning(f"     - {ts}")
                    first_failure_timestamps.append(str(ts))

        except KeyError:
            logger.warning("Price Logic Tests : Ignored (Price columns missing)")

        # 5. Time Index Duplicates Test
        failures_dup = int(df.index.duplicated().sum())
        logger.info(f"5. Duplicated Registers      : {failures_dup} error(s)")

        # 6. Time Ordering Test (Monotonicity)
        time_diffs = df.index.to_series().diff()
        failures_ord = int((time_diffs < pd.Timedelta(seconds=0)).sum())
        logger.info(f"6. Time Ordering             : {failures_ord} error(s)")

        # 7. Gaps Analysis
        failures_gaps = 0
        first_gap_timestamps: list[str] = []
        if len(df) > 1:
            time_diffs = df.index.to_series().diff().dropna()
            expected_freq = time_diffs.median()
            gaps_mask = time_diffs > (expected_freq * 5)
            failures_gaps = int(gaps_mask.sum())
            logger.info(f"7. Absence of Data (Gaps)    : {failures_gaps} gap(s)")

            if failures_gaps > 0:
                gap_starts = df.index[1:][gaps_mask].tolist()[:5]
                logger.warning("   ↳ First gap start timestamps:")
                for ts in gap_starts:
                    logger.warning(f"     - {ts}")
                    first_gap_timestamps.append(str(ts))
        else:
            logger.info(
                "7. Absence of Data (Gaps)    : Ignored (Few data for analysis)"
            )

        return {
            "source": source,
            "asset": asset,
            "timeframe": timeframe,
            "total_rows": len(df),
            "ohlc_relation_errors": failures_ohlc,
            "non_positive_price_errors": failures_positive,
            "spike_errors": failures_spikes,
            "frozen_bar_errors": failures_frozen,
            "duplicate_index_errors": failures_dup,
            "ordering_errors": failures_ord,
            "gap_count": failures_gaps,
            "first_failure_timestamps": first_failure_timestamps,
            "first_gap_timestamps": first_gap_timestamps,
        }
