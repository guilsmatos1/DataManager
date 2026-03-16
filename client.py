import requests
import pandas as pd
from typing import Optional, List, Dict, Any, Union
from io import BytesIO

class DataManagerClient:
    """
    Python client to connect to DataManager Network API protected with API Key.
    """
    def __init__(self, base_url: str = "http://127.0.0.1:8686", api_key: str = "YOUR_API_KEY_HERE"):
        self.base_url = base_url.rstrip("/")
        # Uses a Session to automatically load the custom header
        self.session = requests.Session()
        self.session.headers.update({"X-API-Key": api_key})

    def _handle_response(self, response: requests.Response) -> Dict[str, Any]:
        """Extracts JSON from response, raising exception on HTTP failure"""
        try:
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            try:
                error_detail = response.json().get('detail', str(e))
                raise RuntimeError(f"API Error: {error_detail}")
            except Exception:
                raise RuntimeError(f"API Error: {response.text or str(e)}")
            
    def download(self, source: str, asset: str, start_date: str = None, end_date: str = None) -> dict:
        """Sends a command to download/save assets on the server."""
        payload = {"source": source, "asset": asset}
        if start_date: payload["start_date"] = start_date
        if end_date: payload["end_date"] = end_date
        res = self.session.post(f"{self.base_url}/download", json=payload)
        return self._handle_response(res)

    def update(self, source: str, asset: str, timeframe: str = "M1") -> dict:
        """Sends a command to update the asset databases."""
        payload = {"source": source, "asset": asset, "timeframe": timeframe}
        res = self.session.post(f"{self.base_url}/update", json=payload)
        return self._handle_response(res)

    def delete(self, source: str, asset: str, timeframe: str = None) -> dict:
        """Physically deletes a database or entire asset from the server."""
        payload = {"source": source, "asset": asset}
        if timeframe: payload["timeframe"] = timeframe
        res = self.session.post(f"{self.base_url}/delete", json=payload)
        return self._handle_response(res)

    def resample(self, source: str, asset: str, target_timeframe: str) -> dict:
        """Regenerates or creates a timeframe from the original M1 database."""
        payload = {"source": source, "asset": asset, "target_timeframe": target_timeframe}
        res = self.session.post(f"{self.base_url}/resample", json=payload)
        return self._handle_response(res)

    def list_databases(self) -> List[dict]:
        """Returns a list of dictionaries detailing all databases."""
        res = self.session.get(f"{self.base_url}/list")
        data = self._handle_response(res)
        return data.get("databases", [])

    def info(self, source: str, asset: str, timeframe: str) -> dict:
        """Returns metadata of the specified database on the server."""
        res = self.session.get(f"{self.base_url}/info/{source}/{asset}/{timeframe}")
        return self._handle_response(res)

    def search(self, source: str = "openbb", query: str = None, exchange: str = None) -> pd.DataFrame:
        """String-based search in the chosen source, returning a pandas DataFrame."""
        params = {"source": source}
        if query: params["query"] = query
        if exchange: params["exchange"] = exchange
        
        res = self.session.get(f"{self.base_url}/search", params=params)
        data = self._handle_response(res)
        assets = data.get("assets", [])
        return pd.DataFrame(assets)

    def _apply_timezone(self, df: pd.DataFrame, timezone: str) -> pd.DataFrame:
        """
        Converts the DataFrame's DatetimeIndex from naive (UTC) to the target timezone.
        The stored data is always in UTC but without timezone info (naive).
        This method localizes to UTC first, then converts to the desired tz.
        
        Args:
            df: DataFrame with naive DatetimeIndex (assumed UTC).
            timezone: IANA timezone string (e.g. 'America/Sao_Paulo', 'US/Eastern', 'Europe/London').
        
        Returns:
            DataFrame with timezone-aware DatetimeIndex converted to the target timezone.
        """
        import pytz
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        df.index = df.index.tz_convert(timezone)
        return df

    def get_data(self, source: str, asset: str, timeframe: str, save_path: str = None, save_format: str = "parquet", timezone: str = None) -> Union[pd.DataFrame, str]:
        """
        Downloads the `.parquet` file from the server.
        If save_path is provided, saves to disk and returns the path.
        You can define 'save_format' as 'parquet' or 'csv'.
        Otherwise, loads directly into the client's local memory as a DataFrame.
        
        Args:
            timezone: Optional IANA timezone string to convert the index.
                      Examples: 'America/Sao_Paulo', 'US/Eastern', 'Europe/London', 'Asia/Tokyo'.
                      If None, the data is returned as-is (naive UTC).
        """
        res = self.session.get(f"{self.base_url}/data/{source}/{asset}/{timeframe}")
        res.raise_for_status()
        
        if save_path:
            save_format = save_format.lower()
            if save_format == "csv":
                file_obj = BytesIO(res.content)
                df = pd.read_parquet(file_obj, engine='fastparquet')
                if timezone:
                    df = self._apply_timezone(df, timezone)
                df.to_csv(save_path)
            elif save_format == "parquet":
                if timezone:
                    file_obj = BytesIO(res.content)
                    df = pd.read_parquet(file_obj, engine='fastparquet')
                    df = self._apply_timezone(df, timezone)
                    df.to_parquet(save_path, engine='fastparquet')
                else:
                    with open(save_path, 'wb') as f:
                        f.write(res.content)
            else:
                raise ValueError("Format not supported. Choose 'parquet' or 'csv'.")
            return save_path
        else:
            # Loads the binary into memory for pandas to natively read the parquet
            file_obj = BytesIO(res.content)
            df = pd.read_parquet(file_obj, engine='fastparquet')
            if timezone:
                df = self._apply_timezone(df, timezone)
            return df

if __name__ == "__main__":
    # Simple Example Script
    print("Testing DataManager Client...")
    
    # Initializes the client passing default host and key (optional if matches __init__ default)
    client = DataManagerClient("http://127.0.0.1:8686", api_key="YOUR_API_KEY_HERE")
    
    try:
        from datetime import datetime, timedelta
        import time

        target_source = "DUKASCOPY"
        target_asset = "USATECH"
        target_tf = "H1"

        print(f"\n1. Listing databases on the server...")
        dbs = client.list_databases()
        exists = any(db['source'].upper() == target_source and db['asset'] == target_asset and db['timeframe'] == target_tf for db in dbs)

        if exists:
            print(f" -> The database {target_asset} ({target_tf}) already exists on the server.")
        else:
            print(f" -> The database {target_asset} ({target_tf}) was NOT found. Requesting download...")
            start = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
            end = datetime.now().strftime("%Y-%m-%d")
            res = client.download(target_source, target_asset, start_date=start, end_date=end)
            print(f" -> Server response: {res}")
            print(" -> Waiting a few seconds for initial processing (async)...")
            time.sleep(5)

        print(f"\n2. Downloading data of {target_asset} ({target_tf}) to local CSV...")
        csv_path = client.get_data(
            source=target_source,
            asset=target_asset,
            timeframe=target_tf,
            save_path="usatech_resultado.csv",
            save_format="csv"
        )
        print(f" -> Success! File saved at: {csv_path}")

        print("\nExample finished successfully!")
    except Exception as e:
        print(f"Error in client flow: {e}")
