import pandas as pd
from datetime import datetime, timedelta
import sys
from .base import BaseFetcher
from dukascopy_python import fetch, INTERVAL_MIN_1, OFFER_SIDE_BID

def display_progress_bar(iteration, total, prefix='Download:', suffix='Completo', length=40):
    """Exibe um progress bar no terminal."""
    if total == 0:
        total = 1
    percent = f"{100 * (iteration / float(total)):.1f}"
    filled = int(length * iteration // total)
    bar = '█' * filled + '-' * (length - filled)
    sys.stdout.write(f'\r{prefix} |{bar}| {percent}% {suffix}')
    sys.stdout.flush()
    if iteration == total:
        print()

class DukascopyFetcher(BaseFetcher):
    """
    Baixa dados M1 usando a biblioteca dukascopy-python em chunks com progress bar.
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
                raise ValueError(f"O ativo '{asset_upper}' não existe na base da Dukascopy. Use 'search --source dukascopy --query {asset_upper}' para consultar tickets e aliases válidos.")
        else:
            # Fallback provisório caso o arquivo CSV não exista
            print(f"Aviso: Arquivo dukas_assets.csv não encontrado em {csv_path}. Baixando sem validação prévia...")
            asset_clean = asset_upper
            
        dfs = []
        total_days = (end_date - start_date).days
        if total_days <= 0:
            total_days = 1
            
        # Vamos usar chunks de 7 dias para equilibrar velocidade de req e feedback na progress bar
        chunk_size = 7
        total_chunks = (total_days // chunk_size) + (1 if total_days % chunk_size != 0 else 0)
        
        display_progress_bar(0, total_chunks, prefix=f'Baixando {asset_clean}:')
        
        for i in range(total_chunks):
            chunk_start = start_date + timedelta(days=i * chunk_size)
            chunk_end = min(chunk_start + timedelta(days=chunk_size), end_date)
            
            try:
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
                
            display_progress_bar(i + 1, total_chunks, prefix=f'Baixando {asset_clean}:')
            
        if not dfs:
             raise ValueError(f"Dukascopy retornou vazio para {asset_clean} em {start_date} -> {end_date}")
             
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
