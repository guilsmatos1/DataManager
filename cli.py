import cmd
from datetime import datetime
from dateutil.parser import parse

from core.server import DataManager
import argparse
import shlex
from colorama import init, Fore, Style

init(autoreset=True)

class DataManagerCLI(cmd.Cmd):
    intro = fr"""
{Fore.CYAN}{Style.BRIGHT}
  _____       _         __  __                                   
 |  __ \     | |       |  \/  |                                  
 | |  | | __ _| |_ __ _| \  / | __ _ _ __   __ _  __ _  ___ _ __ 
 | |  | |/ _` | __/ _` | |\/| |/ _` | '_ \ / _` |/ _` |/ _ \ '__|
 | |__| | (_| | || (_| | |  | | (_| | | | | (_| | (_| |  __/ |   
 |_____/ \__,_|\__\__,_|_|  |_|\__,_|_| |_|\__,_|\__, |\___|_|   
                                                  __/ |          
                                                 |___/           
{Fore.WHITE}════════════════════════════════════════════════════════════════════════
                {Fore.CYAN}{Style.BRIGHT}DataManager{Fore.WHITE} - {Fore.GREEN}v1.2.0{Fore.WHITE}
════════════════════════════════════════════════════════════════════════
 {Fore.YELLOW}● MODO INTERATIVO ●{Fore.WHITE}

 {Style.BRIGHT}COMANDOS:{Style.NORMAL}
 {Fore.CYAN}download{Fore.WHITE} | {Fore.CYAN}update{Fore.WHITE} | {Fore.CYAN}search{Fore.WHITE} | {Fore.CYAN}list{Fore.WHITE} | {Fore.CYAN}resample{Fore.WHITE} | {Fore.CYAN}delete{Fore.WHITE} | {Fore.CYAN}quality{Fore.WHITE}
        
 {Fore.WHITE}Digite {Fore.YELLOW}'help'{Fore.WHITE} para o manual completo ou {Fore.YELLOW}'exit'{Fore.WHITE} para sair.
════════════════════════════════════════════════════════════════════════
"""
    prompt = f"{Fore.GREEN}DataManager> {Style.RESET_ALL}"

    def do_help(self, arg):
        """Custom help command to show all commands in a structured way."""
        if arg:
            # Se o usuário pedir help de um comando específico, usa o padrão do cmd
            super().do_help(arg)
        else:
            print(self.intro)
            print(f"{Fore.CYAN}{Style.BRIGHT}--- GUIA DE COMANDOS ---{Style.RESET_ALL}\n")
            for attr in dir(self):
                if attr.startswith("do_") and attr not in ["do_EOF", "do_quit", "do_help"]:
                    cmd_name = attr[3:]
                    doc = getattr(self, attr).__doc__
                    print(f"{Fore.YELLOW}● {cmd_name.upper()}{Style.RESET_ALL}")
                    if doc:
                        cleaned_doc = "\n".join("  " + line.strip() for line in doc.strip().split("\n"))
                        print(f"{Fore.WHITE}{cleaned_doc}\n")

    def __init__(self):
        super().__init__()
        self.server = DataManager()
        
    def do_download(self, arg):
        """
        Baixar novos dados. Uso: download <fonte> <ativo1,ativo2,...> [start_date] [end_date]
        Exemplos:
          download OPENBB AAPL,MSFT 2023-01-01 2024-01-01
          download DUKASCOPY EURUSD,GBPUSD (baixa histórico completo)
        """
        args = arg.split()
        if len(args) not in [2, 3, 4]:
            print("Erro: Uso correto: download <fonte> <ativos,separados,por,virgula> [start_date] [end_date]")
            return
            
        source = args[0]
        assets = [a.strip() for a in args[1].split(',') if a.strip()]
        
        try:
            # Definição dos defaults de data se o usuário omitir (Download Full History)
            if len(args) >= 3:
                start_date = parse(args[2])
            else:
                # Retorna ao passado distante
                start_date = datetime(2000, 1, 1)
                print(f"{Fore.YELLOW}Data inicial omitida. Iniciando busca do log completo a partir de {start_date.date()}...")
                
            if len(args) == 4:
                end_date = parse(args[3])
            else:
                end_date = datetime.now()
                if len(args) < 4:
                    print(f"{Fore.YELLOW}Data final omitida. Indo até a data atual ({end_date.date()}).")

            for asset in assets:
                try:
                    self.server.download_data(source, asset, start_date, end_date)
                except Exception as e:
                    print(f"{Fore.RED}Erro no download de {asset}: {e}")
        except Exception as e:
            print(f"{Fore.RED}Erro nas datas do download: {e}")

    def do_update(self, arg):
        """
        Atualiza uma base de dados existente. Uso: update <fonte> <ativo1,ativo2,...> [timeframe]
        Exemplo: update OPENBB AAPL,MSFT
        Exemplo: update OPENBB AAPL,MSFT H1
        Comando especial: update all (Atualiza todos M1 e faz o resample nos TF maiores)
        """
        args = arg.split()
        
        if len(args) == 1 and args[0].lower() == "all":
            self.server.update_all_databases()
            return

        if len(args) not in [2, 3]:
            print("Erro: Uso correto: update <fonte> <ativos,separados,por,virgula> [timeframe=M1] ou update all")
            return
            
        source = args[0]
        assets = [a.strip() for a in args[1].split(',') if a.strip()]
        timeframe = args[2] if len(args) == 3 else "M1"
        
        for asset in assets:
            try:
                self.server.update_data(source, asset, timeframe)
            except Exception as e:
                print(f"{Fore.RED}Erro ao atualizar {asset}: {e}")

    def do_delete(self, arg):
        """
        Deletar base(s) de dados. Uso: delete <fonte> <ativos,separados,por,virgula> [timeframe]
                                       delete all
        Exemplos: 
          delete OPENBB AAPL,MSFT M1
          delete dukascopy eurusd
          delete all
        """
        args = arg.split()
        if len(args) == 1 and args[0].lower() == 'all':
            confirm = input(f"{Fore.RED}ATENÇÃO: Você está prestes a deletar TODAS as bases de dados de todas as fontes. Deseja continuar? (s/N): {Style.RESET_ALL}")
            if confirm.lower() == 's':
                self.server.delete_all_databases()
            else:
                print("Operação cancelada.")
            return

        if len(args) < 2 or len(args) > 3:
            print("Erro: Uso correto: delete <fonte> <ativos,separados,por,virgula> [timeframe] ou delete all")
            return
            
        source = args[0]
        assets = [a.strip() for a in args[1].split(',') if a.strip()]
        tf = args[2] if len(args) == 3 else None
        
        for asset in assets:
            try:
                self.server.delete_database(source, asset, tf)
            except Exception as e:
                print(f"{Fore.RED}Erro ao deletar {asset}: {e}")

    def do_info(self, arg):
        """
        Mostra informações de uma base. Uso: info <fonte> <ativo> <timeframe>
        """
        args = arg.split()
        if len(args) != 3:
             print("Erro: Uso correto: info <fonte> <ativo> <timeframe>")
             return
             
        info = self.server.info(args[0], args[1], args[2])
        for k, v in info.items():
             print(f"{k.capitalize()}: {v}")

    def do_list(self, arg):
        """Lista todas as bases salvas com detalhes técnicos. Uso: list"""
        dbs = self.server.list_all()
        if not dbs:
            print(f"{Fore.YELLOW}Nenhuma base de dados encontrada no disco.")
            return

        print(f"\n{Fore.CYAN}{Style.BRIGHT}BASES DE DADOS PERSISTIDAS:")
        print(f"{Fore.WHITE}=" * 115)
        header = f"{'ID':<4} | {'FONTE':<12} | {'ATIVO':<12} | {'TF':<5} | {'LINHAS':<10} | {'INÍCIO':<19} | {'FIM':<19} | {'TAMANHO'}"
        print(f"{Fore.YELLOW}{header}")
        print(f"{Fore.WHITE}-" * 115)

        for idx, db in enumerate(dbs):
            # Formatação de datas removendo segundos se necessário ou encurtando
            start = db['start_date'][:19]
            end = db['end_date'][:19]
            row = (f"{idx+1:<4} | {db['source'].upper():<12} | {db['asset'].upper():<12} | "
                   f"{db['timeframe'].upper():<5} | {db['rows']:<10} | {start:<19} | "
                   f"{end:<19} | {db['file_size_kb']} KB")
            print(f"{Fore.WHITE}{row}")

        print(f"{Fore.WHITE}=" * 115 + "\n")    
            
    def do_search(self, arg):
        """
        Busca ativos suportados via fonte específica (Padrão: OpenBB)
        Uso: search [--source FONTE] [--query QUERY] [--exchange EXCHANGE]
        Exemplos:
          search
          search --query "Apple"
          search --exchange NYSE
          search --source dukascopy --query "bitcoin"
        """
        if not arg.strip():
            self.server.show_search_summary()
            return

        parser = argparse.ArgumentParser(prog='search', description='Busca ativos', exit_on_error=False)
        parser.add_argument('--source', type=str, default='openbb', help='Fonte de busca (openbb ou dukascopy)')
        parser.add_argument('--query', type=str, help='Palavra-chave para pesquisar')
        parser.add_argument('--exchange', type=str, help='Exchange (bolsa) para filtrar (Apenas OpenBB)')
        
        try:
            # shlex.split lida bem com aspas ("Apple Inc")
            args_parsed = parser.parse_args(shlex.split(arg))
            self.server.search_assets(
                source=args_parsed.source,
                query=args_parsed.query, 
                exchange=args_parsed.exchange
            )
        except SystemExit:
            pass # argparse já printou o help
        except Exception as e:
            print(f"{Fore.RED}Erro interno no Parse: {e}")
            
    def do_resample(self, arg):
        """
        Converte uma base M1 existente para outro(s) timeframe(s). 
        Uso: resample <fonte> <ativo1,ativo2,...> <novo_timeframe1,novo_timeframe2,...>
        
        Timeframes suportados: M2, M5, M10, M15, M30, H1, H2, H3, H4, H6, D1, W1
        Exemplo: resample OPENBB AAPL,MSFT H1,H2
        """
        args = arg.split()
        if len(args) != 3:
             print("Erro: Uso correto: resample <fonte> <ativos,separados,por,virgula> <novos_timeframes,separados>")
             return
             
        source = args[0]
        assets = [a.strip() for a in args[1].split(',') if a.strip()]
        target_timeframes = [tf.strip() for tf in args[2].split(',') if tf.strip()]
        
        for asset in assets:
            for tf in target_timeframes:
                try:
                    self.server.resample_database(source, asset, tf)
                except Exception as e:
                    print(f"{Fore.RED}Erro ao converter {asset} para {tf}: {e}")

    def do_quality(self, arg):
        """
        Realiza testes de qualidade e retorna a quantidade de erros em uma base de dados.
        Uso: quality <fonte> <ativo1,ativo2,...> [timeframe]
        Exemplo: quality OPENBB AAPL,MSFT M1
        
        Análises realizadas:
        - Relações OHLC: Garante lógicas básicas (High >= Low, High >= Open/Close, Low <= Open/Close).
        - Duplicatas: Detecta registros com o mesmo timestamp exato (erros de importação).
        - Ordenação Temporal: Confirma que os timestamps estão em ordem crescente e não voltam no tempo.
        - Gaps: Quantifica ausência prolongada (buracos) de dados baseando-se na frequência da base.
        """
        args = arg.split()
        if len(args) not in [2, 3]:
            print("Erro: Uso correto: quality <fonte> <ativos,separados,por,virgula> [timeframe=M1]")
            return

        source = args[0]
        assets = [a.strip() for a in args[1].split(',') if a.strip()]
        timeframe = args[2] if len(args) == 3 else "M1"
        
        for asset in assets:
            try:
                self.server.check_quality(source, asset, timeframe)
            except Exception as e:
                print(f"{Fore.RED}Erro ao analisar qualidade de {asset}: {e}")
        

    def do_exit(self, arg):
        """Sair do servidor"""
        print("Encerrando servidor...")
        return True
        
    def do_quit(self, arg):
        return self.do_exit(arg)
