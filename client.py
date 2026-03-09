import requests
import pandas as pd
from typing import Optional, List, Dict, Any, Union
from io import BytesIO

class DataManagerClient:
    """
    Cliente Python para se conectar ao DataManager Network API protegido com API Key.
    """
    def __init__(self, base_url: str = "http://127.0.0.1:8686", api_key: str = "K91DS441s31"):
        self.base_url = base_url.rstrip("/")
        # Usa um Session para carregar automaticamente o header customizado
        self.session = requests.Session()
        self.session.headers.update({"X-API-Key": api_key})

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
        res = self.session.post(f"{self.base_url}/download", json=payload)
        return self._handle_response(res)

    def update(self, source: str, asset: str, timeframe: str = "M1") -> dict:
        """Envia um comando para atualizar as bases do ativo."""
        payload = {"source": source, "asset": asset, "timeframe": timeframe}
        res = self.session.post(f"{self.base_url}/update", json=payload)
        return self._handle_response(res)

    def delete(self, source: str, asset: str, timeframe: str = None) -> dict:
        """Deleta fisicamente uma base ou ativo inteiro do servidor."""
        payload = {"source": source, "asset": asset}
        if timeframe: payload["timeframe"] = timeframe
        res = self.session.post(f"{self.base_url}/delete", json=payload)
        return self._handle_response(res)

    def resample(self, source: str, asset: str, target_timeframe: str) -> dict:
        """Regera ou cria um time_frame a partir da base original M1."""
        payload = {"source": source, "asset": asset, "target_timeframe": target_timeframe}
        res = self.session.post(f"{self.base_url}/resample", json=payload)
        return self._handle_response(res)

    def list_databases(self) -> List[dict]:
        """Retorna uma lista de dicionários detalhando todas bases de dados."""
        res = self.session.get(f"{self.base_url}/list")
        data = self._handle_response(res)
        return data.get("databases", [])

    def info(self, source: str, asset: str, timeframe: str) -> dict:
        """Retorna os metadados da base especificada no servidor."""
        res = self.session.get(f"{self.base_url}/info/{source}/{asset}/{timeframe}")
        return self._handle_response(res)

    def search(self, source: str = "openbb", query: str = None, exchange: str = None) -> pd.DataFrame:
        """Busca baseados em string na fonte escolhida e retorna um pandas DataFrame."""
        params = {"source": source}
        if query: params["query"] = query
        if exchange: params["exchange"] = exchange
        
        res = self.session.get(f"{self.base_url}/search", params=params)
        data = self._handle_response(res)
        assets = data.get("assets", [])
        return pd.DataFrame(assets)

    def get_data(self, source: str, asset: str, timeframe: str, save_path: str = None, save_format: str = "parquet") -> Union[pd.DataFrame, str]:
        """
        Baixa o arquivo `.parquet` do servidor.
        Se save_path for fornecido, salva no disco e retorna o caminho.
        É possível definir o 'save_format' como 'parquet' ou 'csv'.
        Caso contrário, carrega direto na memória local do cliente como DataFrame.
        """
        res = self.session.get(f"{self.base_url}/data/{source}/{asset}/{timeframe}")
        res.raise_for_status()
        
        if save_path:
            save_format = save_format.lower()
            if save_format == "csv":
                file_obj = BytesIO(res.content)
                df = pd.read_parquet(file_obj, engine='fastparquet')
                df.to_csv(save_path)
            elif save_format == "parquet":
                with open(save_path, 'wb') as f:
                    f.write(res.content)
            else:
                raise ValueError("Formato não suportado. Escolha 'parquet' ou 'csv'.")
            return save_path
        else:
            # Carrega o binário na memória para o pandas ler nativamente o parquet
            file_obj = BytesIO(res.content)
            df = pd.read_parquet(file_obj, engine='fastparquet')
            return df

if __name__ == "__main__":
    # Script de Exemplo simples
    print("Testando DataManager Client...")
    
    # Inicia o cliente passando a host padrao e a chave (opcional se bater c/ o padrao do __init__)
    client = DataManagerClient("http://100.100.10.240:8686", api_key="K91DS441s31")
    
    try:
        from datetime import datetime, timedelta
        import time

        target_source = "DUKASCOPY"
        target_asset = "USATECH"
        target_tf = "H1"

        print(f"\n1. Listando bases no servidor...")
        dbs = client.list_databases()
        exists = any(db['source'].upper() == target_source and db['asset'] == target_asset and db['timeframe'] == target_tf for db in dbs)

        if exists:
            print(f" -> A base {target_asset} ({target_tf}) já existe no servidor.")
        else:
            print(f" -> A base {target_asset} ({target_tf}) NÃO foi encontrada. Solicitando download...")
            start = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
            end = datetime.now().strftime("%Y-%m-%d")
            res = client.download(target_source, target_asset, start_date=start, end_date=end)
            print(f" -> Resposta do servidor: {res}")
            print(" -> Aguardando alguns segundos para o processamento inicial (async)...")
            time.sleep(5)

        print(f"\n2. Baixando dados de {target_asset} ({target_tf}) para CSV local...")
        csv_path = client.get_data(
            source=target_source,
            asset=target_asset,
            timeframe=target_tf,
            save_path="usatech_resultado.csv",
            save_format="csv"
        )
        print(f" -> Sucesso! Arquivo salvo em: {csv_path}")

        print("\nExemplo finalizado com sucesso!")
    except Exception as e:
        print(f"Erro no fluxo do cliente: {e}")
