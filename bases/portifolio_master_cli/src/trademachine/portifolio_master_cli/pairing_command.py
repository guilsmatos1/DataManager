"""
Pairing Command Module
======================
Drawdown pairing functionality for PortifolioCLI.
"""

import logging

from trademachine.core.logger import LOGGER_NAME
from trademachine.portifoliomaster.core.exceptions import ValidationError
from trademachine.portifoliomaster.services.pairing import PairingService

logger = logging.getLogger(LOGGER_NAME)


class PairingMixin:
    """Drawdown pairing functionality for PortifolioCLI."""

    def drawdown_pairing(
        self,
        target_dd: float = 4000.0,
        lot_tick: float = 0.1,
        apply: bool = False,
        report_path: str | None = None,
    ) -> None:
        """Calculates the optimal lot size per strategy to match the target drawdown.

        For each loaded strategy, reads the actual lot used in the backtest (from the
        Volume column, persisted in cache_lots.json) and computes the absolute lot
        (rounded to the nearest lot_tick) whose drawdown is closest to target_dd.

        With apply=True, scales every strategy's Net_Profit history by the computed
        factor (paired_lot / base_lot), updates strategy_lots, and rewrites the cache
        so that all downstream commands (--list, --optimize, etc.) see the normalised
        values.

        Args:
            target_dd: Desired maximum drawdown in account currency (default: 4000).
            lot_tick:  Minimum lot increment of the instrument (e.g. 0.1).
            apply:     If True, persist the scaled values to memory and cache.
        """
        if report_path and not report_path.lower().endswith(".csv"):
            raise ValidationError("--report must point to a .csv file.")
        if not self._ensure_loaded():  # type: ignore[attr-defined]
            return

        # Guard: refuse to apply if already applied to prevent double-scaling
        if apply and self.portfolio_manager._lots_meta.get("dd_paired"):  # type: ignore[attr-defined]
            prev_target = self.portfolio_manager._lots_meta.get("target", "?")  # type: ignore[attr-defined]
            prev_tick = self.portfolio_manager._lots_meta.get("tick", "?")  # type: ignore[attr-defined]
            print(
                f"[!] DD Pairing already applied (target={prev_target}, tick={prev_tick}). "
                "Run 'cache rebuild <dir>' to reset before applying again."
            )
            return

        pairing_service = PairingService(target_dd=target_dd, lot_tick=lot_tick)
        has_lots = bool(self.portfolio_manager.strategy_lots)  # type: ignore[attr-defined]
        if not has_lots:
            logger.warning(
                "Lot data not available (cache_lots.json missing). "
                "Reload via --load <dir> to extract lots from HTML reports. "
                "Falling back to base lot = 1.0 for all strategies."
            )

        rows = pairing_service.analyze(
            self.loaded_expert_names,  # type: ignore[attr-defined]
            self.portfolio_manager.strategies,  # type: ignore[attr-defined]
            self.portfolio_manager.strategy_lots,  # type: ignore[attr-defined]
        )

        if not rows:
            print("No strategies loaded.")
            return

        from colorama import Fore, Style

        width = getattr(self, "terminal_width", 100)
        name_len = max(20, width - 85)

        mode = (
            f"  {Fore.YELLOW}[--apply: cache will be updated]{Style.RESET_ALL}"
            if apply
            else ""
        )
        header = (
            f"{'Strategy':<{name_len}} | {'Base Lot':>9} | {'Paired Lot':>10} | "
            f"{'DD (orig)':>12} | {'DD (paired)':>12} | {'Diff':>10} | {'Profit (paired)':>15}"
        )
        sep = f"{Fore.WHITE}{'=' * width}"
        print(
            f"\n{Fore.CYAN}{Style.BRIGHT}Drawdown Pairing  |  Target: {target_dd:,.0f}  |  Lot tick: {lot_tick}{mode}"
        )
        print(sep)
        print(f"{Fore.YELLOW}{header}")
        print(f"{Fore.WHITE}{'-' * width}")

        for row in rows:
            base_str = f"{row.base_lot:.{pairing_service.decimals}f}"
            lot_str = (
                f"{row.paired_lot:.{pairing_service.decimals}f}"
                if row.paired_lot is not None
                else "N/A"
            )
            print(
                f"{Fore.GREEN}{row.name[:name_len]:<{name_len}} {Fore.WHITE}| "
                f"{Fore.CYAN}{base_str:>9} {Fore.WHITE}| {Fore.YELLOW}{lot_str:>10} {Fore.WHITE}| "
                f"{Fore.MAGENTA}{row.orig_dd:>12,.2f} {Fore.WHITE}| {Fore.MAGENTA}{row.paired_dd:>12,.2f} {Fore.WHITE}| "
                f"{Fore.RED if row.diff < 0 else Fore.GREEN}{row.diff:>+10,.2f} {Fore.WHITE}| "
                f"{Fore.BLUE}{row.paired_profit:>15,.2f}"
            )

        print(sep)
        print()

        if report_path:
            abs_report_path = pairing_service.export_report(rows, report_path)
            print(
                f"{Fore.GREEN}[OK] Pairing CSV report saved to: {abs_report_path}{Style.RESET_ALL}"
            )

        if not apply:
            return

        apply_result = pairing_service.apply(self.portfolio_manager, rows)  # type: ignore[attr-defined]
        if apply_result.changed == 0:
            print(
                f"{Fore.CYAN}[OK] No changes applied — all strategies already at target drawdown.{Style.RESET_ALL}"
            )
            return

        self._correlation_cache.clear()  # type: ignore[attr-defined]
        self._cache_service().persist_manager(  # type: ignore[attr-defined]
            self.portfolio_manager,
            self.loaded_expert_names,  # type: ignore[attr-defined]
        )
        print(
            f"{Fore.GREEN}[OK] Pairing finished:{Style.RESET_ALL} {apply_result.analyzed} analyzed, "
            f"{apply_result.changed} changed, {apply_result.unchanged} unchanged. "
            "Cache updated."
        )
