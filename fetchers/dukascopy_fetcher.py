import pandas as pd
from datetime import datetime, timedelta
import sys
from .base import BaseFetcher
import logging
from tqdm import tqdm

from colorama import Fore, Style

# Desativa prints e infos internos do dukascopy-python
logging.getLogger("dukascopy_python").setLevel(logging.WARNING)
logging.getLogger("DUKASCRIPT").setLevel(logging.WARNING)

class DukascopyFetcher(BaseFetcher):
    """
    Downloads M1 data using the dukascopy-python library in chunks with a progress bar.
    """
    @property
    def source_name(self) -> str:
        return "Dukascopy"
        
    def fetch_data(self, asset: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        asset_upper = asset.upper()
        
        from pathlib import Path
        import os
        
        # Como o script main e os workers rodam a partir de "Servidor de Dados", 
        # a pasta data deve estar no mesmo diretório de onde o comando é rodado.
        csv_path = Path("metadata") / "dukas_assets.csv"
        
        if csv_path.exists():
            df_assets = pd.read_csv(csv_path).fillna("")
            
            # Checa se existe no ticker ou no alias exato
            match = df_assets[(df_assets["ticker"].str.upper() == asset_upper) | 
                              (df_assets["alias"].str.upper() == asset_upper)]
            
            if not match.empty:
                asset_clean = match.iloc[0]["ticker"]
            else:
                raise ValueError(f"Asset '{asset_upper}' does not exist in the Dukascopy database. Use 'search --source dukascopy --query {asset_upper}' to query valid tickers and aliases.")
        else:
            # Fallback provisório caso o arquivo CSV não exista
            asset_clean = asset_upper
            
        dfs = []
        total_days = (end_date - start_date).days
        if total_days <= 0:
            total_days = 1
            
        # Vamos usar chunks de 7 dias para equilibrar velocidade de req e feedback na progress bar
        chunk_size = 7
        total_chunks = (total_days // chunk_size) + (1 if total_days % chunk_size != 0 else 0)
        
        for i in tqdm(range(total_chunks), desc=f"Fetching {asset_clean} (Dukascopy)", leave=False):
            chunk_start = start_date + timedelta(days=i * chunk_size)
            chunk_end = min(chunk_start + timedelta(days=chunk_size), end_date)
            
            try:
                from dukascopy_python import fetch, INTERVAL_MIN_1, OFFER_SIDE_BID
                df_chunk = fetch(
                    instrument=asset_clean,
                    interval=INTERVAL_MIN_1,
                    offer_side=OFFER_SIDE_BID,
                    start=chunk_start,
                    end=chunk_end
                )
                if df_chunk is not None and not df_chunk.empty:
                    dfs.append(df_chunk)
            except Exception as e:
                # Finais de semana podem retornar falhas por falta de dados
                pass
                
        if not dfs:
             return pd.DataFrame() # Return empty instead of raising error to handle gaps in chunked download
             
        df = pd.concat(dfs)
        
        # O Dukascopy-python já retorna um DF setado por index. Garantir que não tenha gaps indesejados e duplicatas 
        df = df[~df.index.duplicated(keep='last')]
        
        # Tratamento de colunas e indice
        if df.index.tz is not None:
             df.index = df.index.tz_convert(None)
             
        col_map = {c.lower(): c.capitalize() for c in df.columns}
        df.rename(columns=col_map, inplace=True)
        
        df.index.name = "datetime"
        df.sort_index(inplace=True)
            
        return df

    def search(self, query: str = None, **kwargs) -> pd.DataFrame:
        """Search Dukascopy offline database."""
        from pathlib import Path
        csv_path = Path("metadata") / "dukas_assets.csv"
        
        if not csv_path.exists():
             return pd.DataFrame()
             
        df = pd.read_csv(csv_path).fillna("")
        
        if query:
            # Case-insensitive search in ticker, alias or asset name
            mask = (
                df['ticker'].str.contains(query, case=False) |
                df['alias'].str.contains(query, case=False) |
                df['nome_do_ativo'].str.contains(query, case=False)
            )
            df = df[mask]
            
        return df
