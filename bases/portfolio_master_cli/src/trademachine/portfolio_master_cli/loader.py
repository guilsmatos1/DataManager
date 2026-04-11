"""
Loader Module
=============
Report loading and strategy listing functionality.
"""

import concurrent.futures
import glob
import logging
import os

from tqdm import tqdm
from trademachine.core.logger import LOGGER_NAME
from trademachine.mt5.parser import MT5ReportParser
from trademachine.portfoliomaster.public import ParserError, PortfolioManager

logger = logging.getLogger(LOGGER_NAME)


def _parse_mt5_report_file(filepath: str) -> dict[str, object]:
    """Worker-friendly parser for a single MT5 report file."""
    parser = MT5ReportParser()
    try:
        expert_name = parser.parse_report(filepath)
        return {
            "ok": True,
            "filepath": filepath,
            "expert_name": expert_name,
            "deals_df": parser.deals_by_expert[expert_name],
        }
    except Exception as e:
        return {
            "ok": False,
            "filepath": filepath,
            "error_type": e.__class__.__name__,
            "error": str(e),
        }


class LoaderMixin:
    """Report loading and strategy listing functionality for PortfolioCLI."""

    def load_reports(
        self,
        directory_path: str | None = None,
        use_cache: bool = True,
        parse_workers: int | None = None,
    ):
        """Loads MT5 reports. Prioritizes root cache."""
        cache_filepath = self.default_config.get("cache_path", "cache.parquet")  # type: ignore[attr-defined]
        cache_service = self._cache_service(cache_filepath)  # type: ignore[attr-defined]
        self._correlation_cache.clear()  # type: ignore[attr-defined]

        if use_cache and os.path.exists(cache_filepath):
            logger.info(
                f"Loading cached strategies from: {os.path.abspath(cache_filepath)}"
            )
            try:
                self.loaded_expert_names = cache_service.load_into_manager(
                    self.portfolio_manager
                )
                logger.info(
                    f"[OK] {len(self.loaded_expert_names)} strategies loaded from cache."
                )
                return
            except Exception as e:
                logger.warning(f"Cache invalid or incompatible: {e}.")

        if not directory_path:
            logger.error(
                "No cache found and no directory provided to scan for reports."
            )
            return

        if not os.path.exists(directory_path):
            logger.error(f"Directory '{directory_path}' does not exist.")
            return

        report_files = sorted(glob.glob(os.path.join(directory_path, "*.html")))
        if not report_files:
            logger.error(f"No MT5 HTML reports found in '{directory_path}'.")
            return

        self._reset_loaded_state()
        logger.info(f"Parsing {len(report_files)} reports from {directory_path}...")
        parse_results: list[dict[str, object]] = []
        file_order = {filepath: idx for idx, filepath in enumerate(report_files)}
        configured_workers = (
            parse_workers
            if parse_workers is not None
            else self.default_config.get("load_workers", 0)  # type: ignore[attr-defined]
        )
        if configured_workers and configured_workers > 0:
            max_workers = min(len(report_files), configured_workers)
        else:
            max_workers = min(len(report_files), os.cpu_count() or 1, 8)

        if max_workers <= 1:
            for filepath in tqdm(report_files, desc="Parsing"):
                parse_results.append(_parse_mt5_report_file(filepath))
        else:
            try:
                logger.info(f"Parsing workers: {max_workers}")
                with concurrent.futures.ProcessPoolExecutor(
                    max_workers=max_workers
                ) as executor:
                    futures = {
                        executor.submit(_parse_mt5_report_file, filepath): filepath
                        for filepath in report_files
                    }
                    with tqdm(total=len(report_files), desc="Parsing") as progress:
                        for future in concurrent.futures.as_completed(futures):
                            parse_results.append(future.result())
                            progress.update(1)
            except Exception as e:
                logger.warning(
                    "Parallel parsing failed, retrying sequentially: %s",
                    e,
                )
                parse_results = []
                for filepath in tqdm(report_files, desc="Parsing"):
                    parse_results.append(_parse_mt5_report_file(filepath))

        parse_results.sort(
            key=lambda result: file_order.get(str(result["filepath"]), len(file_order))
        )

        for result in parse_results:
            filepath = str(result["filepath"])
            if not bool(result["ok"]):
                error_type = str(result.get("error_type", "Error"))
                error = str(result.get("error", "Unknown error"))
                if error_type == ParserError.__name__:
                    tqdm.write(f"   - Skipped {os.path.basename(filepath)}: {error}")
                else:
                    tqdm.write(
                        f"   - Unexpected error parsing {os.path.basename(filepath)}: {error}"
                    )
                continue

            expert_name = str(result["expert_name"])
            deals_df = result["deals_df"]
            if self.portfolio_manager.add_strategy(expert_name, deals_df):
                if expert_name not in self.loaded_expert_names:
                    self.loaded_expert_names.append(expert_name)

        if self.loaded_expert_names:
            cache_service.persist_manager(
                self.portfolio_manager, self.loaded_expert_names
            )

        logger.info(
            f"Total: {len(self.loaded_expert_names)} strategies successfully loaded."
        )

    def list_loaded_strategies(self):
        """Prints a table of all strategies currently in memory."""
        if not self.loaded_expert_names:
            logger.warning("Memory is empty.")
            return

        width = getattr(self, "terminal_width", 80)
        name_len = max(30, width - 65)

        from colorama import Fore, Style

        print(f"\n{Fore.CYAN}{Style.BRIGHT}LOADED STRATEGIES:{Style.RESET_ALL}")
        print(f"{Fore.GREEN}=" * width)
        header = f"{'Name':<{name_len}} | {'Lot':>6} | {'# Trades':<10} | {'Net Profit':<12} | {'MaxDD':<10} | {'Ret/DD':<8}"
        print(f"{Fore.YELLOW}{header}")
        print(f"{Fore.GREEN}-" * width)

        for name in sorted(self.loaded_expert_names):
            metrics = self.portfolio_manager.calculate_strategy_metrics(name)
            lot = self.portfolio_manager.strategy_lots.get(name, 1.0)
            if metrics:
                self._print_strategy_row(name, metrics, lot, name_len)

        print(f"{Fore.GREEN}=" * width + "\n")

    def _print_strategy_row(
        self, name: str, metrics: dict, lot: float, name_len: int = 30
    ):
        """Prints a single formatted strategy row."""
        from colorama import Fore

        print(
            f"{Fore.GREEN}{name[:name_len]:<{name_len}} {Fore.GREEN}| "
            f"{Fore.YELLOW}{lot:>6.2f} {Fore.GREEN}| "
            f"{Fore.CYAN}{metrics['Trades']:<10} {Fore.GREEN}| "
            f"{Fore.MAGENTA}{metrics['Profit']:<12.2f} {Fore.GREEN}| "
            f"{Fore.RED}{metrics['MaxDD']:<10.2f} {Fore.GREEN}| "
            f"{Fore.BLUE}{metrics['RetDD']:<8.2f}"
        )

    def _reset_loaded_state(self) -> None:
        """Clears in-memory strategies before a fresh explicit load."""
        self.portfolio_manager = PortfolioManager()
        self.loaded_expert_names = []
        self._correlation_cache.clear()  # type: ignore[attr-defined]

    def _ensure_loaded(self) -> bool:
        """Auto-loads from cache if strategies are not yet in memory."""
        if self.loaded_expert_names:
            return True
        self.load_reports()
        return bool(self.loaded_expert_names)
