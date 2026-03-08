import os
import glob
import pandas as pd
from pathlib import Path

class StorageManager:
    """Gerencia o armazenamento hierárquico dos dados no schema:
       database/{source}/{asset}/{timeframe}/
    """
    
    def __init__(self, base_dir="database"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.format = ".parquet"

    def _get_path(self, source: str, asset: str, timeframe: str) -> Path:
        """Retorna o caminho do arquivo para o dado específico."""
        asset_dir = self.base_dir / source.lower() / asset.upper() / timeframe.upper()
        asset_dir.mkdir(parents=True, exist_ok=True)
        return asset_dir / f"data{self.format}"

    def save_data(self, df: pd.DataFrame, source: str, asset: str, timeframe: str):
        """Salva ou sobreescreve os dados completos."""
        file_path = self._get_path(source, asset, timeframe)
        # Assegura que o index é DateTime e está ordenado
        if not isinstance(df.index, pd.DatetimeIndex):
            if 'date' in df.columns or 'time' in df.columns or 'datetime' in df.columns:
                col = next(c for c in ['datetime', 'date', 'time'] if c in df.columns)
                df[col] = pd.to_datetime(df[col])
                df.set_index(col, inplace=True)
        
        df.sort_index(inplace=True)
        # Removendo fuso horário se houver para não conflitar Parquet
        if df.index.tz is not None:
             df.index = df.index.tz_convert(None)
             
        if self.format == ".parquet":
            df.to_parquet(file_path, engine='fastparquet')
        else:
            df.to_csv(file_path)
            
    def append_data(self, df: pd.DataFrame, source: str, asset: str, timeframe: str):
        """Atualiza/Concatena novos dados aos dados existentes."""
        file_path = self._get_path(source, asset, timeframe)
        if not file_path.exists():
            return self.save_data(df, source, asset, timeframe)
            
        # Carregar existente e juntar
        existing_df = self.load_data(source, asset, timeframe)
        combined_df = pd.concat([existing_df, df])
        
        # Tratar duplicações dando exclusividade aos dados mais recentes ou primeiro a chegar
        combined_df = combined_df[~combined_df.index.duplicated(keep='last')]
        self.save_data(combined_df, source, asset, timeframe)
        
    def load_data(self, source: str, asset: str, timeframe: str) -> pd.DataFrame:
        """Carrega os dados de um arquivo."""
        file_path = self._get_path(source, asset, timeframe)
        if not file_path.exists():
            raise FileNotFoundError(f"Database não encontrada: {source} -> {asset} ({timeframe})")
            
        if self.format == ".parquet":
            return pd.read_parquet(file_path, engine='fastparquet')
        else:
            df = pd.read_csv(file_path, index_col=0, parse_dates=True)
            return df

    def delete_database(self, source: str, asset: str, timeframe: str = None) -> bool:
        """Exclui a base de dados em específico ou todos os timeframes se não informado."""
        import shutil
        if timeframe:
            file_path = self._get_path(source, asset, timeframe)
            if file_path.exists():
                file_path.unlink()
                # Opcional: remover a pasta se estiver vazia
                try:
                    os.rmdir(file_path.parent)
                except OSError:
                    pass 
                return True
        else:
            asset_dir = self.base_dir / source.lower() / asset.upper()
            if asset_dir.exists():
                shutil.rmtree(asset_dir)
                return True
        return False

    def delete_all(self) -> bool:
        """Exclui todas as bases de dados."""
        import shutil
        try:
            for item in self.base_dir.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
            return True
        except OSError:
            return False

    def get_database_info(self, source: str, asset: str, timeframe: str) -> dict:
        """Retorna as informações descritivas da base de dados."""
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
        """Remove recursivamente diretórios vazios a partir de um ponto."""
        if not directory.is_dir():
            return

        # Primeiro, visita os filhos recursivamente
        for entry in directory.iterdir():
            if entry.is_dir():
                self._cleanup_empty_dirs(entry)

        # Se após a limpeza dos filhos, este diretório estiver vazio, remove-o
        # Exceto se for a base_dir principal
        if directory != self.base_dir and not any(directory.iterdir()):
            try:
                directory.rmdir()
            except OSError:
                pass

    def list_databases(self) -> list:
        """Retorna uma lista de todas as bases baixadas e salvas."""
        # Limpa pastas vazias antes de listar
        self._cleanup_empty_dirs(self.base_dir)
        
        all_dbs = []
        # Percorrendo subpastas (nível 3) -> source/asset/timeframe
        for source_path in self.base_dir.iterdir():
            if not source_path.is_dir(): continue
            for asset_path in source_path.iterdir():
                if not asset_path.is_dir(): continue
                for time_path in asset_path.iterdir():
                    if not time_path.is_dir(): continue
                    if (time_path / f"data{self.format}").exists():
                        all_dbs.append({
                            "source": source_path.name,
                            "asset": asset_path.name,
                            "timeframe": time_path.name
                        })
        return all_dbs
