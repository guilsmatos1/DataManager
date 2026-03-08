from abc import ABC, abstractmethod
import pandas as pd
from datetime import datetime

class BaseFetcher(ABC):
    """
    Interface base para todos os Data Fetchers
    """
    
    @property
    @abstractmethod
    def source_name(self) -> str:
        pass
        
    @abstractmethod
    def fetch_data(self, asset: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        """
        Baixa dados M1 do ativo no intervalo de tempo especificado.
        Espera retornar um pandas DataFrame com:
        - Index: datetime timezone-naive
        - Colunas: Open, High, Low, Close, Volume
        """
        pass
