import argparse
import cmd
import logging
import os
import re
import shlex
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from colorama import Fore, Style, init
from dateutil.parser import parse  # type: ignore[import-untyped]
from trademachine.core.interactive import (
    create_prompt_session,
    interactive_history_path,
    read_interactive_input,
)
from trademachine.core.logger import LOGGER_NAME, setup_logger

__version__ = "0.1.0"
from trademachine.datamanager.public import DataManager, SchedulerService, SeriesManager

init(autoreset=True)

logger = logging.getLogger(LOGGER_NAME)

_UNSET_PLACEHOLDERS = {"your_api_key_here", "YOUR_API_KEY_HERE", ""}

# Keys managed by the config command: (env_var_name, display_label)
_CONFIG_KEYS: list[tuple[str, str]] = [
    ("FRED_API_KEY", "FRED API Key"),
    ("OPENBB_FRED_API_KEY", "OpenBB FRED API Key"),
    ("DATAMANAGER_API_KEY", "DataManager API Key"),
]


def _find_env_path() -> Path | None:
    """Walk up from cwd looking for a .env file (max 5 levels)."""
    current = Path.cwd()
    for _ in range(5):
        candidate = current / ".env"
        if candidate.exists():
            return candidate
        current = current.parent
    return None


def _mask(value: str) -> str:
    if not value or value in _UNSET_PLACEHOLDERS:
        return f"{Fore.RED}not set{Style.RESET_ALL}"
    if len(value) <= 8:
        return "****"
    return f"{Fore.GREEN}{value[:4]}{'*' * (len(value) - 4)}{Style.RESET_ALL}"


def _read_env_vars(env_path: Path) -> dict[str, str]:
    """Parse key=value pairs from a .env file, skipping comments and blanks."""
    result: dict[str, str] = {}
    for line in env_path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            k, _, v = stripped.partition("=")
            result[k.strip()] = v.strip()
    return result


