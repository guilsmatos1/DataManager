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

        mode = "  [--apply: cache will be updated]" if apply else ""
        header = (
            f"{'Strategy':<30} | {'Base Lot':>9} | {'Paired Lot':>10} | "
            f"{'DD (orig)':>12} | {'DD (paired)':>12} | {'Diff':>10} | {'Profit (paired)':>15}"
        )
        sep = "─" * len(header)
        print(
            f"\nDrawdown Pairing  |  Target: {target_dd:,.0f}  |  Lot tick: {lot_tick}{mode}"
        )
        print(sep)
        print(header)
        print(sep)

        for row in rows:
            base_str = f"{row.base_lot:.{pairing_service.decimals}f}"
            lot_str = (
                f"{row.paired_lot:.{pairing_service.decimals}f}"
                if row.paired_lot is not None
                else "N/A"
            )
            print(
                f"{row.name[:30]:<30} | {base_str:>9} | {lot_str:>10} | "
                f"{row.orig_dd:>12,.2f} | {row.paired_dd:>12,.2f} | "
                f"{row.diff:>+10,.2f} | {row.paired_profit:>15,.2f}"
            )

        print(sep)
        print()

        if report_path:
            abs_report_path = pairing_service.export_report(rows, report_path)
            print(f"[OK] Pairing CSV report saved to: {abs_report_path}")

        if not apply:
            return

        apply_result = pairing_service.apply(self.portfolio_manager, rows)  # type: ignore[attr-defined]
        if apply_result.changed == 0:
            print(
                "[OK] No changes applied — all strategies already at target drawdown."
            )
            return

        self._correlation_cache.clear()  # type: ignore[attr-defined]
        self._cache_service().persist_manager(  # type: ignore[attr-defined]
            self.portfolio_manager,
            self.loaded_expert_names,  # type: ignore[attr-defined]
        )
        print(
            f"[OK] Pairing finished: {apply_result.analyzed} analyzed, "
            f"{apply_result.changed} changed, {apply_result.unchanged} unchanged. "
            "Cache updated."
        )
