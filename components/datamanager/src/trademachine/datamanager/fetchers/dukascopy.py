import logging
from datetime import datetime, timedelta

import pandas as pd
from tqdm import tqdm
from trademachine.core.logger import LOGGER_NAME

from .base import FETCH_RETRY, BaseFetcher

# Disable internal prints and info from dukascopy-python
logging.getLogger("dukascopy_python").setLevel(logging.WARNING)
logging.getLogger("DUKASCRIPT").setLevel(logging.WARNING)

logger = logging.getLogger(LOGGER_NAME)


class DukascopyFetcher(BaseFetcher):
    """
    Downloads M1 data using the dukascopy-python library in chunks with a progress bar.
    """

    @property
    def source_name(self) -> str:
        return "Dukascopy"

    def fetch_data(
        self, asset: str, start_date: datetime, end_date: datetime, **kwargs
    ) -> pd.DataFrame:
        asset_upper = asset.upper()

        global_pbar = kwargs.get("pbar")

        from pathlib import Path

        # As the main script and workers run from the project root,
        # the metadata folder must be in the same directory where the command is run.
        csv_path = Path("projects/datamanager/metadata") / "dukas_assets.csv"

        if csv_path.exists():
            df_assets = pd.read_csv(csv_path).fillna("")

            # Check if it exists in the ticker or exact alias
            match = df_assets[
                (df_assets["ticker"].str.upper() == asset_upper)
                | (df_assets["alias"].str.upper() == asset_upper)
            ]

            if not match.empty:
                asset_clean = match.iloc[0]["ticker"]
            else:
                raise ValueError(
                    f"Asset '{asset_upper}' does not exist in the Dukascopy database. "
                    f"Use 'search --source dukascopy --query {asset_upper}' to query valid tickers and aliases."
                )
        else:
            # Provisional fallback in case the CSV file does not exist
            asset_clean = asset_upper

        dfs = []
        total_days = (end_date - start_date).days
        if total_days <= 0:
            total_days = 1

        # We will use 7-day chunks to balance request speed and progress bar feedback
        chunk_size = 7
        total_chunks = (total_days // chunk_size) + (
            1 if total_days % chunk_size != 0 else 0
        )

        from dukascopy_python import INTERVAL_MIN_1, OFFER_SIDE_BID, fetch

        @FETCH_RETRY
        def _fetch_chunk(cs: datetime, ce: datetime) -> pd.DataFrame:
            return fetch(
                instrument=asset_clean,
                interval=INTERVAL_MIN_1,
                offer_side=OFFER_SIDE_BID,
                start=cs,
                end=ce,
            )

        # Early-abort: if the first N consecutive weekday chunks all return empty,
        # the instrument is likely invalid — stop instead of running for hours.
        EARLY_ABORT_THRESHOLD = 10
        consecutive_empty = 0

        local_pbar = None
        if global_pbar is None:
            local_pbar = tqdm(
                total=total_chunks,
                desc=f"Fetching {asset_clean} (Dukascopy)",
                leave=False,
            )

        for i in range(total_chunks):
            chunk_start = start_date + timedelta(days=i * chunk_size)
            chunk_end = min(chunk_start + timedelta(days=chunk_size), end_date)

            try:
                df_chunk = _fetch_chunk(chunk_start, chunk_end)
                if df_chunk is not None and not df_chunk.empty:
                    dfs.append(df_chunk)
                    consecutive_empty = 0
                else:
                    consecutive_empty += 1
            except Exception as e:
                consecutive_empty += 1
                logger.debug(
                    f"[Dukascopy] Chunk {chunk_start.date()}–{chunk_end.date()} skipped: {e}"
                )

            if local_pbar is not None:
                local_pbar.update(1)
            if global_pbar is not None:
                global_pbar.update((chunk_end - chunk_start).days)

            # Early abort if no data received after many consecutive chunks —
            # skips the remainder of this date range (e.g. years before data exists)
            if consecutive_empty >= EARLY_ABORT_THRESHOLD and not dfs:
                logger.debug(
                    f"[Dukascopy] {consecutive_empty} consecutive chunks returned no data "
                    f"for '{asset_clean}' in {start_date.date()}–{end_date.date()}. Skipping period."
                )
                break

        if local_pbar is not None:
            local_pbar.close()

        if not dfs:
            # Return empty instead of raising error to handle gaps in chunked download
            return pd.DataFrame()

        df = pd.concat(dfs)

        # Dukascopy-python already returns a DF set by index.
        # Ensure it has no unwanted gaps and duplicates
        df = df[~df.index.duplicated(keep="last")]

        # Column and index processing
        self._normalize_timezone(df)
        self._normalize_columns(df)

        df.index.name = "datetime"
        df.sort_index(inplace=True)

        return df

    def search(self, query: str | None = None, **kwargs) -> pd.DataFrame:
        """Search Dukascopy offline database."""
        from pathlib import Path

        csv_path = Path("projects/datamanager/metadata") / "dukas_assets.csv"

        if not csv_path.exists():
            return pd.DataFrame()

        df = pd.read_csv(csv_path).fillna("")

        if query:
            # Case-insensitive search in ticker, alias or asset name
            mask = (
                df["ticker"].str.contains(query, case=False)
                | df["alias"].str.contains(query, case=False)
                | df["nome_do_ativo"].str.contains(query, case=False)
            )
            df = df[mask]

        return df