def _write_env_key(env_path: Path, key: str, value: str) -> None:
    """Update an existing key or append it to the .env file."""
    lines = env_path.read_text().splitlines(keepends=True)
    found = False
    new_lines = []
    for line in lines:
        if line.startswith(f"{key}=") or line.startswith(f"{key} ="):
            new_lines.append(f"{key}={value}\n")
            found = True
        else:
            new_lines.append(line)
    if not found:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines.append("\n")
        new_lines.append(f"{key}={value}\n")
    env_path.write_text("".join(new_lines))


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
        decorated_title = f"{Fore.CYAN}{Style.BRIGHT}{'─' * padding}{Fore.GREEN}{title}{Fore.CYAN}{'─' * (width - padding - len(title))}{Style.RESET_ALL}"

        self.intro = f"""
{decorated_title}
{Fore.GREEN}{sep}
 {Fore.GREEN}Centralized financial data management system for OHLCV and economic series. Efficiently fetch, store, update, and resample market data in TimescaleDB.

 {Fore.YELLOW}● INTERACTIVE MODE ●{Fore.GREEN}

 {Fore.GREEN}Type {Fore.YELLOW}'help'{Fore.GREEN} for the full manual or {Fore.YELLOW}'exit'{Fore.GREEN} to quit.
{Fore.GREEN}{sep}
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
                        print(f"{Fore.GREEN}{cleaned_doc}\n")

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
                f"{Fore.GREEN}Ensure your TimescaleDB (Postgres) is running and your .env credentials are correct."
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

    def do_config(self, arg):
        """
        Manage API key configuration stored in .env.
        Usage:
          config show                          → show status of all configured keys
          config set fred-key <value>          → set FRED_API_KEY and OPENBB_FRED_API_KEY
          config set api-key <value>           → set DATAMANAGER_API_KEY
        Examples:
          config show
          config set fred-key abc123
          config set api-key mysecret
        """
        args = shlex.split(arg) if arg.strip() else []

        if not args or args[0] == "show":
            env_path = _find_env_path()
            width = self.terminal_width
            print(f"\n{Fore.CYAN}{Style.BRIGHT}API KEY CONFIGURATION{Style.RESET_ALL}")
            print(f"{Fore.GREEN}{'=' * width}")
            if env_path:
                print(f"  {Fore.CYAN}{'File':<24} {Fore.GREEN}» {env_path}")
                env_vars = _read_env_vars(env_path)
            else:
                print(
                    f"  {Fore.YELLOW}.env file not found — keys read from environment only"
                )
                env_vars = {}
            print(f"{Fore.GREEN}{'-' * width}")
            for env_key, label in _CONFIG_KEYS:
                value = env_vars.get(env_key) or os.environ.get(env_key, "")
                print(f"  {Fore.CYAN}{label:<24} {Fore.GREEN}» {_mask(value)}")
            print(f"{Fore.GREEN}{'=' * width}\n")
            return

        if args[0] == "set":
            if len(args) != 3:
                logger.error("Usage: config set <fred-key|api-key> <value>")
                return
            key_name, value = args[1].lower(), args[2]
            env_path = _find_env_path()
            if env_path is None:
                logger.error(
                    ".env file not found. Create one at the project root first."
                )
                return

            if key_name == "fred-key":
                _write_env_key(env_path, "FRED_API_KEY", value)
                _write_env_key(env_path, "OPENBB_FRED_API_KEY", value)
                logger.info("FRED_API_KEY and OPENBB_FRED_API_KEY updated in .env")
            elif key_name == "api-key":
                _write_env_key(env_path, "DATAMANAGER_API_KEY", value)
                logger.info("DATAMANAGER_API_KEY updated in .env")
            else:
                logger.error(f"Unknown key '{key_name}'. Use: fred-key | api-key")
            return

        logger.error("Usage: config show | config set <fred-key|api-key> <value>")

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
                        self.server.resample_data(source, asset, tf)
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

    def do_resample(self, arg):
        """
        Rebuilds one or more higher timeframes from the stored M1 base and saves them to the database.
        Usage: resample <source> <asset1,asset2,...> <tf1,tf2,...>
        Examples:
          resample DUKASCOPY EURUSD M5,H1,D1
          resample OPENBB AAPL,MSFT H1,W1
        """
        args = shlex.split(arg)

        if len(args) != 3:
            logger.error(
                "Correct usage: resample <source> <assets,comma,separated> <timeframes,comma,separated>"
            )
            return

        source = args[0]
        assets = [a.strip() for a in args[1].split(",") if a.strip()]
        timeframes = [tf.strip() for tf in args[2].split(",") if tf.strip()]

        for asset in assets:
            for timeframe in timeframes:
                try:
                    self.server.resample_data(source, asset, timeframe)
                except Exception as e:
                    logger.error(f"Error resampling {asset} to {timeframe}: {e}")

    _TIMEFRAME_RE = re.compile(r"^(M[0-9]+|H[0-9]+|D[0-9]+|W[0-9]+)$", re.IGNORECASE)

    def do_delete(self, arg):
        """
        Delete database(s).

        Usage:
          delete <source> <asset(s)>             — deletes M1 data + asset record (disappears from all timeframes)
          delete <source> <asset(s)> M1          — deletes only M1 rows (keeps asset record)
          delete <source> <asset(s)> <derived>   — drops the entire continuous aggregate view for that
                                                   derived timeframe (H1, M15, etc.). This removes
                                                   the timeframe for ALL assets, not just the one requested.
          delete <source> all                    — removes all assets from <source>
          delete fred <series_id>                — deletes a FRED economic series
          delete all                             — deletes ALL data from all sources

        Examples:
          delete dukascopy eurusd                — remove EURUSD from all timeframes
          delete dukascopy eurusd M1             — wipe M1 rows only
          delete OPENBB AAPL,MSFT               — remove multiple assets
          delete dukascopy H1                    — remove all DUKASCOPY assets
          delete FRED CPIAUCSL
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

        if (
            len(args) == 2
            and not self._is_series_source(args[0])
            and self._TIMEFRAME_RE.match(args[1])
        ):
            source = args[0]
            dbs = self.server.list_all()
            matching = [
                db["asset"]
                for db in dbs
                if db["source"].upper() == source.upper() and db["timeframe"] == "M1"
            ]
            if not matching:
                logger.info(f"No databases found for source {source.upper()}.")
                return
            confirm = input(
                f"{Fore.RED}WARNING: You are about to delete {len(matching)} database(s) "
                f"from {source.upper()}: {', '.join(matching)}. Continue? (y/N): {Style.RESET_ALL}"
            )
            if confirm.lower() == "y":
                self.server.delete_by_source(source)
            else:
                logger.info("Operation cancelled.")
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
            print(f"{Fore.GREEN}{'=' * width}")
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
                        else Fore.GREEN
                    )
                    print(f"  {Fore.CYAN}{label:<16} {Fore.GREEN}» {val_color}{val}")
            print(f"{Fore.GREEN}{'=' * width}\n")
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
        print(f"{Fore.GREEN}{'=' * width}")
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
                val_color = Fore.GREEN if key in ["rows", "asset"] else Fore.GREEN
                print(f"  {Fore.CYAN}{label:<14} {Fore.GREEN}» {val_color}{val}")
        print(f"{Fore.GREEN}{'=' * width}\n")

    def do_list(self, arg):
        """
        Lists all saved databases and FRED series.
        Usage: list
        """
        if arg.strip():
            logger.error("Correct usage: list  (no arguments)")
            return

        width = self.terminal_width
        asset_len = max(8, width - 75)

        dbs = self.server.list_all()
        if dbs:
            print(f"\n{Fore.CYAN}{Style.BRIGHT}PERSISTED DATABASES:{Style.RESET_ALL}")
            print(f"{Fore.GREEN}=" * width)
            header = f"{'ID':<3} | {'SOURCE':<10} | {'ASSET':<{asset_len}} | {'TF':<4} | {'ROWS':<8} | {'START':<16} | {'END':<16}"
            print(f"{Fore.YELLOW}{header}")
            print(f"{Fore.GREEN}-" * width)
            for idx, db in enumerate(dbs):
                start = (db["start_date"] or "")[:16]
                end = (db["end_date"] or "")[:16]
                rows = db["rows"] if db["rows"] is not None else "N/A"
                row = (
                    f"{Fore.YELLOW}{idx + 1:<3} {Fore.GREEN}| "
                    f"{Fore.CYAN}{db['source'].upper()[:10]:<10} {Fore.GREEN}| "
                    f"{Fore.GREEN}{db['asset'].upper()[:asset_len]:<{asset_len}} {Fore.GREEN}| "
                    f"{Fore.MAGENTA}{db['timeframe'].upper()[:4]:<4} {Fore.GREEN}| "
                    f"{Fore.GREEN}{str(rows):<8} | "
                    f"{Fore.BLUE}{start:<16} {Fore.GREEN}| "
                    f"{Fore.BLUE}{end:<16}"
                )
                print(row)
            print(f"{Fore.GREEN}=" * width)
        else:
            logger.warning("No OHLCV databases found.")

        try:
            fred_items = self.series_server.list_series()
        except Exception as e:
            logger.error(f"Error listing FRED series: {e}")
            fred_items = []

        if fred_items:
            title_len = max(10, width - 80)
            print(f"\n{Fore.CYAN}{Style.BRIGHT}FRED SERIES:{Style.RESET_ALL}")
            print(f"{Fore.GREEN}=" * width)
            header = f"{'SERIES ID':<18} | {'TITLE':<{title_len}} | {'FREQ':<10} | {'ROWS':<8} | {'START':<16} | {'END':<16}"
            print(f"{Fore.YELLOW}{header}")
            print(f"{Fore.GREEN}{'-' * width}")
            for item in fred_items:
                start = (item.get("observation_start") or "")[:16]
                end = (item.get("observation_end") or "")[:16]
                rows = item.get("rows", "N/A")
                row = (
                    f"{Fore.GREEN}{str(item.get('series_id', '')):<18} {Fore.GREEN}| "
                    f"{Fore.GREEN}{str(item.get('title', ''))[:title_len]:<{title_len}} | "
                    f"{Fore.CYAN}{str(item.get('frequency', '')):<10} {Fore.GREEN}| "
                    f"{Fore.YELLOW}{str(rows):<8} {Fore.GREEN}| "
                    f"{Fore.BLUE}{start:<16} {Fore.GREEN}| "
                    f"{Fore.BLUE}{end:<16}"
                )
                print(row)
            print(f"{Fore.GREEN}{'=' * width}\n")
        else:
            print()

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
                print(f"{Fore.GREEN}{'=' * width}")
                title_len = max(10, width - 52)
                header = f"{'SERIES ID':<18} | {'TITLE':<{title_len}} | {'FREQ':<10} | {'UNITS':<18}"
                print(f"{Fore.YELLOW}{header}")
                print(f"{Fore.GREEN}{'-' * width}")
                df = df.reset_index().fillna("")
                for _, row in df.head(20).iterrows():
                    series_id = str(row.get("series_id", row.get("id", "")))
                    title = str(row.get("title", row.get("name", "")))[:title_len]
                    frequency = str(
                        row.get("frequency", row.get("native_frequency", ""))
                    )
                    units = str(row.get("units", ""))[:16]
                    row_str = (
                        f"{Fore.GREEN}{series_id:<18} {Fore.GREEN}| "
                        f"{Fore.GREEN}{title:<{title_len}} | "
                        f"{Fore.CYAN}{frequency:<10} {Fore.GREEN}| "
                        f"{Fore.YELLOW}{units:<18}"
                    )
                    print(row_str)
                print(f"{Fore.GREEN}{'=' * width}\n")
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
                print(f"{Fore.GREEN}{'=' * width}")
                name_len = max(10, width - 35)
                header = (
                    f"{'TICKER':<15} | {'COMPANY NAME':<{name_len}} | {'EXCHANGE':<15}"
                )
                print(f"{Fore.YELLOW}{header}")
                print(f"{Fore.GREEN}{'-' * width}")
                df = df.reset_index().fillna("")
                for _, row in df.head(20).iterrows():
                    symbol = str(row.get("symbol", ""))
                    name = str(row.get("name", ""))[:name_len]
                    exc = str(row.get("exchange", ""))
                    row_str = (
                        f"{Fore.GREEN}{symbol:<15} {Fore.GREEN}| "
                        f"{Fore.GREEN}{name:<{name_len}} | "
                        f"{Fore.CYAN}{exc:<15}"
                    )
                    print(row_str)
                print(f"{Fore.GREEN}{'=' * width}\n")

            elif source_key == "DUKASCOPY":
                print(f"{Fore.GREEN}{'=' * width}")
                name_len = max(10, width - 51)
                header = f"{'TICKER':<20} | {'ALIAS':<15} | {'ASSET NAME':<{name_len}} | {'CATEGORY':<10}"
                print(f"{Fore.YELLOW}{header}")
                print(f"{Fore.GREEN}{'-' * width}")
                df = df.fillna("")
                for _, row in df.head(20).iterrows():
                    row_str = (
                        f"{Fore.GREEN}{str(row['ticker']):<20} {Fore.GREEN}| "
                        f"{Fore.CYAN}{str(row['alias']):<15} {Fore.GREEN}| "
                        f"{Fore.GREEN}{str(row['nome_do_ativo'])[:name_len]:<{name_len}} | "
                        f"{Fore.YELLOW}{str(row['categoria']):<10}"
                    )
                    print(row_str)
                print(f"{Fore.GREEN}{'=' * width}\n")

            else:
                # Generic output for new fetchers (like CCXT)
                print(f"{Fore.GREEN}{df.head(20).to_string()}\n")

        except SystemExit:
            pass
        except Exception as e:
            logger.error(f"Internal parse error: {e}")

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
          schedule update-all --cron "0 2 * * *"
          schedule update-all --interval <minutes>
          schedule list
          schedule remove <job_id>
        Examples:
          schedule add DUKASCOPY EURUSD M1 --interval 60
          schedule add OPENBB AAPL H1 --cron "0 9 * * 1-5"
          schedule add-series CPIAUCSL --interval 720
          schedule update-all --cron "0 2 * * *"
          schedule update-all --interval 360
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

        update_all_p = subparsers.add_parser("update-all")
        update_all_p.add_argument("--cron", type=str, default=None)
        update_all_p.add_argument(
            "--interval", type=int, default=None, dest="interval_minutes"
        )

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

        elif parsed.subcmd == "update-all":
            if not parsed.cron and not parsed.interval_minutes:
                logger.error("Provide --cron or --interval.")
                return
            try:
                job = self.scheduler.add_update_all_job(
                    cron=parsed.cron,
                    interval_minutes=parsed.interval_minutes,
                )
                logger.info(
                    f"Update-all job scheduled: {job['job_id']} | next run: {job['next_run']}"
                )
            except Exception as e:
                logger.error(f"Failed to schedule update-all job: {e}")

        elif parsed.subcmd == "list":
            jobs = self.scheduler.list_jobs()
            if not jobs:
                logger.info("No scheduled jobs.")
                return
            width = self.terminal_width
            asset_len = max(10, width - 103)
            print(
                f"\n{'JOB ID':<38} | {'SOURCE':<10} | {'ASSET':<{asset_len}} | {'TF':<4} | {'TRIGGER':<20} | NEXT RUN"
            )
            print(f"{Fore.GREEN}-" * width)
            for j in jobs:
                row = (
                    f"{Fore.GREEN}{j['job_id']:<38} | "
                    f"{Fore.CYAN}{j['source']:<10} | "
                    f"{Fore.GREEN}{j['asset']:<{asset_len}} | "
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
    setup_logger(log_path="projects/datamanager/log.log")
    DataManagerCLI().cmdloop()


def main() -> None:
    """Entry point for the datamanager CLI."""
    setup_logger(log_path="projects/datamanager/log.log")
    import sys

    cli = DataManagerCLI()
    if len(sys.argv) > 1 and sys.argv[1] != "-i":
        # Execute single command from arguments
        command = " ".join(shlex.quote(arg) for arg in sys.argv[1:])
        cli.onecmd(command)
    else:
        # Start interactive session
        cli.cmdloop()
