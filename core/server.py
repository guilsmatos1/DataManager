from datetime import datetime
from pathlib import Path
import pandas as pd
from data_management.storage import StorageManager
from data_management.processor import DataProcessor
from fetchers.dukascopy_fetcher import DukascopyFetcher
from fetchers.openbb_fetcher import OpenBBFetcher

class DataManager:
    """
    Controlador central da aplicação.
    """
    
    def __init__(self):
        self.storage = StorageManager()
        self.processor = DataProcessor()
        
        # Mapeamento dinâmico de fontes de dados suportadas
        self._fetchers = {
            "DUKASCOPY": DukascopyFetcher(),
            "OPENBB": OpenBBFetcher()
        }
        
    def _get_fetcher(self, source_name: str):
        source = source_name.upper()
        if source not in self._fetchers:
             raise ValueError(f"Fonte de dados não suportada: {source_name}. Disponíveis: {list(self._fetchers.keys())}")
        return self._fetchers[source]

    def download_data(self, source: str, asset: str, start_date: datetime, end_date: datetime):
        """Baixa e salva dados em M1."""
        print(f"[{datetime.now()}] Iniciando download de {asset} via {source}...")
        fetcher = self._get_fetcher(source)
        df_m1 = fetcher.fetch_data(asset, start_date, end_date)
        
        # O Fetcher sempre devolve M1 naive-datetime indexado e ordenado
        self.storage.save_data(df_m1, source, asset, timeframe="M1")
        print(f"[{datetime.now()}] Base de dados {asset} (M1) salva com sucesso! (Total: {len(df_m1)} linhas)")

    def update_data(self, source: str, asset: str, timeframe: str = "M1"):
        """Descobre a última data na base existente e faz download até hoje (append)."""
        info = self.storage.get_database_info(source, asset, timeframe)
        if info.get("status") == "Not Found":
            print(f"ERRO: Base de dados {asset} ({timeframe}) não existe.")
            print("Deseja baixar do zero? Use a função de Download.")
            return

        last_date_str = info["end_date"]
        # Naive datetime
        last_date = datetime.strptime(last_date_str, "%Y-%m-%d %H:%M:%S")
        now = datetime.now()
        
        if last_date.date() >= now.date() and (now - last_date).total_seconds() < 3600:
             print(f"[{datetime.now()}] {asset} já está atualizado.")
             return
             
        print(f"[{datetime.now()}] Atualizando {asset} a partir de {last_date}...")
        fetcher = self._get_fetcher(source)
        
        # Importante: Como `timeframe` aqui pode ser H1 por exemplo, nós sempre atualizamos a base M1, 
        # e se for pedido para atualizar H1, nos convertemos dps.
        # Por padrão: sempre baixamos M1 do Fetcher.
        new_df = fetcher.fetch_data(asset, last_date, now)
        
        # Se for um timeframe diferente de M1, nos convertemos
        if timeframe.upper() != "M1":
             new_df = self.processor.resample_ohlc(new_df, timeframe)
             
        self.storage.append_data(new_df, source, asset, timeframe)
        print(f"[{datetime.now()}] Base {asset} ({timeframe}) atualizada com sucesso!")

    def update_all_databases(self):
        """Atualiza todas as bases de dados M1 e realiza o resample dinâmico para timeframes superiores."""
        dbs = self.list_all()
        if not dbs:
            print(f"[{datetime.now()}] Nenhuma base de dados encontrada para atualizar.")
            return

        print(f"\n[{datetime.now()}] Iniciando a atualização automática de todas as bases globais...")

        m1_dbs = [db for db in dbs if db['timeframe'] == 'M1']
        other_dbs = [db for db in dbs if db['timeframe'] != 'M1']

        print(f"[{datetime.now()}] Foram detectadas {len(m1_dbs)} base(s) originais (M1) e {len(other_dbs)} base(s) de timeframes maiores.")

        # Primeiro, atualiza todos os M1
        for db in m1_dbs:
            try:
                self.update_data(db['source'], db['asset'], "M1")
            except Exception as e:
                print(f"[{datetime.now()}] Erro ao atualizar base M1 ({db['source']}/{db['asset']}): {e}")

        # Depois reconstrói as de maior timeframe baseando-se no novo M1 recém atualizado.
        for db in other_dbs:
            try:
                print(f"\n[{datetime.now()}] Sincronizando e Reconstruindo timeframe {db['timeframe']} para {db['source']}/{db['asset']}...")
                self.resample_database(db['source'], db['asset'], db['timeframe'])
            except Exception as e:
                print(f"[{datetime.now()}] Erro ao converter base {db['timeframe']} ({db['source']}/{db['asset']}): {e}")

        print(f"\n[{datetime.now()}] Tarefa global de atualização (Updates & Resamples) finalizada com sucesso!\n")

    def delete_database(self, source: str, asset: str, timeframe: str = None):
        """Exclui base de dados (ou todos os timeframes do ativo)"""
        success = self.storage.delete_database(source, asset, timeframe)
        target = f"{source}/{asset}/{timeframe}" if timeframe else f"{source}/{asset} (todos os timeframes)"
        if success:
             print(f"Base de dados apagada: {target}")
        else:
             print(f"Base de dados não encontrada: {target}")

    def delete_all_databases(self):
        """Exclui todas as bases de dados de todas as fontes"""
        success = self.storage.delete_all()
        if success:
             print("Todas as bases de dados foram apagadas com sucesso.")
        else:
             print("Erro ao apagar as bases de dados.")

    def info(self, source: str, asset: str, timeframe: str) -> dict:
        return self.storage.get_database_info(source, asset, timeframe)

    def list_all(self):
        """Retorna a lista completa de bases com suas informações."""
        dbs = self.storage.list_databases()
        if not dbs:
             return []
             
        detailed_dbs = []
        for db in dbs:
            info = self.storage.get_database_info(db['source'], db['asset'], db['timeframe'])
            detailed_dbs.append(info)
            
        return detailed_dbs
        
        
    def show_search_summary(self):
        """Apresenta a quantidade total de ativos em cada fonte sem listar."""
        print(f"\n[{datetime.now()}] Resumo de ativos disponíveis para busca:")
        
        # Dukascopy
        duka_count = 0
        csv_path = Path("database") / "dukas_assets.csv"
        if csv_path.exists():
            try:
                df = pd.read_csv(csv_path)
                duka_count = len(df)
            except:
                pass
        print(f"  ● Dukascopy: {duka_count} ativos (Base Local)")

        # OpenBB
        print(f"  ● OpenBB: Buscando total na API...", end="\r")
        try:
            from openbb import obb
            # Busca vazia para obter o count total retornado pelo provedor default
            res = obb.equity.search(query="")
            df_obb = res.to_df()
            obb_count = len(df_obb)
            print(f"  ● OpenBB: {obb_count} ativos encontrados (via API)    ")
        except Exception:
            print(f"  ● OpenBB: Milhares de ativos disponíveis (Erro ao contar)   ")
        print()

    def search_assets(self, source: str = "openbb", query: str = None, exchange: str = None):
        """Busca em OpenBB ou Dukascopy ativos disponíveis."""
        source = source.lower()
        if source == "openbb":
            print(f"\n[{datetime.now()}] Buscando ativos no OpenBB...")
            try:
                from openbb import obb
                kwargs = {}
                if query:
                    kwargs['query'] = query
                if exchange:
                    kwargs['exchange'] = exchange
                    
                res = obb.equity.search(**kwargs)
                df = res.to_df()
                
                if df.empty:
                    print("Nenhum ativo encontrado para estes parâmetros no OpenBB.")
                    return
                    
                print(f"Foram encontrados {len(df)} resultados. Exibindo os primeiros 20:")
                print(f"{'=' * 95}")
                header = f"{'TICKER':<15} | {'NOME DA EMPRESA':<55} | {'BOLSA':<15}"
                print(header)
                print(f"{'-' * 95}")
                
                # Reseta o index caso symbol esteja no indice do OpenBB
                df = df.reset_index()
                df = df.fillna("")
                for _, row in df.head(20).iterrows():
                    symbol = str(row.get('symbol', ''))
                    name = str(row.get('name', ''))[:53]
                    exc = str(row.get('exchange', ''))
                    print(f"{symbol:<15} | {name:<55} | {exc:<15}")
                print(f"{'=' * 95}")
            except Exception as e:
                print(f"Erro ao buscar ativos no OpenBB: {e}")
                
        elif source == "dukascopy":
            print(f"\n[{datetime.now()}] Buscando ativos offline (Dukascopy)...")
            try:
                # O caminho é relativo à subpasta data onde salvamos o script CSV
                csv_path = Path("database") / "dukas_assets.csv"
                if not csv_path.exists():
                    print("O arquivo 'dukas_assets.csv' não foi encontrado. Execute o script de merge primeiro.")
                    return
                
                df = pd.read_csv(csv_path)
                # Forçando strings e removendo NaNs
                df = df.fillna("")
                
                if query:
                    # Busca insensível a maiúsculas na coluna ticker, alias ou nome_do_ativo
                    mask = (
                        df['ticker'].str.contains(query, case=False) |
                        df['alias'].str.contains(query, case=False) |
                        df['nome_do_ativo'].str.contains(query, case=False)
                    )
                    df = df[mask]
                
                if df.empty:
                    print(f"Nenhum ativo contendo '{query}' foi encontrado.")
                    return
                    
                print(f"Foram encontrados {len(df)} resultados. Exibindo os primeiros 20:")
                print(f"{'=' * 105}")
                header = f"{'TICKER':<20} | {'ALIAS':<15} | {'NOME DO ATIVO':<50} | {'CATEGORIA':<10}"
                print(header)
                print(f"{'-' * 105}")
                for _, row in df.head(20).iterrows():
                    print(f"{str(row['ticker']):<20} | {str(row['alias']):<15} | {str(row['nome_do_ativo'])[:48]:<50} | {str(row['categoria']):<10}")
                print(f"{'=' * 105}")

            except Exception as e:
                print(f"Erro ao buscar ativos na Dukascopy: {e}")
        else:
            print(f"Fonte {source} não suportada na busca. Tente openbb ou dukascopy.")

    def resample_database(self, source: str, asset: str, target_timeframe: str):
        """Lê M1 de uma base existente e converte e salva no timeframe alvo."""
        try:
            df_m1 = self.storage.load_data(source, asset, timeframe="M1")
        except FileNotFoundError:
            print(f"Erro: Não há base M1 salva para {asset} na fonte {source}. Baixe-a primeiro.")
            return

        print(f"[{datetime.now()}] Convertendo {asset} M1 para {target_timeframe}...")
        df_resampled = self.processor.resample_ohlc(df_m1, target_timeframe)
        self.storage.save_data(df_resampled, source, asset, target_timeframe)
        print(f"[{datetime.now()}] Conversão finalizada e salva!")
