from datetime import datetime
from pathlib import Path
import pandas as pd
from data_management.storage import StorageManager
from data_management.processor import DataProcessor
from fetchers.dukascopy_fetcher import DukascopyFetcher
from fetchers.openbb_fetcher import OpenBBFetcher
from colorama import init, Fore, Style
import logging

# Desativar logs excessivos de bibliotecas externas
logging.getLogger("dukascopy_python").setLevel(logging.WARNING)
logging.getLogger("DUKASCRIPT").setLevel(logging.WARNING)

init(autoreset=True)

class DataManager:
    """
    Central controller of the application.
    """
    
    def __init__(self):
        self.storage = StorageManager()
        self.processor = DataProcessor()
        
        # Dynamic mapping of supported data sources
        self._fetchers = {
            "DUKASCOPY": DukascopyFetcher(),
            "OPENBB": OpenBBFetcher()
        }
        
    def _get_fetcher(self, source_name: str):
        source = source_name.upper()
        if source not in self._fetchers:
             raise ValueError(f"Data source not supported: {source_name}. Available: {list(self._fetchers.keys())}")
        return self._fetchers[source]

    def download_data(self, source: str, asset: str, start_date: datetime, end_date: datetime):
        """Downloads and saves data in M1."""
        info = self.storage.get_database_info(source, asset, "M1")
        if info.get("status") != "Not Found":
            print(f"{Fore.YELLOW}⚠ Warning: {Fore.WHITE}The database {Fore.YELLOW}{asset}{Fore.WHITE} (M1) from {source} already exists in the database.")
            print(f"  {Fore.CYAN}↳ Use the 'update' command to add recent data.{Style.RESET_ALL}")
            raise Exception(f"Database {asset} (M1) already exists in {source}")

        print(f"{Fore.CYAN}⇅ {Fore.WHITE}Starting download of {Fore.YELLOW}{asset}{Fore.WHITE} via {Fore.YELLOW}{source.upper()}{Fore.WHITE}...")
        fetcher = self._get_fetcher(source)
        df_m1 = fetcher.fetch_data(asset, start_date, end_date)
        
        # The Fetcher always returns M1 naive-datetime indexed and sorted
        self.storage.save_data(df_m1, source, asset, timeframe="M1")
        print(f"{Fore.GREEN}✓ {Fore.WHITE}Database {Fore.CYAN}{asset} (M1){Fore.WHITE} saved successfully! ({len(df_m1):,} rows)")

    def update_data(self, source: str, asset: str, timeframe: str = "M1"):
        """Discovers the last date in the existing database and downloads up to today (append)."""
        info = self.storage.get_database_info(source, asset, timeframe)
        if info.get("status") == "Not Found":
            print(f"ERROR: Database {asset} ({timeframe}) does not exist.")
            print("Do you want to download from scratch? Use the Download function.")
            return

        last_date_str = info["end_date"]
        # Naive datetime
        last_date = datetime.strptime(last_date_str, "%Y-%m-%d %H:%M:%S")
        now = datetime.now()
        
        if last_date.date() >= now.date() and (now - last_date).total_seconds() < 3600:
             print(f"{Fore.YELLOW}ℹ {Fore.WHITE}{asset} is already updated.")
             return
             
        print(f"{Fore.CYAN}⟳ {Fore.WHITE}Updating {Fore.YELLOW}{asset}{Fore.WHITE} from {last_date}...")
        fetcher = self._get_fetcher(source)
        
        # Important: Since `timeframe` here can be H1 for example, we always update the M1 database, 
        # and if asked to update H1, we convert afterwards.
        # By default: we always download M1 from the Fetcher.
        new_df = fetcher.fetch_data(asset, last_date, now)
        
        # If it is a different timeframe than M1, we convert
        if timeframe.upper() != "M1":
             new_df = self.processor.resample_ohlc(new_df, timeframe)
             
        self.storage.append_data(new_df, source, asset, timeframe)
        print(f"{Fore.GREEN}✓ {Fore.WHITE}Database {Fore.CYAN}{asset} ({timeframe}){Fore.WHITE} updated successfully!\n")

    def update_all_databases(self):
        """Updates all M1 databases and dynamically resamples to higher timeframes."""
        dbs = self.list_all()
        if not dbs:
            print(f"[{datetime.now()}] No databases found to update.")
            return

        print(f"\n{Fore.CYAN}{Style.BRIGHT}=== GLOBAL DATABASE UPDATE ===")

        m1_dbs = [db for db in dbs if db['timeframe'] == 'M1']
        other_dbs = [db for db in dbs if db['timeframe'] != 'M1']

        print(f"[{datetime.now()}] Detected {len(m1_dbs)} original database(s) (M1) and {len(other_dbs)} higher timeframe database(s).")

        # First, updates all M1s
        for db in m1_dbs:
            try:
                self.update_data(db['source'], db['asset'], "M1")
            except Exception as e:
                print(f"[{datetime.now()}] Error updating M1 database ({db['source']}/{db['asset']}): {e}")

        # Then rebuilds higher timeframes based on the newly updated M1.
        for db in other_dbs:
            try:
                print(f"\n{Fore.CYAN}⚙ {Fore.WHITE}Synchronizing and Rebuilding timeframe {Fore.YELLOW}{db['timeframe']}{Fore.WHITE} for {Fore.YELLOW}{db['source']}/{db['asset']}{Fore.WHITE}...")
                self.resample_database(db['source'], db['asset'], db['timeframe'])
            except Exception as e:
                print(f"{Fore.RED}✗ Error converting database {db['timeframe']} ({db['source']}/{db['asset']}): {e}")

        print(f"\n{Fore.GREEN}{Style.BRIGHT}✓ Global task finished successfully!{Style.RESET_ALL}\n")

    def delete_database(self, source: str, asset: str, timeframe: str = None):
        """Deletes database (or all timeframes of the asset)"""
        success = self.storage.delete_database(source, asset, timeframe)
        target = f"{source}/{asset}/{timeframe}" if timeframe else f"{source}/{asset} (all timeframes)"
        if success:
             print(f"Database deleted: {target}")
        else:
             print(f"Database not found: {target}")

    def delete_all_databases(self):
        """Deletes all databases from all sources"""
        success = self.storage.delete_all()
        if success:
             print("All databases were successfully deleted.")
        else:
             print("Error deleting databases.")

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
        print(f"\n{Fore.CYAN}🔍 {Fore.WHITE}Resumo de ativos disponíveis for busca:")
        
        # Dukascopy
        duka_count = 0
        csv_path = Path("metadata") / "dukas_assets.csv"
        if csv_path.exists():
            try:
                df = pd.read_csv(csv_path)
                duka_count = len(df)
            except:
                pass
        print(f"  ● Dukascopy: {duka_count} ativos (Database Local)")

        # OpenBB
        print(f"  ● OpenBB: Fetching total from API...", end="\r")
        try:
            from openbb import obb
            # Busca vazia for obter o count total retornado pelo provedor default
            res = obb.equity.search(query="")
            df_obb = res.to_df()
            obb_count = len(df_obb)
            print(f"  ● OpenBB: {obb_count} assets found (via API)    ")
        except Exception:
            print(f"  ● OpenBB: Thousands of available assets (Error counting)   ")
        print()

    def search_assets(self, source: str = "openbb", query: str = None, exchange: str = None):
        """Search OpenBB or Dukascopy for available assets."""
        source = source.lower()
        if source == "openbb":
            print(f"\n{Fore.CYAN}🔍 {Fore.WHITE}Searching assets in OpenBB...")
            try:
                from openbb import obb
                kwargs = {}
                if query:
                    kwargs['query'] = query
                if exchange:
                    kwargs['exchange'] = exchange
                    
                res = obb.equity.search(**kwargs)
                df = res.to_df()
                
                if df.empty:
                    print("Nenhum ativo encontrado for estes parâmetros no OpenBB.")
                    return
                    
                print(f"Found {len(df)} results. Displaying the first 20:")
                print(f"{'=' * 95}")
                header = f"{'TICKER':<15} | {'COMPANY NAME':<55} | {'EXCHANGE':<15}"
                print(header)
                print(f"{'-' * 95}")
                
                # Resets the index in case symbol is in OpenBB index
                df = df.reset_index()
                df = df.fillna("")
                for _, row in df.head(20).iterrows():
                    symbol = str(row.get('symbol', ''))
                    name = str(row.get('name', ''))[:53]
                    exc = str(row.get('exchange', ''))
                    print(f"{symbol:<15} | {name:<55} | {exc:<15}")
                print(f"{'=' * 95}")
            except Exception as e:
                print(f"Error searching assets in OpenBB: {e}")
                
        elif source == "dukascopy":
            print(f"\n{Fore.CYAN}🔍 {Fore.WHITE}Searching assets offline (Dukascopy)...")
            try:
                # The path is relative to the data subfolder where the CSV script is saved
                csv_path = Path("metadata") / "dukas_assets.csv"
                if not csv_path.exists():
                    print("File 'dukas_assets.csv' not found. Execute the merge script first.")
                    return
                
                df = pd.read_csv(csv_path)
                # Forcing strings and removing NaNs
                df = df.fillna("")
                
                if query:
                    # Case-insensitive search in ticker, alias or asset name
                    mask = (
                        df['ticker'].str.contains(query, case=False) |
                        df['alias'].str.contains(query, case=False) |
                        df['nome_do_ativo'].str.contains(query, case=False)
                    )
                    df = df[mask]
                
                if df.empty:
                    print(f"No assets containing '{query}' were found.")
                    return
                    
                print(f"Found {len(df)} results. Displaying the first 20:")
                print(f"{'=' * 105}")
                header = f"{'TICKER':<20} | {'ALIAS':<15} | {'ASSET NAME':<50} | {'CATEGORY':<10}"
                print(header)
                print(f"{'-' * 105}")
                for _, row in df.head(20).iterrows():
                    print(f"{str(row['ticker']):<20} | {str(row['alias']):<15} | {str(row['nome_do_ativo'])[:48]:<50} | {str(row['categoria']):<10}")
                print(f"{'=' * 105}")

            except Exception as e:
                print(f"Error searching assets in Dukascopy: {e}")
        else:
            print(f"Source {source} not supported for search. Try openbb or dukascopy.")

    def resample_database(self, source: str, asset: str, target_timeframe: str):
        """Reads M1 from an existing db, converts and saves to the target timeframe."""
        try:
            df_m1 = self.storage.load_data(source, asset, timeframe="M1")
        except FileNotFoundError:
            print(f"Erro: Não há base M1 salva for {asset} in source {source}. Download it first.")
            return

        print(f"{Fore.CYAN}⚙ {Fore.WHITE}Converting {Fore.YELLOW}{asset}{Fore.WHITE} M1 for {Fore.YELLOW}{target_timeframe}{Fore.WHITE}...")
        df_resampled = self.processor.resample_ohlc(df_m1, target_timeframe)
        self.storage.save_data(df_resampled, source, asset, target_timeframe)
        print(f"{Fore.GREEN}✓ {Fore.WHITE}Conversion finished and saved!")

    def check_quality(self, source: str, asset: str, timeframe: str = "M1"):
        """Performs integrity and quality validations on the specified database."""
        try:
            df = self.storage.load_data(source, asset, timeframe)
        except FileNotFoundError:
            print(f"{Fore.RED}Erro: Database {asset} ({timeframe}) in source {source} não encontrada.")
            return

        print(f"\n{Fore.CYAN}{Style.BRIGHT}=== QUALITY REPORT: {asset.upper()} ({timeframe}) - {source.upper()} ===")
        print(f"{Fore.WHITE}Total Registers Analyzed: {Fore.YELLOW}{len(df):,}")
        print(f"{Fore.CYAN}{'-' * 60}")

        # 1. OHLC Relations Test
        try:
            relations_mask = (df['High'] >= df['Low']) & \
                             (df['High'] >= df['Open']) & \
                             (df['High'] >= df['Close']) & \
                             (df['Low'] <= df['Open']) & \
                             (df['Low'] <= df['Close'])
            failures_ohlc = (~relations_mask).sum()
            c_ohlc = Fore.RED if failures_ohlc > 0 else Fore.GREEN
            print(f"{Fore.WHITE}1. OHLC Mathematical Relations : {c_ohlc}{failures_ohlc} error(s)")
        except KeyError:
            print(f"{Fore.WHITE}1. OHLC Mathematical Relations : {Fore.YELLOW}Ignored (Price columns missing)")

        # 2. Time Index Duplicates Test
        failures_dup = df.index.duplicated().sum()
        c_dup = Fore.RED if failures_dup > 0 else Fore.GREEN
        print(f"{Fore.WHITE}2. Duplicated Registers      : {c_dup}{failures_dup} error(s)")
        
        # 3. Time Ordering Test (Monotonicity)
        time_diffs = df.index.to_series().diff()
        failures_ord = (time_diffs < pd.Timedelta(seconds=0)).sum()
        c_ord = Fore.RED if failures_ord > 0 else Fore.GREEN
        print(f"{Fore.WHITE}3. Time Ordering             : {c_ord}{failures_ord} error(s)")
            
        # 4. Gaps Analysis
        if len(df) > 1:
            time_diffs = df.index.to_series().diff().dropna()
            expected_freq = time_diffs.median()
            
            gaps_mask = time_diffs > (expected_freq * 5)
            failures_gaps = gaps_mask.sum()
            c_gap = Fore.YELLOW if failures_gaps > 0 else Fore.GREEN
            print(f"{Fore.WHITE}4. Absence of Data (Gaps)    : {c_gap}{failures_gaps} gap(s)")
        else:
            print(f"{Fore.WHITE}4. Absence of Data (Gaps)    : {Fore.YELLOW}Ignorado (Poucos dados for análise)")

        print(f"{Fore.CYAN}{'-' * 60}{Style.RESET_ALL}\n")
        return
