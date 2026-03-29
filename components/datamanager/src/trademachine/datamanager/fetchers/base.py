from abc import ABC, abstractmethod
from datetime import datetime

import pandas as pd


class BaseFetcher(ABC):
    """
    Base interface for all Data Fetchers.
    Provides common post-processing to ensure consistent DataFrame output
    across all fetchers.
    """

    @property
    @abstractmethod
    def source_name(self) -> str:
        pass

    @abstractmethod
    def fetch_data(
        self, asset: str, start_date: datetime, end_date: datetime, **kwargs
    ) -> pd.DataFrame:
        """
        Downloads M1 data for the asset in the specified time range.
        Expects to return a pandas DataFrame with:
        - Index: datetime timezone-naive
        - Colunas: Open, High, Low, Close, Volume
        """
        pass

    def search(self, query: str | None = None, **kwargs) -> pd.DataFrame:
        """
        Optional: Search for assets supported by this fetcher.
        Returns a DataFrame with search results or raises NotImplementedError.
        """
        raise NotImplementedError(f"Search not implemented for {self.source_name}")

    def _normalize_timezone(self, df: pd.DataFrame) -> pd.DataFrame:
        """Strip timezone from index if present — ensures timezone-naive datetimes."""
        if df.index.tz is not None:
            df.index = df.index.tz_convert(None)
        return df

    def _normalize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Rename columns to Title-Case (e.g. open → Open, volume → Volume)."""
        col_map = {c.lower(): c.capitalize() for c in df.columns}
        df.rename(columns=col_map, inplace=True)
        return df
