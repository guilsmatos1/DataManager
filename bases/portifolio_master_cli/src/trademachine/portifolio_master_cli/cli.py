"""
CLI Module
==========
Manages the Command Line Interface and user interactions.

This module serves as the facade for the PortifolioCLI class, composing
specialized mixins for each responsibility area. The actual logic lives
in the mixin modules:

- loader.py          — Report loading and strategy listing
- cache_commands.py  — Cache management subcommands
- io_commands.py     — Import/export and output
- optimizer.py       — Optimization orchestration
- inspector.py       — Strategy inspection and correlation analysis
- pairing_command.py — Drawdown pairing
- adherence_command.py — SQX vs MT5 adherence checks
"""

import json
import logging
import os
import shlex

import numpy as np
from colorama import Fore, Style, init
from trademachine.core.interactive import (
    create_prompt_session,
    interactive_history_path,
    read_interactive_input,
)
from trademachine.core.logger import LOGGER_NAME
from trademachine.portifolio_master_cli.adherence_command import AdherenceMixin
from trademachine.portifolio_master_cli.cache_commands import CacheMixin
from trademachine.portifolio_master_cli.inspector import InspectorMixin
from trademachine.portifolio_master_cli.io_commands import IOMixin

# Re-export for test compatibility (tests patch cli_module._parse_mt5_report_file)
from trademachine.portifolio_master_cli.loader import (  # noqa: F401
    LoaderMixin,
    _parse_mt5_report_file,
)
from trademachine.portifolio_master_cli.optimizer import OptimizerMixin
from trademachine.portifolio_master_cli.pairing_command import PairingMixin
from trademachine.portifoliomaster.services.portfolio import PortfolioManager

init(autoreset=True)

logger = logging.getLogger(LOGGER_NAME)

DEFAULT_MT5_ADHERENCE_DIR = (
    "components/portifoliomaster/test/trademachine/portifoliomaster/reports"
)
DEFAULT_SQX_ADHERENCE_DIR = (
    "components/portifoliomaster/test/trademachine/portifoliomaster/reports-sqx"
)


