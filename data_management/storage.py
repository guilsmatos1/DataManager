import os
import glob
import pandas as pd
from pathlib import Path
import json

class StorageManager:
    """Manages the hierarchical storage of data in the schema:
       database/{source}/{asset}/{timeframe}/
    """
    
    def __init__(self, base_dir="database"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.format = ".parquet"
        self.catalog_path = self.base_dir.parent / "metadata" / "catalog.json"
        
        # Ensure metadata dir exists
        self.catalog_path.parent.mkdir(parents=True, exist_ok=True)

    def _get_path(self, source: str, asset: str, timeframe: str) -> Path:
        """Returns the file path for the specific data."""
        asset_dir = self.base_dir / source.lower() / asset.upper() / timeframe.upper()
        asset_dir.mkdir(parents=True, exist_ok=True)
        return asset_dir / f"data{self.format}"

    def _load_catalog(self) -> list:
        """Loads the metadata catalog from disk."""
        if not self.catalog_path.exists():
            return []
        try:
            with open(self.catalog_path, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return []

    def _save_catalog(self, catalog: list):
        """Saves the metadata catalog to disk."""
        with open(self.catalog_path, "w") as f:
            json.dump(catalog, f)

    def _update_catalog_entry(self, source: str, asset: str, timeframe: str):
        """Updates or adds an entry to the catalog."""
        catalog = self._load_catalog()
        info = self.get_database_info(source, asset, timeframe)
        
        # Remove existing if any
        catalog = [c for c in catalog if not (c["source"].lower() == source.lower() and c["asset"].lower() == asset.lower() and c["timeframe"].lower() == timeframe.lower())]
        
        if info.get("status") != "Not Found":
            catalog.append(info)
        
        self._save_catalog(catalog)

    def rebuild_catalog(self):
        """Rebuilds the entire catalog by scanning the disk."""
        catalog = []
        # Loops logic previously in list_databases
        for source_path in self.base_dir.iterdir():
            if not source_path.is_dir(): continue
            for asset_path in source_path.iterdir():
                if not asset_path.is_dir(): continue
                for time_path in asset_path.iterdir():
                    if not time_path.is_dir(): continue
                    if (time_path / f"data{self.format}").exists():
                        info = self.get_database_info(source_path.name, asset_path.name, time_path.name)
                        if info.get("status") != "Not Found":
                            catalog.append(info)
        self._save_catalog(catalog)
        return {"status": "success", "count": len(catalog)}

    def save_data(self, df: pd.DataFrame, source: str, asset: str, timeframe: str):
        """Saves data using an atomic swap to prevent corruption (Write-ahead-style)."""
        file_path = self._get_path(source, asset, timeframe)
        temp_path = file_path.with_suffix(f".tmp{self.format}")

        # Ensures the index is DateTime and is sorted
        if not isinstance(df.index, pd.DatetimeIndex):
            if 'date' in df.columns or 'time' in df.columns or 'datetime' in df.columns:
                col = next(c for c in ['datetime', 'date', 'time'] if c in df.columns)
                df[col] = pd.to_datetime(df[col])
                df.set_index(col, inplace=True)
        
        df.sort_index(inplace=True)
        # Removing timezone if any to avoid Parquet conflict
        if df.index.tz is not None:
             df.index = df.index.tz_convert(None)
             
        try:
            # 1. Write to temporary file
            if self.format == ".parquet":
                df.to_parquet(temp_path, engine='fastparquet')
            else:
                df.to_csv(temp_path)
            
            # 2. Atomic rename (replace existing if successful)
            temp_path.replace(file_path)
            
            # 3. Update metadata
            self._update_catalog_entry(source, asset, timeframe)
            
        except Exception as e:
            # If something fails, try to remove the partial temp file
            if temp_path.exists():
                temp_path.unlink()
            raise e
            
    def append_data(self, df: pd.DataFrame, source: str, asset: str, timeframe: str):
        """Updates/Concatenates new data to existing data."""
        file_path = self._get_path(source, asset, timeframe)
        if not file_path.exists():
            return self.save_data(df, source, asset, timeframe)
            
        # Load existing and join
        existing_df = self.load_data(source, asset, timeframe)
        combined_df = pd.concat([existing_df, df])
        
        # Handle duplications keeping the latest or first arrived data
        combined_df = combined_df[~combined_df.index.duplicated(keep='last')]
        self.save_data(combined_df, source, asset, timeframe)
        
    def load_data(self, source: str, asset: str, timeframe: str) -> pd.DataFrame:
        """Loads data from a file."""
        file_path = self._get_path(source, asset, timeframe)
        if not file_path.exists():
            raise FileNotFoundError(f"Database not found: {source} -> {asset} ({timeframe})")
            
        if self.format == ".parquet":
            return pd.read_parquet(file_path, engine='fastparquet')
        else:
            df = pd.read_csv(file_path, index_col=0, parse_dates=True)
            return df

    def delete_database(self, source: str, asset: str, timeframe: str = None) -> bool:
        """Deletes the specific database or all timeframes if not provided."""
        import shutil
        if timeframe:
            file_path = self._get_path(source, asset, timeframe)
            if file_path.exists():
                file_path.unlink()
                # Optional: remove the folder if empty
                try:
                    os.rmdir(file_path.parent)
                except OSError:
                    pass 
                self._update_catalog_entry(source, asset, timeframe)
                return True
        else:
            asset_dir = self.base_dir / source.lower() / asset.upper()
            if asset_dir.exists():
                shutil.rmtree(asset_dir)
                catalog = self._load_catalog()
                catalog = [c for c in catalog if not (c["source"].lower() == source.lower() and c["asset"].lower() == asset.lower())]
                self._save_catalog(catalog)
                return True
        return False

    def delete_all(self) -> bool:
        """Deletes all databases."""
        import shutil
        try:
            for item in self.base_dir.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
            self._save_catalog([])
            return True
        except OSError:
            return False

    def get_database_info(self, source: str, asset: str, timeframe: str) -> dict:
        """Returns descriptive info of the database."""
        file_path = self._get_path(source, asset, timeframe)
        if not file_path.exists():
            return {"status": "Not Found"}
            
        df = self.load_data(source, asset, timeframe)
        return {
            "source": source,
            "asset": asset,
            "timeframe": timeframe,
            "rows": len(df),
            "start_date": str(df.index.min()),
            "end_date": str(df.index.max()),
            "file_size_kb": round(file_path.stat().st_size / 1024, 2)
        }
        
    def _cleanup_empty_dirs(self, directory: Path):
        """Recursively removes empty directories from a point."""
        if not directory.is_dir():
            return

        # First, recursively visits children
        for entry in directory.iterdir():
            if entry.is_dir():
                self._cleanup_empty_dirs(entry)

        # If after cleaning children this directory is empty, remove it
        # Except if it is the main base_dir
        if directory != self.base_dir and not any(directory.iterdir()):
            try:
                directory.rmdir()
            except OSError:
                pass

    def list_databases(self) -> list:
        """Returns a list of all downloaded and saved databases (Fast catalog read)."""
        self._cleanup_empty_dirs(self.base_dir)
        return self._load_catalog()
