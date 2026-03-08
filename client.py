import requests
import pandas as pd
from typing import Optional, List, Dict, Any
from io import BytesIO

class DataManagerClient:
    """
    Cliente Python para se conectar ao DataManager Network API.
    """
    def __init__(self, base_url: str = "http://127.0.0.1:8686"):
        self.base_url = base_url.rstrip("/")

    def _handle_response(self, response: requests.Response) -> Dict[str, Any]:
        """Extrai o JSON da resposta gerando exception em caso de falha HTTP"""
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
        """Envia um comando para baixar/salvar ativos no servidor."""
        payload = {"source": source, "asset": asset}
        if start_date: payload["start_date"] = start_date
        if end_date: payload["end_date"] = end_date
        res = requests.post(f"{self.base_url}/download", json=payload)
        return self._handle_response(res)

    def update(self, source: str, asset: str, timeframe: str = "M1") -> dict:
        """Envia um comando para atualizar as bases do ativo."""
        payload = {"source": source, "asset": asset, "timeframe": timeframe}
        res = requests.post(f"{self.base_url}/update", json=payload)
        return self._handle_response(res)

    def delete(self, source: str, asset: str, timeframe: str = None) -> dict:
        """Deleta fisicamente uma base ou ativo inteiro do servidor."""
        payload = {"source": source, "asset": asset}
        if timeframe: payload["timeframe"] = timeframe
        res = requests.post(f"{self.base_url}/delete", json=payload)
        return self._handle_response(res)

    def resample(self, source: str, asset: str, target_timeframe: str) -> dict:
        """Regera ou cria um time_frame a partir da base original M1."""
        payload = {"source": source, "asset": asset, "target_timeframe": target_timeframe}
        res = requests.post(f"{self.base_url}/resample", json=payload)
        return self._handle_response(res)

    def list_databases(self) -> List[dict]:
        """Retorna uma lista de dicionários detalhando todas bases de dados."""
        res = requests.get(f"{self.base_url}/list")
        data = self._handle_response(res)
        return data.get("databases", [])

    def info(self, source: str, asset: str, timeframe: str) -> dict:
        """Retorna os metadados da base especificada no servidor."""
        res = requests.get(f"{self.base_url}/info/{source}/{asset}/{timeframe}")
        return self._handle_response(res)

    def search(self, source: str = "openbb", query: str = None, exchange: str = None) -> pd.DataFrame:
        """Busca baseados em string na fonte escolhida e retorna um pandas DataFrame."""
        params = {"source": source}
        if query: params["query"] = query
        if exchange: params["exchange"] = exchange
        
        res = requests.get(f"{self.base_url}/search", params=params)
        data = self._handle_response(res)
        assets = data.get("assets", [])
        return pd.DataFrame(assets)

    def get_data(self, source: str, asset: str, timeframe: str) -> pd.DataFrame:
        """
        Baixa nativamente o dataframe `.parquet` via streamming do servidor 
        e carrega direto na memória local do cliente.
        """
        res = requests.get(f"{self.base_url}/data/{source}/{asset}/{timeframe}")
        res.raise_for_status()
        
        # Carrega o binário na memória para o pandas ler nativamente o parquet
        file_obj = BytesIO(res.content)
        df = pd.read_parquet(file_obj, engine='fastparquet')
        return df

if __name__ == "__main__":
    # Script de Exemplo simples
    # Lembre de iniciar o servidor em outro terminal antes: `source venv/bin/activate && python network_server.py`
    
    print("Testando DataManager Client...")
    
    client = DataManagerClient("http://127.0.0.1:8686")
    
    try:
        from datetime import datetime, timedelta
        start = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
        end = datetime.now().strftime("%Y-%m-%d")
        
        print(f"\n1. Solicitando download de AAPL (OpenBB) pelo Servidor ({start} to {end})...")
        res = client.download("OPENBB", "AAPL", start_date=start, end_date=end)
        print("Resposta:", res)
        
        print("\n2. Listando bases no servidor:")
        dbs = client.list_databases()
        for db in dbs:
            print(f" - {db['source']}/{db['asset']} ({db['timeframe']}) -> {db['rows']} linhas")
            
        print("\n3. Fazendo download do DataFrame Parquet pela Rede...")
        df = client.get_data("OPENBB", "AAPL", "M1")
        print("\nDataFrame recebido no Cliente Local (!):")
        print(df.head())
        print(f"Total de Registros transferidos: {len(df)}")
            
        print("\nExemplo finalizado com sucesso!")
    except Exception as e:
        print(f"Erro na conexão (O servidor está rodando?): {e}")
