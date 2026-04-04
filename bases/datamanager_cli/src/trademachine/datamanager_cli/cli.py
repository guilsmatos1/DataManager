import argparse
import cmd
import logging
import shlex
import shutil
from collections.abc import Callable
from datetime import UTC, datetime

from colorama import Fore, Style, init
from dateutil.parser import parse  # type: ignore[import-untyped]
from trademachine.core.interactive import (
    create_prompt_session,
    interactive_history_path,
    read_interactive_input,
)
from trademachine.core.logger import LOGGER_NAME, setup_logger

__version__ = "0.1.0"
from trademachine.datamanager.services.manager import DataManager
from trademachine.datamanager.services.scheduler import SchedulerService
from trademachine.datamanager.services.series_manager import SeriesManager

init(autoreset=True)

logger = logging.getLogger(LOGGER_NAME)


class DataManagerCLI(cmd.Cmd):
    intro = ""
    prompt = f"{Fore.GREEN}DataManager> {Style.RESET_ALL}"

    @property
    def terminal_width(self) -> int:
        """Returns the current terminal width."""
        return shutil.get_terminal_size((80, 20)).columns

    def _update_intro(self):
        """Generates a dynamic intro based on terminal width."""
        width = self.terminal_width
        sep = "═" * width

        # Decorated title
        title = f" DATAMANAGER v{__version__} "
        padding = max(0, (width - len(title)) // 2)
        decorated_title = f"{Fore.CYAN}{Style.BRIGHT}{'─' * padding}{Fore.WHITE}{title}{Fore.CYAN}{'─' * (width - padding - len(title))}{Style.RESET_ALL}"

        self.intro = f"""
{decorated_title}
{Fore.WHITE}{sep}
 {Fore.WHITE}Centralized financial data management system for OHLCV and economic series. Efficiently fetch, store, update, and resample market data in TimescaleDB.

 {Fore.YELLOW}● INTERACTIVE MODE ●{Fore.WHITE}

 {Fore.WHITE}Type {Fore.YELLOW}'help'{Fore.WHITE} for the full manual or {Fore.YELLOW}'exit'{Fore.WHITE} to quit.
{Fore.WHITE}{sep}
"""

    @staticmethod
    def _interactive_history_path() -> str:
        """Returns the shell history file used by the interactive prompt."""
        return interactive_history_path("datamanager")  # type: ignore[no-any-return]

    def _create_prompt_session(self):
        """Builds a prompt_toolkit session when available."""
        return create_prompt_session(self._interactive_history_path(), logger=logger)

    def _read_interactive_input(self, prompt_session) -> str:
        """Reads one interactive command, using history-capable prompt when possible."""
        return read_interactive_input(prompt_session, self.prompt)  # type: ignore[no-any-return]

    @staticmethod
    def _is_series_source(source: str) -> bool:
        return source.lower() == "fred"

    def do_help(self, arg):
        """Custom help command to show all commands in a structured way."""
        if arg:
            # If the user asks for help on a specific command, use default cmd behavior
            super().do_help(arg)
        else:
            self._update_intro()
            print(self.intro)
            print(f"{Fore.CYAN}{Style.BRIGHT}--- COMMAND GUIDE ---{Style.RESET_ALL}\n")
            for attr in dir(self):
                if attr.startswith("do_") and attr not in [
                    "do_EOF",
                    "do_quit",
                    "do_help",
                ]:
                    cmd_name = attr[3:]
                    doc = getattr(self, attr).__doc__
                    print(f"{Fore.YELLOW}● {cmd_name.upper()}{Style.RESET_ALL}")
                    if doc:
                        cleaned_doc = "\n".join(
                            "  " + line.strip() for line in doc.strip().split("\n")
                        )
                        print(f"{Fore.WHITE}{cleaned_doc}\n")

    def __init__(self):
        super().__init__()
        self._update_intro()
        try:
            self.server = DataManager()
            # Win #5: Quick health check
            self.server.storage.check_connection()
        except Exception as e:
            print(
                f"\n{Fore.RED}{Style.BRIGHT}ERROR: Could not connect to the Database."
            )
            print(
                f"{Fore.WHITE}Ensure your TimescaleDB (Postgres) is running and your .env credentials are correct."
            )
            print(f"{Fore.YELLOW}Details: {e}\n")
            import sys

            sys.exit(1)

        self.scheduler = SchedulerService(self.server)
        self.scheduler.start()
        self.series_server = SeriesManager()

    def emptyline(self):
        """Overrides cmd.Cmd default behavior, which repeats the last command."""
        pass

    def cmdloop(self, intro=None):
        """Runs the interactive loop with persistent command history support."""
        if intro is not None:
            self.intro = intro

        self.preloop()
        if self.intro:
            self.stdout.write(str(self.intro))

        prompt_session = self._create_prompt_session()
        stop = None
        while not stop:
            if self.cmdqueue:
                line = self.cmdqueue.pop(0)
            else:
                try:
                    line = self._read_interactive_input(prompt_session)
                except EOFError:
                    self.stdout.write("\n")
                    line = "quit"
                except KeyboardInterrupt:
                    self.stdout.write("\n")
                    continue

            line = self.precmd(line)
            stop = self.onecmd(line)
            stop = self.postcmd(stop, line)

        self.postloop()

    def do_download(self, arg):
        """
        Download new data. Usage: download <source> <asset1,asset2,...> [start_date] [end_date] [-timeframe tf1,tf2,...]
        Examples:
          download OPENBB AAPL,MSFT 2023-01-01 2024-01-01
          download DUKASCOPY EURUSD,GBPUSD (downloads full history)
          download DUKASCOPY EURUSD -timeframe M15,H1,D1
          download FRED CPIAUCSL 2010-01-01 2024-01-01 --frequency m
        """
        args = shlex.split(arg)

        if args and self._is_series_source(args[0]):
            parser = argparse.ArgumentParser(prog="download", exit_on_error=False)
            parser.add_argument("source")
            parser.add_argument("series_id")
            parser.add_argument("start_date", nargs="?", default=None)
            parser.add_argument("end_date", nargs="?", default=None)
            parser.add_argument("--frequency", type=str, default=None)

            try:
                args_parsed = parser.parse_args(args)
                start_date = (
                    parse(args_parsed.start_date) if args_parsed.start_date else None
                )
                end_date = parse(args_parsed.end_date) if args_parsed.end_date else None
                result = self.series_server.download_series(
                    args_parsed.source,
                    args_parsed.series_id,
                    start_date=start_date.isoformat() if start_date else None,
                    end_date=end_date.isoformat() if end_date else None,
                    frequency=args_parsed.frequency,
                )
                logger.info(
                    "FRED download started/completed: "
                    f"{result.get('series_id', args_parsed.series_id)}"
                )
            except SystemExit:
                pass
            except Exception as e:
                logger.error(f"Error downloading FRED series: {e}")
            return

        target_timeframes = []
        if "-timeframe" in args:
            idx = args.index("-timeframe")
            if idx + 1 < len(args):
                target_timeframes = [
                    tf.strip() for tf in args[idx + 1].split(",") if tf.strip()
                ]
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
                logger.info(
                    f"Start date omitted. Starting full history search from {start_date.date()}..."
                )

            if len(args) == 4:
                end_date = parse(args[3])
            else:
                end_date = datetime.now(UTC).replace(tzinfo=None)
                if len(args) < 4:
                    logger.info(
                        f"End date omitted. Going up to the current date ({end_date.date()})."
                    )

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
        Example: update FRED CPIAUCSL --lookback 30D --frequency m
        Special command: update all               (updates all M1s and reconstructs higher TFs)
        """
        args = shlex.split(arg)

        if len(args) == 1 and args[0].lower() == "all":
            self.server.update_all_databases()
            return

        if args and self._is_series_source(args[0]):
            parser = argparse.ArgumentParser(prog="update", exit_on_error=False)
            parser.add_argument("source")
            parser.add_argument("series_id")
            parser.add_argument("--lookback", dest="lookback_period", default=None)
            parser.add_argument("--frequency", type=str, default=None)

            try:
                args_parsed = parser.parse_args(args)
                result = self.series_server.update_series(
                    args_parsed.source,
                    args_parsed.series_id,
                    lookback_period=args_parsed.lookback_period,
                    frequency=args_parsed.frequency,
                )
                logger.info(
                    "FRED update started/completed: "
                    f"{result.get('series_id', args_parsed.series_id)}"
                )
            except SystemExit:
                pass
            except Exception as e:
                logger.error(f"Error updating FRED series: {e}")
            return

        if len(args) not in [2, 3]:
            logger.error(
                "Correct usage: update <source> <assets,comma,separated> [timeframe=M1] or update all"
            )
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
                                    delete fred <series_id>
                                    delete all
        Examples:
          delete OPENBB AAPL,MSFT M1
          delete FRED CPIAUCSL
          delete dukascopy eurusd
          delete all
        """
        args = shlex.split(arg)
        if len(args) == 1 and args[0].lower() == "all":
            confirm = input(
                f"{Fore.RED}WARNING: You are about to delete ALL databases from all sources. Continue? (y/N): {Style.RESET_ALL}"
            )
            if confirm.lower() == "y":
                self.server.delete_all_databases()
            else:
                logger.info("Operation cancelled.")
            return

        if len(args) == 2 and self._is_series_source(args[0]):
            try:
                if self.series_server.delete_series(args[0], args[1]):
                    logger.info(f"Deleted FRED series: {args[1]}")
                else:
                    logger.warning(f"Series not found: {args[1]}")
            except Exception as e:
                logger.error(f"Error deleting FRED series: {e}")
            return

        if len(args) < 2 or len(args) > 3:
            logger.error(
                "Correct usage: delete <source> <assets,comma,separated> [timeframe] or delete all"
            )
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
        Shows info about a database or FRED series.
        Usage: info <source> <asset> <timeframe>
               info fred <series_id>
        """
        args = shlex.split(arg)
        if len(args) == 2 and self._is_series_source(args[0]):
            info = self.series_server.info_series(args[0], args[1])
            if not info:
                logger.warning(f"Series not found: {args[1].upper()}")
                return

            print(f"\n{Fore.CYAN}{Style.BRIGHT}FRED SERIES INFO:")
            width = self.terminal_width
            print(f"{Fore.WHITE}{'=' * width}")
            labels: dict[str, tuple[str, Callable[[object], str]]] = {
                "source": ("Source", str),
                "series_id": ("Series ID", str),
                "title": ("Title", str),
                "frequency": ("Frequency", str),
                "units": ("Units", str),
                "seasonal_adjustment": ("Seasonal Adj.", str),
                "observation_start": ("Start", str),
                "observation_end": ("End", str),
                "last_updated": ("Last Updated", str),
                "rows": ("Rows", lambda v: f"{v:,}" if isinstance(v, int) else str(v)),
            }
            for key, (label, fmt) in labels.items():
                if key in info:
                    val = fmt(info[key])
                    val_color = (
                        Fore.GREEN
                        if key in ["rows", "series_id", "asset"]
                        else Fore.WHITE
                    )
                    print(f"  {Fore.CYAN}{label:<16} {Fore.WHITE}» {val_color}{val}")
            print(f"{Fore.WHITE}{'=' * width}\n")
            return

        if len(args) != 3:
            logger.error(
                "Correct usage: info <source> <asset> <timeframe> or info fred <series_id>"
            )
            return

        info = self.server.info(args[0], args[1], args[2])
        if info.get("status") == "Not Found":
            logger.warning(
                f"Database not found: {args[1].upper()} ({args[2].upper()}) from {args[0].upper()}"
            )
            return

        print(f"\n{Fore.CYAN}{Style.BRIGHT}DATABASE INFO:")
        width = self.terminal_width
        print(f"{Fore.WHITE}{'=' * width}")
        labels: dict[str, tuple[str, Callable[[object], str]]] = {
            "source": ("Source", str),
            "asset": ("Asset", str),
            "timeframe": ("Timeframe", str),
            "rows": ("Rows", lambda v: f"{v:,}" if isinstance(v, int) else str(v)),
            "start_date": ("Start Date", str),
            "end_date": ("End Date", str),
        }
        for key, (label, fmt) in labels.items():
            if key in info:
                val = fmt(info[key])
                val_color = Fore.GREEN if key in ["rows", "asset"] else Fore.WHITE
                print(f"  {Fore.CYAN}{label:<14} {Fore.WHITE}» {val_color}{val}")
        print(f"{Fore.WHITE}{'=' * width}\n")

    def do_list(self, arg):
        """
        Lists saved databases or FRED series.
        Usage: list
               list --source fred
        """
        if arg.strip():
            parser = argparse.ArgumentParser(prog="list", exit_on_error=False)
            parser.add_argument("--source", type=str, default=None)

            try:
                args_parsed = parser.parse_args(shlex.split(arg))
            except SystemExit:
                return

            if self._is_series_source(args_parsed.source or ""):
                try:
                    items = self.series_server.list_series()
                    if not items:
                        logger.info("No FRED series found.")
                        return

                    width = self.terminal_width
                    print(f"\n{Fore.CYAN}{Style.BRIGHT}FRED SERIES:{Style.RESET_ALL}")
                    print(f"{Fore.WHITE}=" * width)
                    header = f"{'SERIES ID':<18} | {'TITLE':<36} | {'FREQ':<10} | {'ROWS':<8} | {'START':<16} | {'END':<16}"
                    print(f"{Fore.YELLOW}{header}")
                    print(f"{Fore.WHITE}{'-' * width}")
                    for item in items:
                        start = (item.get("observation_start") or "")[:16]
                        end = (item.get("observation_end") or "")[:16]
                        rows = item.get("rows", "N/A")
                        row = (
                            f"{Fore.GREEN}{str(item.get('series_id', '')):<18} {Fore.WHITE}| "
                            f"{Fore.WHITE}{str(item.get('title', ''))[:34]:<36} | "
                            f"{Fore.CYAN}{str(item.get('frequency', '')):<10} {Fore.WHITE}| "
                            f"{Fore.YELLOW}{str(rows):<8} {Fore.WHITE}| "
                            f"{Fore.BLUE}{start:<16} {Fore.WHITE}| "
                            f"{Fore.BLUE}{end:<16}"
                        )
                        print(row)
                    print(f"{Fore.WHITE}{'=' * width}\n")
                except Exception as e:
                    logger.error(f"Error listing FRED series: {e}")
                return

            logger.error("Correct usage: list or list --source fred")
            return

        dbs = self.server.list_all()
        if not dbs:
            logger.warning("No databases found on disk.")
            return

        width = self.terminal_width
        print(f"\n{Fore.CYAN}{Style.BRIGHT}PERSISTED DATABASES:")
        print(f"{Fore.WHITE}=" * width)
        header = f"{'ID':<3} | {'SOURCE':<10} | {'ASSET':<8} | {'TF':<4} | {'ROWS':<8} | {'START':<16} | {'END':<16}"
        print(f"{Fore.YELLOW}{header}")
        print(f"{Fore.WHITE}-" * width)

        for idx, db in enumerate(dbs):
            # Date formatting, removing seconds if necessary
            start = (db["start_date"] or "")[:16]
            end = (db["end_date"] or "")[:16]
            rows = db["rows"] if db["rows"] is not None else "N/A"
            row = (
                f"{Fore.YELLOW}{idx + 1:<3} {Fore.WHITE}| "
                f"{Fore.CYAN}{db['source'].upper()[:10]:<10} {Fore.WHITE}| "
                f"{Fore.GREEN}{db['asset'].upper()[:8]:<8} {Fore.WHITE}| "
                f"{Fore.MAGENTA}{db['timeframe'].upper()[:4]:<4} {Fore.WHITE}| "
                f"{Fore.WHITE}{str(rows):<8} | "
                f"{Fore.BLUE}{start:<16} {Fore.WHITE}| "
                f"{Fore.BLUE}{end:<16}"
            )
            print(row)

        print(f"{Fore.WHITE}=" * width + "\n")

    def do_search(self, arg):
        """
        Search supported assets via specific source (Default: OpenBB)
        Usage: search [--source SOURCE] [--query QUERY] [--exchange EXCHANGE]
        Examples:
          search
          search --query \"Apple\"
          search --exchange NYSE
          search --source fred --query inflation
          search --source dukascopy --query \"bitcoin\"
        """
        if not arg.strip():
            self.server.show_search_summary()
            return

        parser = argparse.ArgumentParser(
            prog="search", description="Search assets", exit_on_error=False
        )
        parser.add_argument(
            "--source",
            type=str,
            default="openbb",
            help="Search source (openbb or dukascopy)",
        )
        parser.add_argument("--query", type=str, help="Keyword to search")
        parser.add_argument(
            "--exchange", type=str, help="Exchange to filter (OpenBB only)"
        )

        try:
            args_parsed = parser.parse_args(shlex.split(arg))
            if self._is_series_source(args_parsed.source):
                df = self.series_server.search_series(
                    source=args_parsed.source,
                    query=args_parsed.query,
                )
                if df is None or df.empty:
                    logger.info("No FRED series found.")
                    return

                print(f"\nFound {len(df)} series. Displaying the first 20:")
                width = self.terminal_width
                print(f"{Fore.WHITE}{'=' * width}")
                title_len = max(10, width - 52)
                header = f"{'SERIES ID':<18} | {'TITLE':<{title_len}} | {'FREQ':<10} | {'UNITS':<18}"
                print(f"{Fore.YELLOW}{header}")
                print(f"{Fore.WHITE}{'-' * width}")
                df = df.reset_index().fillna("")
                for _, row in df.head(20).iterrows():
                    series_id = str(row.get("series_id", row.get("id", "")))
                    title = str(row.get("title", row.get("name", "")))[:title_len]
                    frequency = str(
                        row.get("frequency", row.get("native_frequency", ""))
                    )
                    units = str(row.get("units", ""))[:16]
                    row_str = (
                        f"{Fore.GREEN}{series_id:<18} {Fore.WHITE}| "
                        f"{Fore.WHITE}{title:<{title_len}} | "
                        f"{Fore.CYAN}{frequency:<10} {Fore.WHITE}| "
                        f"{Fore.YELLOW}{units:<18}"
                    )
                    print(row_str)
                print(f"{Fore.WHITE}{'=' * width}\n")
                return

            df = self.server.search_assets(
                source=args_parsed.source,
                query=args_parsed.query,
                exchange=args_parsed.exchange,
            )

            if df is None or df.empty:
                return

            print(f"\nFound {len(df)} results. Displaying the first 20:")
            source_key = args_parsed.source.upper()
            width = self.terminal_width

            if source_key == "OPENBB":
                print(f"{Fore.WHITE}{'=' * width}")
                header = f"{'TICKER':<15} | {'COMPANY NAME':<55} | {'EXCHANGE':<15}"
                print(f"{Fore.YELLOW}{header}")
                print(f"{Fore.WHITE}{'-' * width}")
                df = df.reset_index().fillna("")
                for _, row in df.head(20).iterrows():
                    symbol = str(row.get("symbol", ""))
                    name = str(row.get("name", ""))[:53]
                    exc = str(row.get("exchange", ""))
                    row_str = (
                        f"{Fore.GREEN}{symbol:<15} {Fore.WHITE}| "
                        f"{Fore.WHITE}{name:<55} | "
                        f"{Fore.CYAN}{exc:<15}"
                    )
                    print(row_str)
                print(f"{Fore.WHITE}{'=' * width}\n")

            elif source_key == "DUKASCOPY":
                print(f"{Fore.WHITE}{'=' * width}")
                name_len = max(10, width - 51)
                header = f"{'TICKER':<20} | {'ALIAS':<15} | {'ASSET NAME':<{name_len}} | {'CATEGORY':<10}"
                print(f"{Fore.YELLOW}{header}")
                print(f"{Fore.WHITE}{'-' * width}")
                df = df.fillna("")
                for _, row in df.head(20).iterrows():
                    row_str = (
                        f"{Fore.GREEN}{str(row['ticker']):<20} {Fore.WHITE}| "
                        f"{Fore.CYAN}{str(row['alias']):<15} {Fore.WHITE}| "
                        f"{Fore.WHITE}{str(row['nome_do_ativo'])[:name_len]:<{name_len}} | "
                        f"{Fore.YELLOW}{str(row['categoria']):<10}"
                    )
                    print(row_str)
                print(f"{Fore.WHITE}{'=' * width}\n")

            else:
                # Generic output for new fetchers (like CCXT)
                print(f"{Fore.WHITE}{df.head(20).to_string()}\n")

        except SystemExit:
            pass
        except Exception as e:
            logger.error(f"Internal parse error: {e}")

    def do_fred_search(self, arg):
        """
        Search FRED economic series.
        Usage: fred_search [--query QUERY]
        Examples:
          fred_search
          fred_search --query inflation
        """
        forwarded = f"--source fred {arg}".strip()
        self.do_search(forwarded)

    def do_fred_download(self, arg):
        """
        Download and save a FRED series.
        Usage: fred_download <series_id> [start_date] [end_date] [--frequency FREQ]
        Examples:
          fred_download CPIAUCSL 2010-01-01 2024-01-01
          fred_download CPIAUCSL --frequency m
        """
        self.do_download(f"fred {arg}".strip())

    def do_fred_update(self, arg):
        """
        Update an existing FRED series.
        Usage: fred_update <series_id> [--lookback LOOKBACK] [--frequency FREQ]
        Examples:
          fred_update CPIAUCSL
          fred_update CPIAUCSL --lookback 30D
        """
        self.do_update(f"fred {arg}".strip())

    def do_fred_list(self, arg):
        """List stored FRED series. Usage: fred_list"""
        self.do_list("--source fred")

    def do_fred_info(self, arg):
        """
        Show info about a stored FRED series.
        Usage: fred_info <series_id>
        """
        self.do_info(f"fred {arg}".strip())

    def do_fred_delete(self, arg):
        """
        Delete a stored FRED series.
        Usage: fred_delete <series_id>
        """
        self.do_delete(f"fred {arg}".strip())

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
            logger.error(
                "Correct usage: quality <source> <assets,comma,separated> [timeframe=M1]"
            )
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
          schedule add-series <series_id> --cron "0 */4 * * *"
          schedule add-series <series_id> --interval <minutes>
          schedule list
          schedule remove <job_id>
        Examples:
          schedule add DUKASCOPY EURUSD M1 --interval 60
          schedule add OPENBB AAPL H1 --cron "0 9 * * 1-5"
          schedule add-series CPIAUCSL --interval 720
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
        add_p.add_argument(
            "--interval", type=int, default=None, dest="interval_minutes"
        )

        add_series_p = subparsers.add_parser("add-series")
        add_series_p.add_argument("series_id")
        add_series_p.add_argument("--cron", type=str, default=None)
        add_series_p.add_argument(
            "--interval", type=int, default=None, dest="interval_minutes"
        )
        add_series_p.add_argument("--lookback", dest="lookback_period", default=None)
        add_series_p.add_argument("--frequency", type=str, default=None)

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
                logger.info(
                    f"Job scheduled: {job['job_id']} | next run: {job['next_run']}"
                )
            except Exception as e:
                logger.error(f"Failed to schedule job: {e}")

        elif parsed.subcmd == "add-series":
            if not parsed.cron and not parsed.interval_minutes:
                logger.error("Provide --cron or --interval.")
                return
            try:
                add_series_job = getattr(self.scheduler, "add_series_job", None)
                if add_series_job is None:
                    logger.error("Series scheduling is not available in this build.")
                    return
                job = add_series_job(
                    source="fred",
                    series_id=parsed.series_id,
                    lookback_period=parsed.lookback_period,
                    frequency=parsed.frequency,
                    cron=parsed.cron,
                    interval_minutes=parsed.interval_minutes,
                )
                logger.info(
                    f"Series job scheduled: {job['job_id']} | next run: {job['next_run']}"
                )
            except Exception as e:
                logger.error(f"Failed to schedule series job: {e}")

        elif parsed.subcmd == "list":
            jobs = self.scheduler.list_jobs()
            if not jobs:
                logger.info("No scheduled jobs.")
                return
            width = self.terminal_width
            print(
                f"\n{'JOB ID':<38} | {'SOURCE':<10} | {'ASSET':<10} | {'TF':<4} | {'TRIGGER':<20} | NEXT RUN"
            )
            print(f"{Fore.WHITE}-" * width)
            for j in jobs:
                row = (
                    f"{Fore.WHITE}{j['job_id']:<38} | "
                    f"{Fore.CYAN}{j['source']:<10} | "
                    f"{Fore.GREEN}{j['asset']:<10} | "
                    f"{Fore.MAGENTA}{j['timeframe']:<4} | "
                    f"{Fore.YELLOW}{j['trigger']:<20} | "
                    f"{Fore.BLUE}{j['next_run']}"
                )
                print(row)

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


if __name__ == "__main__":
    setup_logger()
    DataManagerCLI().cmdloop()


def main() -> None:
    """Entry point for the datamanager CLI."""
    setup_logger()
    DataManagerCLI().cmdloop()
