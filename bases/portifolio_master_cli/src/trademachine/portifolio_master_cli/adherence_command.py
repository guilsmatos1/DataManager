"""
Adherence Command Module
========================
SQX vs MT5 adherence check functionality for PortifolioCLI.
"""

import json
import logging
import os
import shutil
from datetime import datetime as dt
from pathlib import Path

from trademachine.core.logger import LOGGER_NAME
from trademachine.portifoliomaster.services.adherence import (
    adherence_result_to_dict,
    run_adherence_check,
)
from trademachine.portifoliomaster.utils.visualizer import (
    generate_adherence_report_html,
)

logger = logging.getLogger(LOGGER_NAME)

DEFAULT_MT5_ADHERENCE_DIR = (
    "components/portifoliomaster/test/trademachine/portifoliomaster/reports"
)
DEFAULT_SQX_ADHERENCE_DIR = (
    "components/portifoliomaster/test/trademachine/portifoliomaster/reports-sqx"
)


class AdherenceMixin:
    """SQX vs MT5 adherence check functionality for PortifolioCLI."""

    def adherence_run(
        self,
        mt5_dir: str = DEFAULT_MT5_ADHERENCE_DIR,
        sqx_dir: str = DEFAULT_SQX_ADHERENCE_DIR,
        output_dir: str | None = None,
        threshold: float = 0.80,
        pearson_threshold: float = 0.85,
        export_passed_reports: bool = False,
        open_browser: bool = True,
        quiet: bool = False,
    ) -> bool:
        """Compares SQX backtests against MT5 backtests and reports adherence.

        Returns:
            True if all strategies passed, False if any failed.
        """
        result = run_adherence_check(
            mt5_dir,
            sqx_dir,
            threshold,
            pearson_threshold,
            show_progress=not quiet,
        )

        # Print terminal summary (suppressed in quiet mode)
        if not quiet:
            from colorama import Fore, Style

            width = getattr(self, "terminal_width", 100)
            name_len = max(20, width - 80)
            sep = f"{Fore.WHITE}{'=' * width}"
            print(
                f"\n{Fore.CYAN}{Style.BRIGHT}Adherence Check — trade>={threshold:.0%}  pearson>={pearson_threshold:.2f}{Style.RESET_ALL}"
            )
            print(sep)
            header = (
                f"{'Strategy':<{name_len}} {'MT5':>6} {'SQX':>6} {'Trade%':>8} "
                f"{'Pearson':>8} {'MT5 WR':>8} {'SQX WR':>8} "
                f"{'MT5RDD':>8} {'SQXrdd':>8}  Status"
            )
            print(f"{Fore.YELLOW}{header}")
            print(f"{Fore.WHITE}{'-' * width}")
            for s in result.strategies:
                if s.insufficient_data:
                    status_color = Fore.YELLOW
                    status_str = "INSUFFICIENT"
                else:
                    status_color = Fore.GREEN if s.passes else Fore.RED
                    status_str = "PASS" if s.passes else "FAIL"
                print(
                    f"{Fore.GREEN}{s.name[:name_len]:<{name_len}} {Fore.CYAN}{s.mt5_trades:>6} {Fore.CYAN}{s.sqx_trades:>6} "
                    f"{Fore.YELLOW}{s.trade_ratio * 100:>7.1f}% "
                    f"{Fore.MAGENTA}{s.pearson:>8.3f} "
                    f"{Fore.BLUE}{s.mt5_win_rate * 100:>7.1f}% "
                    f"{Fore.BLUE}{s.sqx_win_rate * 100:>7.1f}% "
                    f"{Fore.WHITE}{s.mt5_retdd:>8.2f} {Fore.WHITE}{s.sqx_retdd:>8.2f}  {status_color}{status_str}{Style.RESET_ALL}"
                )
            print(sep)
            print(
                f"{Fore.CYAN}Summary: {Fore.GREEN if result.passed == result.total else Fore.YELLOW}{result.passed}/{result.total} passed ({result.pass_rate:.1f}% pass rate){Style.RESET_ALL}"
            )
            print()

        # Output folder — always created (auto-timestamped when not specified)
        now = dt.now()
        timestamp = now.strftime("%Y-%m-%d_%H-%M")
        if output_dir is not None:
            final_out_dir = output_dir if output_dir else f"adherence_{timestamp}"
        else:
            final_out_dir = f"adherence_{timestamp}"
        Path(final_out_dir).mkdir(parents=True, exist_ok=True)

        # JSON output — always saved alongside the HTML
        data = adherence_result_to_dict(result)
        json_filename = "results.json"
        json_path = os.path.join(final_out_dir, json_filename)
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        logger.info(f"[output] {json_filename} → {os.path.abspath(json_path)}")

        # HTML report — always saved in the same folder
        report_filename = "adherence_report.html"
        report_path = os.path.join(final_out_dir, report_filename)
        abs_html = generate_adherence_report_html(result, report_path, open_browser)
        logger.info(f"[output] {report_filename} → {abs_html}")

        if export_passed_reports:
            passed_reports_dir = os.path.join(final_out_dir, "passed_mt5_reports")
            copied = 0
            for s in result.strategies:
                if not s.passes or s.insufficient_data or not s.mt5_report_path:
                    continue
                Path(passed_reports_dir).mkdir(parents=True, exist_ok=True)
                destination = os.path.join(
                    passed_reports_dir, os.path.basename(s.mt5_report_path)
                )
                if os.path.abspath(destination) == os.path.abspath(s.mt5_report_path):
                    destination = os.path.join(
                        passed_reports_dir,
                        f"{s.name}_{os.path.basename(s.mt5_report_path)}",
                    )
                shutil.copy2(s.mt5_report_path, destination)
                copied += 1
            if copied > 0:
                logger.info(
                    f"[output] passed_mt5_reports/ → {os.path.abspath(passed_reports_dir)} ({copied} files)"
                )
            else:
                logger.info("No passed MT5 reports to export.")

        logger.info(f"Output directory: {os.path.abspath(final_out_dir)}")

        return result.failed == 0  # type: ignore[no-any-return]
