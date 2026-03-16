import pandas as pd
from datetime import datetime
from .base import BaseFetcher



class OpenBBFetcher(BaseFetcher):
    """
    Downloads M1 data via OpenBB (usually YFinance proxy).
    """
    @property
    def source_name(self) -> str:
        return "OpenBB"
        
    def fetch_data(self, asset: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        
        # Obb equity price history method (using yfinance provider as default for M1)
        # Note que openbb V4 a sintaxe é struct: obb.equity.price.historical()
        
        kwargs = {
            "symbol": asset,
            "interval": "1m",
            "provider": "yfinance"
        }
        
        # Se o ano for > 2000, significa que o usuário especificou um range.
        # Caso contrário (2000-01-01 default absoluto da CLI para Full History),
        # omitimos start e end pro provider trazer o limite histórico dele próprio.
        if start_date.year > 2000:
            kwargs["start_date"] = start_date.strftime("%Y-%m-%d")
            kwargs["end_date"] = end_date.strftime("%Y-%m-%d")
            
        try:
             from openbb import obb
             res = obb.equity.price.historical(**kwargs)
        except Exception as e:
             raise RuntimeError(f"Error in OpenBB module when searching for {asset}: {str(e)}")
             
        df = res.to_df()
        
        if df.empty:
            raise ValueError(f"OpenBB (YFinance) returned empty for {asset} from {start_str} to {end_str}")
            
        # O OpenBB V4 rotorna o index "date"
        if df.index.name != 'date' and 'date' in df.columns:
            df.set_index('date', inplace=True)
            
        # Ajustar timezone e colunas para bater com o layout padrão do storage manager
        if df.index.tz is not None:
             df.index = df.index.tz_convert(None)
             
        col_map = {c.lower(): c.capitalize() for c in df.columns}
        df.rename(columns=col_map, inplace=True)
            
        return df

    def search(self, query: str = None, **kwargs) -> pd.DataFrame:
        """Search assets via OpenBB API."""
        from openbb import obb
        search_args = {}
        if query:
            search_args['query'] = query
        if 'exchange' in kwargs:
            search_args['exchange'] = kwargs['exchange']
            
        res = obb.equity.search(**search_args)
        df = res.to_df()
        return df