class PortifolioCLI(
    LoaderMixin,
    CacheMixin,
    IOMixin,
    OptimizerMixin,
    InspectorMixin,
    PairingMixin,
    AdherenceMixin,
):
    """Interface for user interactions via command line or interactive shell.

    Composes specialized mixins for each responsibility area while
    maintaining a single unified API surface for typer_app.py and tests.
    """

    def __init__(self, default_config: dict | None = None):
        self.portfolio_manager = PortfolioManager()
        self.loaded_expert_names: list[str] = []
        self.default_config = default_config or {}
        self.last_optimization_results: list[dict] = []
        self._correlation_cache: dict[tuple, np.ndarray] = {}

    # ------------------------------------------------------------------
    # interactive shell + config (stay in this module)
    # ------------------------------------------------------------------

    @staticmethod
    def _interactive_history_path() -> str:
        """Returns the shell history file used by the interactive prompt."""
        return interactive_history_path("portifoliomaster")

    def _create_prompt_session(self):
        """Builds a prompt_toolkit session when available."""
        return create_prompt_session(self._interactive_history_path(), logger=logger)

    def _read_interactive_input(self, prompt_session) -> str:
        """Reads one interactive command, using history-capable prompt when possible."""
        prompt_text = f"\n{Fore.GREEN}PMaster> {Style.RESET_ALL}"
        return read_interactive_input(prompt_session, prompt_text)

    def config_show(self, config_path: str = "config.json") -> None:
        """Displays the active configuration."""
        from trademachine.portifoliomaster.core.config import AppConfig

        cfg = AppConfig.from_json(config_path)
        src = "config.json" if os.path.exists(config_path) else "defaults"

        sep = "─" * 44
        print(f"\nActive configuration  (source: {src})")
        print(sep)
        for field, value in cfg.model_dump().items():
            print(f"  {field:<32}{value}")

    def config_validate(self, config_path: str = "config.json") -> None:
        """Validates config.json and reports any errors."""
        from pydantic import ValidationError as PydanticValidationError
        from trademachine.portifoliomaster.core.config import AppConfig

        abs_path = os.path.abspath(config_path)
        if not os.path.exists(config_path):
            print(f"No config.json found at: {abs_path}")
            print("Default values will be used on next run.")
            return

        try:
            with open(config_path, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"[INVALID JSON] {abs_path}")
            print(f"  {e}")
            return

        try:
            AppConfig(**data)
            print(f"[OK] {abs_path}")
            print("  All fields are valid.")
        except PydanticValidationError as e:
            print(f"[INVALID] {abs_path}")
            for err in e.errors():
                field = " → ".join(str(loc) for loc in err["loc"])
                print(f"  {field}: {err['msg']}")

    def start_interactive_shell(self, default_csv_cols: list[str] | None = None):
        """Enters an interactive loop for command execution using the Typer app."""
        import typer
        from trademachine.portifolio_master_cli.typer_app import app

        _ = default_csv_cols
        prompt_session = self._create_prompt_session()

        banner_art = (
            f"\n{Fore.CYAN}{Style.BRIGHT}"
            r"  _____           _   _  __      _ _        __  __           _            "
            + "\n"
            r"  |  __ \         | | (_)/ _|    | (_)      |  \/  |         | |           "
            + "\n"
            r"  | |__) |__  _ __| |_ _| |_ ___ | |_  ___  | \  / | __ _ ___| |_ ___ _ __ "
            + "\n"
            r"  |  ___/ _ \| '__| __| |  _/ _ \| | |/ _ \ | |\/| |/ _` / __| __/ _ \ '__|"
            + "\n"
            r"  | |  | (_) | |  | |_| | || (_) | | | (_) || |  | | (_| \__ \ ||  __/ |   "
            + "\n"
            r"  |_|   \___/|_|   \__|_|_| \___/|_|_|\___/ |_|  |_|\__,_|___/\__\___|_|   "
        )
        separator = f"{Fore.WHITE}{'═' * 76}"
        title = (
            f"  {' ' * 20}{Fore.CYAN}{Style.BRIGHT}PortfolioMaster"
            f"{Fore.WHITE} - {Fore.GREEN}v0.1.0"
        )
        commands = (
            f"  {Fore.CYAN}optimize{Fore.WHITE} | {Fore.CYAN}adherence{Fore.WHITE} | "
            f"{Fore.CYAN}inspect{Fore.WHITE} | {Fore.CYAN}cache{Fore.WHITE} | "
            f"{Fore.CYAN}config{Fore.WHITE} | {Fore.CYAN}pairing{Fore.WHITE}"
        )
        hint = f"  {Fore.WHITE}Type {Fore.YELLOW}'help'{Fore.WHITE} for full help or {Fore.YELLOW}'exit'{Fore.WHITE} to quit."
        mode_label = f"  {Fore.YELLOW}● INTERACTIVE MODE ●"
        print(banner_art)
        print(separator)
        print(title)
        print(separator)
        print(mode_label)
        print()
        print(f"  {Style.BRIGHT}COMMANDS:{Style.NORMAL}")
        print(f"  {commands}")
        print()
        print(hint)
        print(separator)

        while True:
            try:
                user_input = self._read_interactive_input(prompt_session).strip()
                if not user_input:
                    continue
                if user_input.lower() in ("exit", "quit", "q"):
                    break

                try:
                    split_args = shlex.split(user_input)
                except ValueError as e:
                    logger.error(f"Invalid command syntax: {e}")
                    continue

                if not split_args:
                    continue

                # Map bare 'help' / 'help <cmd>' to '--help' / '<cmd> --help'
                if split_args[0].lower() == "help":
                    split_args = (
                        split_args[1:] + ["--help"]
                        if len(split_args) > 1
                        else ["--help"]
                    )

                # Run command through Typer
                try:
                    # Using standalone_mode=False to avoid sys.exit() on help or errors
                    app(split_args, standalone_mode=False)
                except (typer.Exit, typer.Abort):
                    continue
                except Exception as e:
                    logger.error(f"Command Error: {e}")

            except KeyboardInterrupt:
                break
            except EOFError:
                break
            except Exception as error:
                logger.error(f"Shell Error: {error}")
