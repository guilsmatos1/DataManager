import argparse
import cmd
import logging
import shlex
from datetime import datetime

from colorama import Fore, Style, init
from dateutil.parser import parse

from datamanager import __version__
from datamanager.services.manager import DataManager
from datamanager.services.scheduler import SchedulerService

init(autoreset=True)

logger = logging.getLogger("DataManager")


class DataManagerCLI(cmd.Cmd):
    intro = rf"""
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
                {Fore.CYAN}{Style.BRIGHT}DataManager{Fore.WHITE} - {Fore.GREEN}v{__version__}{Fore.WHITE}
════════════════════════════════════════════════════════════════════════
 {Fore.YELLOW}● INTERACTIVE MODE ●{Fore.WHITE}

 {Style.BRIGHT}COMMANDS:{Style.NORMAL}
 {Fore.CYAN}download{Fore.WHITE} | {Fore.CYAN}update{Fore.WHITE} | {Fore.CYAN}search{Fore.WHITE} | {Fore.CYAN}list{Fore.WHITE} | {Fore.CYAN}resample{Fore.WHITE} | {Fore.CYAN}delete{Fore.WHITE} | {Fore.CYAN}quality{Fore.WHITE} | {Fore.CYAN}schedule{Fore.WHITE} | {Fore.CYAN}info{Fore.WHITE} | {Fore.CYAN}rebuild{Fore.WHITE}

 {Fore.WHITE}Type {Fore.YELLOW}'help'{Fore.WHITE} for the full manual or {Fore.YELLOW}'exit'{Fore.WHITE} to quit.
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
        self.scheduler = SchedulerService(self.server)
        self.scheduler.start()

    def do_download(self, arg):
        """
        Download new data. Usage: download <source> <asset1,asset2,...> [start_date] [end_date] [-timeframe tf1,tf2,...]
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
                target_timeframes = [tf.strip() for tf in args[idx + 1].split(",") if tf.strip()]
            args = args[:idx] + args[idx + 2 :]

        if len(args) not in [2, 3, 4]:
            logger.error(
                "Correct usage: download <source> <assets,comma,separated> [start_date] [end_date] [-timeframe tf1,tf2,...]"
            )
            return

        source = args[0]
        assets = [a.strip() for a in args[1].split(",") if a.strip()]

        try:
            # Set date defaults if the user omits them (Download Full History)
            if len(args) >= 3:
                start_date = parse(args[2])
            else:
                # Go back to the distant past
                start_date = datetime(2000, 1, 1)
                logger.info(f"Start date omitted. Starting full history search from {start_date.date()}...")

            if len(args) == 4:
                end_date = parse(args[3])
            else:
                end_date = datetime.now()
                if len(args) < 4:
                    logger.info(f"End date omitted. Going up to the current date ({end_date.date()}).")

            for asset in assets:
                try:
                    self.server.download_data(source, asset, start_date, end_date)
                    for tf in target_timeframes:
                        self.server.resample_database(source, asset, tf)
                except Exception as e:
                    logger.error(f"Error downloading/resampling {asset}: {e}")
        except Exception as e:
            logger.error(f"Error in download dates: {e}")

    def do_update(self, arg):
        """
        Updates an existing M1 database with new data, then rebuilds the requested timeframe.
        M1 is always updated first as the source of truth. If a higher timeframe is given,
        it is fully rebuilt from the updated M1 to guarantee consistency.
        Usage: update <source> <asset1,asset2,...> [timeframe]
        Example: update OPENBB AAPL,MSFT          (updates M1)
        Example: update DUKASCOPY EURUSD H1        (updates M1 then rebuilds H1)
        Special command: update all               (updates all M1s and reconstructs higher TFs)
        """
        args = arg.split()

        if len(args) == 1 and args[0].lower() == "all":
            self.server.update_all_databases()
            return

        if len(args) not in [2, 3]:
            logger.error("Correct usage: update <source> <assets,comma,separated> [timeframe=M1] or update all")
            return

        source = args[0]
        assets = [a.strip() for a in args[1].split(",") if a.strip()]
        timeframe = args[2] if len(args) == 3 else "M1"

        for asset in assets:
            try:
                self.server.update_data(source, asset, timeframe)
            except Exception as e:
                logger.error(f"Error updating {asset}: {e}")

    def do_delete(self, arg):
        """
        Delete database(s). Usage: delete <source> <assets,comma,separated> [timeframe]
                                    delete all
        Examples:
          delete OPENBB AAPL,MSFT M1
          delete dukascopy eurusd
          delete all
        """
        args = arg.split()
        if len(args) == 1 and args[0].lower() == "all":
            confirm = input(
                f"{Fore.RED}WARNING: You are about to delete ALL databases from all sources. Continue? (y/N): {Style.RESET_ALL}"
            )
            if confirm.lower() == "y":
                self.server.delete_all_databases()
            else:
                logger.info("Operation cancelled.")
            return

        if len(args) < 2 or len(args) > 3:
            logger.error("Correct usage: delete <source> <assets,comma,separated> [timeframe] or delete all")
            return

        source = args[0]
        assets = [a.strip() for a in args[1].split(",") if a.strip()]
        tf = args[2] if len(args) == 3 else None

        for asset in assets:
            try:
                self.server.delete_database(source, asset, tf)
            except Exception as e:
                logger.error(f"Error deleting {asset}: {e}")

    def do_info(self, arg):
        """
        Shows info about a database. Usage: info <source> <asset> <timeframe>
        """
        args = arg.split()
        if len(args) != 3:
            logger.error("Correct usage: info <source> <asset> <timeframe>")
            return

        info = self.server.info(args[0], args[1], args[2])
        if info.get("status") == "Not Found":
            logger.warning(f"Database not found: {args[1].upper()} ({args[2].upper()}) from {args[0].upper()}")
            return

        print(f"\n{Fore.CYAN}{Style.BRIGHT}DATABASE INFO:")
        print(f"{Fore.WHITE}{'=' * 50}")
        labels = {
            "source": ("Source", str),
            "asset": ("Asset", str),
            "timeframe": ("Timeframe", str),
            "rows": ("Rows", lambda v: f"{v:,}"),
            "start_date": ("Start Date", str),
            "end_date": ("End Date", str),
            "file_size_kb": ("File Size", lambda v: f"{v} KB"),
        }
        for key, (label, fmt) in labels.items():
            if key in info:
                print(f"  {Fore.YELLOW}{label:<12}{Fore.WHITE}{fmt(info[key])}")
        print(f"{Fore.WHITE}{'=' * 50}\n")

    def do_list(self, arg):
        """Lists all saved databases with technical details. Usage: list"""
        dbs = self.server.list_all()
        if not dbs:
            logger.warning("No databases found on disk.")
            return

        print(f"\n{Fore.CYAN}{Style.BRIGHT}PERSISTED DATABASES:")
        print(f"{Fore.WHITE}=" * 95)
        header = f"{'ID':<3} | {'SOURCE':<10} | {'ASSET':<8} | {'TF':<4} | {'ROWS':<8} | {'START':<16} | {'END':<16} | {'SIZE'}"
        print(f"{Fore.YELLOW}{header}")
        print(f"{Fore.WHITE}-" * 95)

        for idx, db in enumerate(dbs):
            # Date formatting, removing seconds if necessary
            start = db["start_date"][:16]
            end = db["end_date"][:16]
            row = (
                f"{idx + 1:<3} | {db['source'].upper()[:10]:<10} | {db['asset'].upper()[:8]:<8} | "
                f"{db['timeframe'].upper()[:4]:<4} | {db['rows']:<8} | {start:<16} | "
                f"{end:<16} | {db['file_size_kb']} KB"
            )
            print(f"{Fore.WHITE}{row}")

        print(f"{Fore.WHITE}=" * 95)
        print(f"{Fore.CYAN}Tip: Use 'rebuild' command to resync this list if you manually changed files.\n")

    def do_rebuild(self, arg):
        """Rebuilds the database catalog index. Usage: rebuild"""
        logger.info("Rebuilding catalog. This might take a few seconds...")
        result = self.server.storage.rebuild_catalog()
        count = result.get("count", 0)
        logger.info(f"✓ Catalog rebuilt successfully! ({count} databases indexed)")

    def do_search(self, arg):
        """
        Search supported assets via specific source (Default: OpenBB)
        Usage: search [--source SOURCE] [--query QUERY] [--exchange EXCHANGE]
        Examples:
          search
          search --query \"Apple\"
          search --exchange NYSE
          search --source dukascopy --query \"bitcoin\"
        """
        if not arg.strip():
            self.server.show_search_summary()
            return

        parser = argparse.ArgumentParser(prog="search", description="Search assets", exit_on_error=False)
        parser.add_argument("--source", type=str, default="openbb", help="Search source (openbb or dukascopy)")
        parser.add_argument("--query", type=str, help="Keyword to search")
        parser.add_argument("--exchange", type=str, help="Exchange to filter (OpenBB only)")

        try:
            args_parsed = parser.parse_args(shlex.split(arg))
            df = self.server.search_assets(
                source=args_parsed.source, query=args_parsed.query, exchange=args_parsed.exchange
            )

            if df is None or df.empty:
                return

            print(f"\nFound {len(df)} results. Displaying the first 20:")
            source_key = args_parsed.source.upper()

            if source_key == "OPENBB":
                print(f"{Fore.WHITE}{'=' * 95}")
                header = f"{'TICKER':<15} | {'COMPANY NAME':<55} | {'EXCHANGE':<15}"
                print(f"{Fore.YELLOW}{header}")
                print(f"{Fore.WHITE}{'-' * 95}")
                df = df.reset_index().fillna("")
                for _, row in df.head(20).iterrows():
                    symbol = str(row.get("symbol", ""))
                    name = str(row.get("name", ""))[:53]
                    exc = str(row.get("exchange", ""))
                    print(f"{Fore.WHITE}{symbol:<15} | {name:<55} | {exc:<15}")
                print(f"{Fore.WHITE}{'=' * 95}\n")

            elif source_key == "DUKASCOPY":
                print(f"{Fore.WHITE}{'=' * 105}")
                header = f"{'TICKER':<20} | {'ALIAS':<15} | {'ASSET NAME':<50} | {'CATEGORY':<10}"
                print(f"{Fore.YELLOW}{header}")
                print(f"{Fore.WHITE}{'-' * 105}")
                df = df.fillna("")
                for _, row in df.head(20).iterrows():
                    print(
                        f"{Fore.WHITE}{str(row['ticker']):<20} | {str(row['alias']):<15} | {str(row['nome_do_ativo'])[:48]:<50} | {str(row['categoria']):<10}"  # noqa: E501
                    )
                print(f"{Fore.WHITE}{'=' * 105}\n")

            else:
                # Generic output for new fetchers (like CCXT)
                print(f"{Fore.WHITE}{df.head(20).to_string()}\n")

        except SystemExit:
            pass
        except Exception as e:
            logger.error(f"Internal parse error: {e}")

    def do_resample(self, arg):
        """
        Converts an existing M1 database to other timeframe(s).
        Usage: resample <source> <asset1,asset2,...> <new_timeframe1,new_timeframe2,...>

        Supported timeframes: M2, M5, M10, M15, M30, H1, H2, H3, H4, H6, D1, W1
        Example: resample OPENBB AAPL,MSFT H1,H2
        """
        args = arg.split()
        if len(args) != 3:
            logger.error("Correct usage: resample <source> <assets,comma,separated> <new_timeframes,separated>")
            return

        source = args[0]
        assets = [a.strip() for a in args[1].split(",") if a.strip()]
        target_timeframes = [tf.strip() for tf in args[2].split(",") if tf.strip()]

        for asset in assets:
            for tf in target_timeframes:
                try:
                    self.server.resample_database(source, asset, tf)
                except Exception as e:
                    logger.error(f"Error converting {asset} to {tf}: {e}")

    def do_quality(self, arg):
        """
        Performs quality tests and returns error count in a database.
        Usage: quality <source> <asset1,asset2,...> [timeframe]
        Example: quality OPENBB AAPL,MSFT M1

        Analyses performed:
        - OHLC Relations: Ensures basic logic (High >= Low, High >= Open/Close, Low <= Open/Close).
        - Duplicates: Detects records with exact same timestamp (import errors).
        - Temporal Ordering: Confirms timestamps are in chronological order.
        - Gaps: Quantifies prolonged absence (gaps) based on frequency.
        """
        args = arg.split()
        if len(args) not in [2, 3]:
            logger.error("Correct usage: quality <source> <assets,comma,separated> [timeframe=M1]")
            return

        source = args[0]
        assets = [a.strip() for a in args[1].split(",") if a.strip()]
        timeframe = args[2] if len(args) == 3 else "M1"

        for asset in assets:
            try:
                self.server.check_quality(source, asset, timeframe)
            except Exception as e:
                logger.error(f"Error analyzing quality of {asset}: {e}")

    def do_schedule(self, arg):
        """
        Manage scheduled automatic updates.
        Usage:
          schedule add <source> <asset> [timeframe] --cron "0 */4 * * *"
          schedule add <source> <asset> [timeframe] --interval <minutes>
          schedule list
          schedule remove <job_id>
        Examples:
          schedule add DUKASCOPY EURUSD M1 --interval 60
          schedule add OPENBB AAPL H1 --cron "0 9 * * 1-5"
          schedule list
          schedule remove <job_id>
        """
        parser = argparse.ArgumentParser(prog="schedule", exit_on_error=False)
        subparsers = parser.add_subparsers(dest="subcmd")

        add_p = subparsers.add_parser("add")
        add_p.add_argument("source")
        add_p.add_argument("asset")
        add_p.add_argument("timeframe", nargs="?", default="M1")
        add_p.add_argument("--cron", type=str, default=None)
        add_p.add_argument("--interval", type=int, default=None, dest="interval_minutes")

        subparsers.add_parser("list")

        rem_p = subparsers.add_parser("remove")
        rem_p.add_argument("job_id")

        try:
            parsed = parser.parse_args(shlex.split(arg))
        except SystemExit:
            return
        except Exception as e:
            logger.error(f"Parse error: {e}")
            return

        if parsed.subcmd == "add":
            if not parsed.cron and not parsed.interval_minutes:
                logger.error("Provide --cron or --interval.")
                return
            try:
                job = self.scheduler.add_job(
                    source=parsed.source,
                    asset=parsed.asset,
                    timeframe=parsed.timeframe,
                    cron=parsed.cron,
                    interval_minutes=parsed.interval_minutes,
                )
                logger.info(f"Job scheduled: {job['job_id']} | next run: {job['next_run']}")
            except Exception as e:
                logger.error(f"Failed to schedule job: {e}")

        elif parsed.subcmd == "list":
            jobs = self.scheduler.list_jobs()
            if not jobs:
                logger.info("No scheduled jobs.")
                return
            print(f"\n{'JOB ID':<38} | {'SOURCE':<10} | {'ASSET':<10} | {'TF':<4} | {'TRIGGER':<20} | NEXT RUN")
            print("-" * 110)
            for j in jobs:
                print(
                    f"{j['job_id']:<38} | {j['source']:<10} | {j['asset']:<10} | {j['timeframe']:<4} | {j['trigger']:<20} | {j['next_run']}"
                )

        elif parsed.subcmd == "remove":
            if self.scheduler.remove_job(parsed.job_id):
                logger.info(f"Job {parsed.job_id} removed.")
            else:
                logger.warning(f"Job {parsed.job_id} not found.")
        else:
            logger.error("Unknown subcommand. Use: add | list | remove")

    def do_exit(self, arg):
        """Exit server"""
        logger.info("Shutting down server...")
        self.scheduler.shutdown()
        return True

    def do_quit(self, arg):
        return self.do_exit(arg)
