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
 {Fore.YELLOW}● INTERACTIVE MODE ●{Fore.WHITE}

 {Style.BRIGHT}COMMANDS:{Style.NORMAL}
 {Fore.CYAN}download{Fore.WHITE} | {Fore.CYAN}update{Fore.WHITE} | {Fore.CYAN}search{Fore.WHITE} | {Fore.CYAN}list{Fore.WHITE} | {Fore.CYAN}resample{Fore.WHITE} | {Fore.CYAN}delete{Fore.WHITE} | {Fore.CYAN}quality{Fore.WHITE}
        
 {Fore.WHITE}Digite {Fore.YELLOW}'help'{Fore.WHITE} para o manual completo ou {Fore.YELLOW}'exit'{Fore.WHITE} para sair.
════════════════════════════════════════════════════════════════════════
"""
    prompt = f"{Fore.GREEN}DataManager> {Style.RESET_ALL}"

    def do_help(self, arg):
        """Custom help command to show all commands in a structured way."""
        if arg:
            # If the user asks for help on a specific command, use default cmd behavior
            super().do_help(arg)
        else:
            print(self.intro)
            print(f"{Fore.CYAN}{Style.BRIGHT}--- COMMAND GUIDE ---{Style.RESET_ALL}\n")
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
        Download new data. Usage: download <fonte> <ativo1,ativo2,...> [start_date] [end_date] [-timeframe tf1,tf2,...]
        Examples:
          download OPENBB AAPL,MSFT 2023-01-01 2024-01-01
          download DUKASCOPY EURUSD,GBPUSD (downloads full history)
          download DUKASCOPY EURUSD -timeframe M15,H1,D1
        """
        args = arg.split()
        
        target_timeframes = []
        if "-timeframe" in args:
            idx = args.index("-timeframe")
            if idx + 1 < len(args):
                target_timeframes = [tf.strip() for tf in args[idx+1].split(',') if tf.strip()]
            args = args[:idx] + args[idx+2:]

        if len(args) not in [2, 3, 4]:
            print("Error: Correct usage: download <fonte> <assets,comma,separated> [start_date] [end_date] [-timeframe tf1,tf2,...]")
            return
            
        source = args[0]
        assets = [a.strip() for a in args[1].split(',') if a.strip()]
        
        try:
            # Set date defaults if the user omits them (Download Full History)
            if len(args) >= 3:
                start_date = parse(args[2])
            else:
                # Go back to the distant past
                start_date = datetime(2000, 1, 1)
                print(f"{Fore.YELLOW}Start date omitted. Starting full history search from {start_date.date()}...")
                
            if len(args) == 4:
                end_date = parse(args[3])
            else:
                end_date = datetime.now()
                if len(args) < 4:
                    print(f"{Fore.YELLOW}End date omitted. Going up to the current date ({end_date.date()}).")

            for asset in assets:
                try:
                    self.server.download_data(source, asset, start_date, end_date)
                    for tf in target_timeframes:
                        self.server.resample_database(source, asset, tf)
                except Exception as e:
                    print(f"{Fore.RED}Error downloading/resampling {asset}: {e}")
        except Exception as e:
            print(f"{Fore.RED}Error in download dates: {e}")

    def do_update(self, arg):
        """
        Updates an existing database. Uso: update <fonte> <ativo1,ativo2,...> [timeframe]
        Exemplo: update OPENBB AAPL,MSFT
        Exemplo: update OPENBB AAPL,MSFT H1
        Special command: update all (Updates all M1 and resamples to higher TFs)
        """
        args = arg.split()
        
        if len(args) == 1 and args[0].lower() == "all":
            self.server.update_all_databases()
            return

        if len(args) not in [2, 3]:
            print("Error: Correct usage: update <fonte> <assets,comma,separated> [timeframe=M1] ou update all")
            return
            
        source = args[0]
        assets = [a.strip() for a in args[1].split(',') if a.strip()]
        timeframe = args[2] if len(args) == 3 else "M1"
        
        for asset in assets:
            try:
                self.server.update_data(source, asset, timeframe)
            except Exception as e:
                print(f"{Fore.RED}Error updating {asset}: {e}")

    def do_delete(self, arg):
        """
        Delete database(s). Uso: delete <fonte> <assets,comma,separated> [timeframe]
                                       delete all
        Examples: 
          delete OPENBB AAPL,MSFT M1
          delete dukascopy eurusd
          delete all
        """
        args = arg.split()
        if len(args) == 1 and args[0].lower() == 'all':
            confirm = input(f"{Fore.RED}WARNING: You are about to delete ALL databases from all sources. Continue? (y/N): {Style.RESET_ALL}")
            if confirm.lower() == 'y':
                self.server.delete_all_databases()
            else:
                print("Operation cancelled.")
            return

        if len(args) < 2 or len(args) > 3:
            print("Error: Correct usage: delete <fonte> <assets,comma,separated> [timeframe] ou delete all")
            return
            
        source = args[0]
        assets = [a.strip() for a in args[1].split(',') if a.strip()]
        tf = args[2] if len(args) == 3 else None
        
        for asset in assets:
            try:
                self.server.delete_database(source, asset, tf)
            except Exception as e:
                print(f"{Fore.RED}Error deleting {asset}: {e}")

    def do_info(self, arg):
        """
        Shows info about a database. Uso: info <fonte> <ativo> <timeframe>
        """
        args = arg.split()
        if len(args) != 3:
             print("Error: Correct usage: info <fonte> <ativo> <timeframe>")
             return
             
        info = self.server.info(args[0], args[1], args[2])
        for k, v in info.items():
             print(f"{k.capitalize()}: {v}")

    def do_list(self, arg):
        """Lists all saved databases with technical details. Uso: list"""
        dbs = self.server.list_all()
        if not dbs:
            print(f"{Fore.YELLOW}No databases found on disk.")
            return

        print(f"\n{Fore.CYAN}{Style.BRIGHT}PERSISTED DATABASES:")
        print(f"{Fore.WHITE}=" * 115)
        header = f"{'ID':<4} | {'SOURCE':<12} | {'ASSET':<12} | {'TF':<5} | {'LINHAS':<10} | {'START':<19} | {'END':<19} | {'SIZE'}"
        print(f"{Fore.YELLOW}{header}")
        print(f"{Fore.WHITE}-" * 115)

        for idx, db in enumerate(dbs):
            # Date formatting, removing seconds if necessary
            start = db['start_date'][:19]
            end = db['end_date'][:19]
            row = (f"{idx+1:<4} | {db['source'].upper():<12} | {db['asset'].upper():<12} | "
                   f"{db['timeframe'].upper():<5} | {db['rows']:<10} | {start:<19} | "
                   f"{end:<19} | {db['file_size_kb']} KB")
            print(f"{Fore.WHITE}{row}")

        print(f"{Fore.WHITE}=" * 115)
        print(f"{Fore.CYAN}Tip: Use 'rebuild' command to resync this list if you manually changed files.\n")
            
    def do_rebuild(self, arg):
        """Rebuilds the database catalog index. Usage: rebuild"""
        print(f"{Fore.YELLOW}Rebuilding catalog. This might take a few seconds...")
        result = self.server.storage.rebuild_catalog()
        count = result.get('count', 0)
        print(f"{Fore.GREEN}✓ Catalog rebuilt successfully! ({count} databases indexed)\n")
            
    def do_search(self, arg):
        """
        Search supported assets via specific source (Default: OpenBB)
        Uso: search [--source FONTE] [--query QUERY] [--exchange EXCHANGE]
        Examples:
          search
          search --query "Apple"
          search --exchange NYSE
          search --source dukascopy --query "bitcoin"
        """
        if not arg.strip():
            self.server.show_search_summary()
            return

        parser = argparse.ArgumentParser(prog='search', description='Search assets', exit_on_error=False)
        parser.add_argument('--source', type=str, default='openbb', help='Search source (openbb ou dukascopy)')
        parser.add_argument('--query', type=str, help='Keyword to search')
        parser.add_argument('--exchange', type=str, help='Exchange to filter (Apenas OpenBB)')
        
        try:
            # shlex.split handles quotes well ("Apple Inc")
            args_parsed = parser.parse_args(shlex.split(arg))
            self.server.search_assets(
                source=args_parsed.source,
                query=args_parsed.query, 
                exchange=args_parsed.exchange
            )
        except SystemExit:
            pass # argparse already printed help
        except Exception as e:
            print(f"{Fore.RED}Internal parse error: {e}")
            
    def do_resample(self, arg):
        """
        Converts an existing M1 database to outro(s) timeframe(s). 
        Uso: resample <fonte> <ativo1,ativo2,...> <novo_timeframe1,novo_timeframe2,...>
        
        Supported timeframes: M2, M5, M10, M15, M30, H1, H2, H3, H4, H6, D1, W1
        Exemplo: resample OPENBB AAPL,MSFT H1,H2
        """
        args = arg.split()
        if len(args) != 3:
             print("Error: Correct usage: resample <fonte> <assets,comma,separated> <novos_timeframes,separados>")
             return
             
        source = args[0]
        assets = [a.strip() for a in args[1].split(',') if a.strip()]
        target_timeframes = [tf.strip() for tf in args[2].split(',') if tf.strip()]
        
        for asset in assets:
            for tf in target_timeframes:
                try:
                    self.server.resample_database(source, asset, tf)
                except Exception as e:
                    print(f"{Fore.RED}Error converting {asset} para {tf}: {e}")

    def do_quality(self, arg):
        """
        Performs quality tests and returns error count in a database.
        Uso: quality <fonte> <ativo1,ativo2,...> [timeframe]
        Exemplo: quality OPENBB AAPL,MSFT M1
        
        Analyses performed:
        - Relações OHLC: Ensures basic logic (High >= Low, High >= Open/Close, Low <= Open/Close).
        - Duplicatas: Detects records with exact same timestamp (erros de importação).
        - Ordenação Temporal: Confirms timestamps are in chronological order.
        - Gaps: Quantifies prolonged absence (gaps) based on frequency.
        """
        args = arg.split()
        if len(args) not in [2, 3]:
            print("Error: Correct usage: quality <fonte> <assets,comma,separated> [timeframe=M1]")
            return

        source = args[0]
        assets = [a.strip() for a in args[1].split(',') if a.strip()]
        timeframe = args[2] if len(args) == 3 else "M1"
        
        for asset in assets:
            try:
                self.server.check_quality(source, asset, timeframe)
            except Exception as e:
                print(f"{Fore.RED}Error analyzing quality of {asset}: {e}")
        

    def do_exit(self, arg):
        """Exit server"""
        print("Shutting down server...")
        return True
        
    def do_quit(self, arg):
        return self.do_exit(arg)
