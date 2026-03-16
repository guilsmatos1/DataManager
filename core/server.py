from datetime import datetime
from pathlib import Path
import pandas as pd
from data_management.storage import StorageManager
from data_management.processor import DataProcessor
from fetchers import get_all_fetchers
from colorama import init, Fore, Style
import logging
from tqdm import tqdm

# Disable excessive logging from external libraries
logging.getLogger("dukascopy_python").setLevel(logging.WARNING)
logging.getLogger("DUKASCRIPT").setLevel(logging.WARNING)

init(autoreset=True)

logger = logging.getLogger("DataManager")

class DataManager:
    """
    Central controller of the application.
    """
    
    def __init__(self):
        self.storage = StorageManager()
        self.processor = DataProcessor()
        
        # Dynamic discovery of supported data sources
        self._fetchers = {}
        for fetcher_class in get_all_fetchers():
            try:
                instance = fetcher_class()
                self._fetchers[instance.source_name.upper()] = instance
            except Exception as e:
                logger.warning(f"Failed to initialize fetcher {fetcher_class.__name__}: {e}")
        
    def _get_fetcher(self, source_name: str):
        source = source_name.upper()
        if source not in self._fetchers:
             raise ValueError(f"Data source not supported: {source_name}. Available: {list(self._fetchers.keys())}")
        return self._fetchers[source]

    def download_data(self, source: str, asset: str, start_date: datetime, end_date: datetime):
        """Downloads and saves data in M1 using yearly chunks to save memory."""
        info = self.storage.get_database_info(source, asset, "M1")
        if info.get("status") != "Not Found":
            logger.warning(f"The database {asset} (M1) from {source} already exists in the database.")
            logger.info("↳ Use the 'update' command to add recent data.")
            raise Exception(f"Database {asset} (M1) already exists in {source}")

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
        
        with tqdm(total=len(chunks), desc=f"Downloading {asset}", unit="year") as pbar:
            for c_start, c_end in chunks:
                try:
                    df_chunk = fetcher.fetch_data(c_start, c_end)
                    
                    if df_chunk is not None and not df_chunk.empty:
                        self.storage.append_data(df_chunk, source, asset, timeframe="M1")
                        total_rows += len(df_chunk)
                    
                except Exception as e:
                    logger.error(f"    [ERROR] Failed to fetch/save chunk {c_start.date()}: {e}")
                
                pbar.update(1)

        if total_rows > 0:
            logger.info(f"Database {asset} (M1) download complete! Total: {total_rows:,} rows.")
        else:
            logger.error(f"No data was downloaded for {asset} (M1).")

    def update_data(self, source: str, asset: str, timeframe: str = "M1"):
        """Discovers the last date in the existing database and downloads up to today (append)."""
        info = self.storage.get_database_info(source, asset, timeframe)
        if info.get("status") == "Not Found":
            logger.error(f"Database {asset} ({timeframe}) does not exist.")
            logger.info("Do you want to download from scratch? Use the Download function.")
            return

        last_date_str = info["end_date"]
        # Naive datetime
        last_date = datetime.strptime(last_date_str, "%Y-%m-%d %H:%M:%S")
        now = datetime.now()
        
        if last_date.date() >= now.date() and (now - last_date).total_seconds() < 3600:
             logger.info(f"{asset} is already updated.")
             return
             
        logger.info(f"Updating {asset} from {last_date}...")
        fetcher = self._get_fetcher(source)
        
        # Important: Since `timeframe` here can be H1 for example, we always update the M1 database, 
        # and if asked to update H1, we convert afterwards.
        # By default: we always download M1 from the Fetcher.
        new_df = fetcher.fetch_data(asset, last_date, now)
        
        # If it is a different timeframe than M1, we convert
        if timeframe.upper() != "M1":
             new_df = self.processor.resample_ohlc(new_df, timeframe)
             
        self.storage.append_data(new_df, source, asset, timeframe)
        logger.info(f"Database {asset} ({timeframe}) updated successfully!")

    def update_all_databases(self):
        """Updates all M1 databases and dynamically resamples to higher timeframes."""
        dbs = self.list_all()
        if not dbs:
            logger.info("No databases found to update.")
            return

        logger.info("=== GLOBAL DATABASE UPDATE ===")

        m1_dbs = [db for db in dbs if db['timeframe'] == 'M1']
        other_dbs = [db for db in dbs if db['timeframe'] != 'M1']

        logger.info(f"Detected {len(m1_dbs)} original database(s) (M1) and {len(other_dbs)} higher timeframe database(s).")

        # First, updates all M1s
        if m1_dbs:
            for db in tqdm(m1_dbs, desc="Updating M1 databases"):
                try:
                    self.update_data(db['source'], db['asset'], "M1")
                except Exception as e:
                    logger.error(f"Error updating M1 database ({db['source']}/{db['asset']}): {e}")

        # Then rebuilds higher timeframes based on the newly updated M1.
        if other_dbs:
            for db in tqdm(other_dbs, desc="Rebuilding higher timeframes"):
                try:
                    self.resample_database(db['source'], db['asset'], db['timeframe'])
                except Exception as e:
                    logger.error(f"Error converting database {db['timeframe']} ({db['source']}/{db['asset']}): {e}")

        logger.info("Global task finished successfully!")

    def delete_database(self, source: str, asset: str, timeframe: str = None):
        """Deletes database (or all timeframes of the asset)"""
        success = self.storage.delete_database(source, asset, timeframe)
        target = f"{source}/{asset}/{timeframe}" if timeframe else f"{source}/{asset} (all timeframes)"
        if success:
             logger.info(f"Database deleted: {target}")
        else:
             logger.warning(f"Database not found: {target}")

    def delete_all_databases(self):
        """Deletes all databases from all sources"""
        success = self.storage.delete_all()
        if success:
             logger.info("All databases were successfully deleted.")
        else:
             logger.error("Error deleting databases.")

    def info(self, source: str, asset: str, timeframe: str) -> dict:
        return self.storage.get_database_info(source, asset, timeframe)

    def list_all(self):
        """Returns the complete list of databases with their info."""
        dbs = self.storage.list_databases()
        if not dbs:
             return []
             
        detailed_dbs = []
        for db in dbs:
            info = self.storage.get_database_info(db['source'], db['asset'], db['timeframe'])
            detailed_dbs.append(info)
            
        return detailed_dbs
        
        
    def show_search_summary(self):
        """Displays the total amount of assets from each source without listing."""
        logger.info("Summary of available assets for search:")
        
        for source_name, fetcher in self._fetchers.items():
            try:
                df = fetcher.search(query="")
                logger.info(f"  ● {source_name.capitalize()}: {len(df)} assets found")
            except Exception:
                # If search is not implemented or fails, show a generic message
                logger.info(f"  ● {source_name.capitalize()}: Supports searching (Details via search command)")

    def search_assets(self, source: str = "openbb", query: str = None, exchange: str = None):
        """Search assets via the specified fetcher."""
        source_key = source.upper()
        if source_key not in self._fetchers:
             logger.warning(f"Source {source} not supported for search. Available: {list(self._fetchers.keys())}")
             return

        fetcher = self._fetchers[source_key]
        logger.info(f"Searching assets in {source_key}...")
        
        try:
            df = fetcher.search(query=query, exchange=exchange)
            
            if df.empty:
                logger.info(f"No asset found for these parameters in {source_key}.")
                return
                
            print(f"Found {len(df)} results. Displaying the first 20:")
            
            # Format output based on source (we could decentralize formatting too, but keeping it simple for now)
            if source_key == "OPENBB":
                print(f"{'=' * 95}")
                header = f"{'TICKER':<15} | {'COMPANY NAME':<55} | {'EXCHANGE':<15}"
                print(header)
                print(f"{'-' * 95}")
                df = df.reset_index().fillna("")
                for _, row in df.head(20).iterrows():
                    symbol = str(row.get('symbol', ''))
                    name = str(row.get('name', ''))[:53]
                    exc = str(row.get('exchange', ''))
                    print(f"{symbol:<15} | {name:<55} | {exc:<15}")
                print(f"{'=' * 95}")
            elif source_key == "DUKASCOPY":
                print(f"{'=' * 105}")
                header = f"{'TICKER':<20} | {'ALIAS':<15} | {'ASSET NAME':<50} | {'CATEGORY':<10}"
                print(header)
                print(f"{'-' * 105}")
                df = df.fillna("")
                for _, row in df.head(20).iterrows():
                    print(f"{str(row['ticker']):<20} | {str(row['alias']):<15} | {str(row['nome_do_ativo'])[:48]:<50} | {str(row['categoria']):<10}")
                print(f"{'=' * 105}")
            else:
                # Generic output for new fetchers
                print(df.head(20).to_string())

        except Exception as e:
            logger.error(f"Error searching assets in {source_key}: {e}")

    def resample_database(self, source: str, asset: str, target_timeframe: str):
        """Reads M1 from an existing db, converts and saves to the target timeframe."""
        try:
            df_m1 = self.storage.load_data(source, asset, timeframe="M1")
        except FileNotFoundError:
            logger.error(f"There is no saved M1 base for {asset} in source {source}. Download it first.")
            return

        logger.info(f"Converting {asset} M1 for {target_timeframe}...")
        
        # We can't easily tqdm the resample_ohlc logic itself if it's one pandas call,
        # but we can show a spinner or a determinate bar if we knew it was slow.
        # Since resample is usually fast for one asset, a simple log is often enough,
        # but for consistency we use tqdm with a single step or just a message.
        with tqdm(total=1, desc=f"Resampling {asset} to {target_timeframe}", leave=False) as pbar:
            df_resampled = self.processor.resample_ohlc(df_m1, target_timeframe)
            self.storage.save_data(df_resampled, source, asset, target_timeframe)
            pbar.update(1)
            
        logger.info(f"Conversion of {asset} to {target_timeframe} finished and saved!")

    def check_quality(self, source: str, asset: str, timeframe: str = "M1"):
        """Performs integrity and quality validations on the specified database."""
        try:
            df = self.storage.load_data(source, asset, timeframe)
        except FileNotFoundError:
            logger.error(f"Database {asset} ({timeframe}) in source {source} not found.")
            return

        logger.info(f"=== QUALITY REPORT: {asset.upper()} ({timeframe}) - {source.upper()} ===")
        logger.info(f"Total Registers Analyzed: {len(df):,}")

        # 1. OHLC Relations Test
        try:
            relations_mask = (df['High'] >= df['Low']) & \
                             (df['High'] >= df['Open']) & \
                             (df['High'] >= df['Close']) & \
                             (df['Low'] <= df['Open']) & \
                             (df['Low'] <= df['Close'])
            failures_ohlc = (~relations_mask).sum()
            logger.info(f"1. OHLC Mathematical Relations : {failures_ohlc} error(s)")
        except KeyError:
            logger.warning("1. OHLC Mathematical Relations : Ignored (Price columns missing)")

        # 2. Time Index Duplicates Test
        failures_dup = df.index.duplicated().sum()
        logger.info(f"2. Duplicated Registers      : {failures_dup} error(s)")
        
        # 3. Time Ordering Test (Monotonicity)
        time_diffs = df.index.to_series().diff()
        failures_ord = (time_diffs < pd.Timedelta(seconds=0)).sum()
        logger.info(f"3. Time Ordering             : {failures_ord} error(s)")
            
        # 4. Gaps Analysis
        if len(df) > 1:
            time_diffs = df.index.to_series().diff().dropna()
            expected_freq = time_diffs.median()
            
            gaps_mask = time_diffs > (expected_freq * 5)
            failures_gaps = gaps_mask.sum()
            logger.info(f"4. Absence of Data (Gaps)    : {failures_gaps} gap(s)")
        else:
            logger.info("4. Absence of Data (Gaps)    : Ignored (Few data for analysis)")

        return
