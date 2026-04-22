from __future__ import annotations

from io import BytesIO
from typing import Any

import pandas as pd
import requests  # type: ignore[import-untyped]


class DataManagerClient:
    """
    Python client to connect to DataManager Network API protected with API Key.
    Data is served as Parquet over HTTP from TimescaleDB.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8686",
        api_key: str = "YOUR_API_KEY_HERE",
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        # Uses a Session to automatically load the custom header
        self.session = requests.Session()
        self.session.headers.update({"X-API-Key": api_key})
        self.session.timeout = timeout

    def _handle_response(self, response: requests.Response) -> dict[str, Any]:
        """Extracts JSON from response, raising exception on HTTP failure"""
        try:
            response.raise_for_status()
            json_data: dict[str, Any] = response.json()
            return json_data
        except requests.exceptions.HTTPError as e:
            error_detail = None
            try:
                error_detail = response.json().get("detail")
            except Exception:
                pass

            if error_detail:
                raise RuntimeError(f"API Error: {error_detail}")
            raise RuntimeError(f"API Error: {response.text or str(e)}")

    def download(
        self,
        source: str,
        asset: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        """Sends a command to download/save assets on the server."""
        payload = {"source": source, "asset": asset}
        if start_date:
            payload["start_date"] = start_date
        if end_date:
            payload["end_date"] = end_date
        res = self.session.post(f"{self.base_url}/download", json=payload)
        return self._handle_response(res)

    def update(self, source: str, asset: str, timeframe: str = "M1") -> dict:
        """Sends a command to update the asset databases."""
        payload = {"source": source, "asset": asset, "timeframe": timeframe}
        res = self.session.post(f"{self.base_url}/update", json=payload)
        return self._handle_response(res)

    def delete(self, source: str, asset: str, timeframe: str | None = None) -> dict:
        """Physically deletes a database or entire asset from the server."""
        payload = {"source": source, "asset": asset}
        if timeframe:
            payload["timeframe"] = timeframe
        res = self.session.post(f"{self.base_url}/delete", json=payload)
        return self._handle_response(res)

    def list_databases(self) -> list[dict[str, Any]]:
        """Returns a list of dictionaries detailing all databases."""
        res = self.session.get(f"{self.base_url}/list")
        data = self._handle_response(res)
        databases = data.get("databases", [])
        return list(databases)

    def get_data(
        self,
        source: str,
        asset: str,
        timeframe: str,
        save_path: str | None = None,
        save_format: str = "parquet",
        timezone: str | None = None,
    ) -> pd.DataFrame | str:
        """
        Downloads OHLCV data from the server as Parquet.
        If save_path is provided, saves to disk and returns the path.
        Otherwise, loads directly into the client's local memory as a DataFrame.
        """
        res = self.session.get(f"{self.base_url}/data/{source}/{asset}/{timeframe}")
        res.raise_for_status()

        if save_path:
            save_format = save_format.lower()
            if save_format == "parquet" and not timezone:
                with open(save_path, "wb") as f:
                    f.write(res.content)
            else:
                df = self._parse_parquet(res.content)
                self._save_dataframe(df, save_path, save_format, timezone)
            return save_path

        df = self._parse_parquet(res.content)
        if timezone:
            df = self._apply_timezone(df, timezone)
        return df

    def info(self, source: str, asset: str, timeframe: str) -> dict:
        """Returns metadata of the specified database on the server."""
        res = self.session.get(f"{self.base_url}/info/{source}/{asset}/{timeframe}")
        return self._handle_response(res)

    def search(
        self,
        source: str = "openbb",
        query: str | None = None,
        exchange: str | None = None,
    ) -> pd.DataFrame:
        """String-based search in the chosen source, returning a pandas DataFrame."""
        params = {"source": source}
        if query:
            params["query"] = query
        if exchange:
            params["exchange"] = exchange

        res = self.session.get(f"{self.base_url}/search", params=params)
        data = self._handle_response(res)
        assets = data.get("assets", [])
        return pd.DataFrame(assets)

    def search_series(
        self,
        source: str = "fred",
        query: str | None = None,
    ) -> pd.DataFrame:
        """Search economic series in the chosen source, returning a pandas DataFrame."""
        params = {"source": source}
        if query:
            params["query"] = query

        res = self.session.get(f"{self.base_url}/series/search", params=params)
        data = self._handle_response(res)
        series = data.get("series", [])
        return pd.DataFrame(series)

    def download_series(
        self,
        source: str,
        series_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
        frequency: str | None = None,
    ) -> dict:
        """Sends a command to download and save a series on the server."""
        payload: dict[str, str] = {"source": source, "series_id": series_id}
        if start_date:
            payload["start_date"] = start_date
        if end_date:
            payload["end_date"] = end_date
        if frequency:
            payload["frequency"] = frequency
        res = self.session.post(f"{self.base_url}/series/download", json=payload)
        return self._handle_response(res)

    def update_series(
        self,
        source: str,
        series_id: str,
        lookback_period: str | None = None,
        frequency: str | None = None,
    ) -> dict:
        """Sends a command to update an existing series on the server."""
        payload: dict[str, str] = {"source": source, "series_id": series_id}
        if lookback_period:
            payload["lookback_period"] = lookback_period
        if frequency:
            payload["frequency"] = frequency
        res = self.session.post(f"{self.base_url}/series/update", json=payload)
        return self._handle_response(res)

    def delete_series(self, source: str, series_id: str) -> dict:
        """Physically deletes a series from the server."""
        payload = {"source": source, "series_id": series_id}
        res = self.session.post(f"{self.base_url}/series/delete", json=payload)
        return self._handle_response(res)

    def list_series(self, skip: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        """Returns a list of dictionaries detailing all stored series."""
        params = {"skip": skip, "limit": limit}
        res = self.session.get(f"{self.base_url}/series/list", params=params)
        data = self._handle_response(res)
        series = data.get("series", [])
        return list(series)

    def get_series_data(
        self,
        source: str,
        series_id: str,
        save_path: str | None = None,
        save_format: str = "parquet",
        timezone: str | None = None,
    ) -> pd.DataFrame | str:
        """
        Downloads a series from the server as Parquet.
        If save_path is provided, saves to disk and returns the path.
        Otherwise, loads directly into the client's local memory as a DataFrame.
        """
        res = self.session.get(f"{self.base_url}/series/data/{source}/{series_id}")
        res.raise_for_status()

        if save_path:
            save_format = save_format.lower()
            if save_format == "parquet" and not timezone:
                with open(save_path, "wb") as f:
                    f.write(res.content)
            else:
                df = self._parse_parquet(res.content)
                self._save_dataframe(df, save_path, save_format, timezone)
            return save_path

        df = self._parse_parquet(res.content)
        if timezone:
            df = self._apply_timezone(df, timezone)
        return df

    def _apply_timezone(self, df: pd.DataFrame, timezone: str) -> pd.DataFrame:
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        df.index = df.index.tz_convert(timezone)
        return df

    def _parse_parquet(self, content: bytes) -> pd.DataFrame:
        return pd.read_parquet(BytesIO(content), engine="pyarrow")

    def _save_dataframe(
        self,
        df: pd.DataFrame,
        save_path: str,
        save_format: str,
        timezone: str | None = None,
    ) -> None:
        if timezone:
            df = self._apply_timezone(df, timezone)

        if save_format == "csv":
            df.to_csv(save_path)
        elif save_format == "excel":
            df.to_excel(save_path)
        elif save_format == "parquet":
            df.to_parquet(save_path, engine="pyarrow")
        else:
            raise ValueError(f"Unsupported save format: {save_format}")
