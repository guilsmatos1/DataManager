from abc import ABC, abstractmethod
import pandas as pd
from datetime import datetime

class BaseFetcher(ABC):
    """
    Base interface for all Data Fetchers
    """
    
    @property
    @abstractmethod
    def source_name(self) -> str:
        pass
        
    @abstractmethod
    def fetch_data(self, asset: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        """
        Downloads M1 data for the asset in the specified time range.
        Expects to return a pandas DataFrame with:
        - Index: datetime timezone-naive
        - Colunas: Open, High, Low, Close, Volume
        """
        pass

    def search(self, query: str = None, **kwargs) -> pd.DataFrame:
        """
        Optional: Search for assets supported by this fetcher.
        Returns a DataFrame with search results or raises NotImplementedError.
        """
        raise NotImplementedError(f"Search not implemented for {self.source_name}")
