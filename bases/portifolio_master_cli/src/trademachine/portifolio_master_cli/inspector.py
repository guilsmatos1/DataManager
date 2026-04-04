"""
Inspector Module
================
Strategy inspection and correlation analysis for PortifolioCLI.
"""

import logging

import numpy as np
from trademachine.core.logger import LOGGER_NAME
from trademachine.portifoliomaster.utils.visualizer import plot_portfolio_equity

logger = logging.getLogger(LOGGER_NAME)


class InspectorMixin:
    """Strategy inspection and correlation analysis for PortifolioCLI."""

    def inspect_correlations(
        self, period: str = "D", top_n: int = 10, threshold: float | None = None
    ) -> None:
        """Displays the pairwise correlation matrix between all loaded strategies."""
        if not self._ensure_loaded():  # type: ignore[attr-defined]
            return

        all_trades = self.portfolio_manager.get_all_trades_long()  # type: ignore[attr-defined]
        strategy_names = sorted(all_trades["Strategy"].unique().to_list())
        n = len(strategy_names)

        corr = self.portfolio_manager.compute_periodic_correlation(  # type: ignore[attr-defined]
            all_trades, strategy_names, period
        )
        upper_idx = np.triu_indices(n, k=1)
        upper_vals = corr[upper_idx]

        valid = upper_vals[~np.isnan(upper_vals)]
        n_pairs = len(valid)

        sep = "─" * 60
        print(
            f"\nCorrelation Matrix — Period: {period.upper()} | {n} strategies | {n_pairs} pairs"
        )
        print(sep)
        if n_pairs > 0:
            print(
                f"  Mean: {np.nanmean(valid):+.3f}  |  "
                f"Min: {np.nanmin(valid):+.3f}  |  "
                f"Max: {np.nanmax(valid):+.3f}"
            )

        # For small n, show full matrix; for large n, show pairs list
        if n <= 12:
            print()
            col_w = 8
            name_w = max(len(s) for s in strategy_names)
            name_w = min(name_w, 24)
            header = " " * (name_w + 2) + "  ".join(
                s[:col_w].rjust(col_w) for s in strategy_names
            )
            print(header)
            print("─" * len(header))
            for i, row_name in enumerate(strategy_names):
                row_vals = "  ".join(
                    f"{corr[i, j]:+.3f}".rjust(col_w)
                    if not np.isnan(corr[i, j])
                    else "   N/A ".rjust(col_w)
                    for j in range(n)
                )
                print(f"{row_name[:name_w]:<{name_w}}  {row_vals}")
        else:
            # Build sorted pair list
            pairs = []
            for idx in range(len(upper_idx[0])):
                i, j = upper_idx[0][idx], upper_idx[1][idx]
                v = corr[i, j]
                if not np.isnan(v):
                    pairs.append((v, strategy_names[i], strategy_names[j]))
            pairs.sort(reverse=True)

            if threshold is not None:
                filtered = [(v, a, b) for v, a, b in pairs if v >= threshold]
                print(
                    f"\n  Pairs with correlation >= {threshold:.2f}  ({len(filtered)} found)"
                )
                print()
                for v, a, b in filtered:
                    print(f"  {a[:28]:<28} × {b[:28]:<28}  {v:+.3f}")
            else:
                show = min(top_n, len(pairs))
                if show > 0:
                    print(f"\n  TOP {show} most correlated:")
                    for v, a, b in pairs[:show]:
                        print(f"    {a[:28]:<28} × {b[:28]:<28}  {v:+.3f}")
                if len(pairs) > show:
                    print(f"\n  BOTTOM {show} least correlated:")
                    for v, a, b in pairs[-show:]:
                        print(f"    {a[:28]:<28} × {b[:28]:<28}  {v:+.3f}")

        print()

    def inspect_strategy(self, name: str, show_chart: bool = False) -> None:
        """Displays detailed metrics for a single strategy."""
        if not self._ensure_loaded():  # type: ignore[attr-defined]
            return

        # Fuzzy match: exact first, then case-insensitive substring
        if name not in self.portfolio_manager.strategies:  # type: ignore[attr-defined]
            name_lower = name.lower()
            candidates = [
                n
                for n in self.loaded_expert_names
                if name_lower in n.lower()  # type: ignore[attr-defined]
            ]
            if not candidates:
                print(f"Strategy '{name}' not found.")
                print(
                    "  Loaded strategies: "
                    + ", ".join(sorted(self.loaded_expert_names)[:10])  # type: ignore[attr-defined]
                    + ("..." if len(self.loaded_expert_names) > 10 else "")  # type: ignore[attr-defined]
                )
                return
            if len(candidates) > 1:
                print(f"Ambiguous name '{name}'. Matches:")
                for c in sorted(candidates):
                    print(f"  {c}")
                return
            name = candidates[0]

        from trademachine.portifoliomaster.services.metrics import (
            compute_performance_ratios,
            compute_vector_metrics,
        )

        df = self.portfolio_manager.strategies[name]  # type: ignore[attr-defined]
        profits = df["Net_Profit"].to_numpy()
        total = len(profits)

        # Use shared metrics
        vm = compute_vector_metrics(profits)
        net_profit = vm["Profit"]
        max_dd = vm["MaxDD"]
        ret_dd = vm["RetDD"]
        pr = compute_performance_ratios(df)
        win_rate = pr["win_percentage"]
        avg_win = pr["avg_win"]
        avg_loss = pr["avg_loss"]
        wl_ratio = pr["win_loss_ratio"]

        # Date range
        dates = df["Horário"].drop_nulls()
        date_from = str(dates.min())[:10] if len(dates) > 0 else "N/A"
        date_to = str(dates.max())[:10] if len(dates) > 0 else "N/A"

        sep = "─" * 44
        print(f"\nStrategy: {name}")
        print(sep)
        print(f"  {'Net Profit:':<22}{net_profit:>14,.2f}")
        print(f"  {'Max Drawdown:':<22}{max_dd:>14,.2f}")
        print(f"  {'Ret/DD:':<22}{ret_dd:>14.2f}")
        print(f"  {'Total Trades:':<22}{total:>14}")
        print(f"  {'Win Rate:':<22}{win_rate:>13.1f}%")
        print(f"  {'Avg Win:':<22}{avg_win:>14,.2f}")
        print(f"  {'Avg Loss:':<22}{avg_loss:>14,.2f}")
        print(f"  {'Win/Loss Ratio:':<22}{wl_ratio:>14.2f}")
        print(f"  {'Date Range:':<22}{date_from} → {date_to}")
        print()

        if show_chart:
            plot_portfolio_equity((name,), self.portfolio_manager.strategies)  # type: ignore[attr-defined]
