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

        from colorama import Fore, Style

        width = getattr(self, "terminal_width", 80)
        sep = f"{Fore.WHITE}{'=' * width}"
        print(
            f"\n{Fore.CYAN}{Style.BRIGHT}Correlation Matrix — Period: {period.upper()} | {n} strategies | {n_pairs} pairs{Style.RESET_ALL}"
        )
        print(sep)
        if n_pairs > 0:
            print(
                f"  {Fore.YELLOW}Mean:{Fore.WHITE} {np.nanmean(valid):+.3f}  |  "
                f"{Fore.YELLOW}Min:{Fore.WHITE} {np.nanmin(valid):+.3f}  |  "
                f"{Fore.YELLOW}Max:{Fore.WHITE} {np.nanmax(valid):+.3f}"
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
            print(f"{Fore.CYAN}{header}")
            print(f"{Fore.WHITE}{'-' * len(header)}")
            for i, row_name in enumerate(strategy_names):
                row_vals = "  ".join(
                    (
                        f"{Fore.RED if corr[i, j] < 0 else Fore.GREEN}{corr[i, j]:+.3f}{Fore.WHITE}".rjust(
                            col_w + len(Fore.RED) + len(Fore.WHITE)
                        )
                        if not np.isnan(corr[i, j])
                        else f"{Fore.YELLOW}   N/A {Fore.WHITE}".rjust(
                            col_w + len(Fore.YELLOW) + len(Fore.WHITE)
                        )
                    )
                    for j in range(n)
                )
                print(
                    f"{Fore.CYAN}{row_name[:name_w]:<{name_w}}{Fore.WHITE}  {row_vals}"
                )
        else:
            # Build sorted pair list
            pairs = []
            for idx in range(len(upper_idx[0])):
                i, j = upper_idx[0][idx], upper_idx[1][idx]
                v = corr[i, j]
                if not np.isnan(v):
                    pairs.append((v, strategy_names[i], strategy_names[j]))
            pairs.sort(reverse=True)

            name_len = max(28, (width - 15) // 2)

            if threshold is not None:
                filtered = [(v, a, b) for v, a, b in pairs if v >= threshold]
                print(
                    f"\n  {Fore.CYAN}Pairs with correlation >= {threshold:.2f}  ({len(filtered)} found){Style.RESET_ALL}"
                )
                print()
                for v, a, b in filtered:
                    print(
                        f"  {Fore.GREEN}{a[:name_len]:<{name_len}} {Fore.WHITE}× {Fore.GREEN}{b[:name_len]:<{name_len}}  {Fore.YELLOW}{v:+.3f}"
                    )
            else:
                show = min(top_n, len(pairs))
                if show > 0:
                    print(
                        f"\n  {Fore.CYAN}TOP {show} most correlated:{Style.RESET_ALL}"
                    )
                    for v, a, b in pairs[:show]:
                        print(
                            f"    {Fore.GREEN}{a[:name_len]:<{name_len}} {Fore.WHITE}× {Fore.GREEN}{b[:name_len]:<{name_len}}  {Fore.YELLOW}{v:+.3f}"
                        )
                if len(pairs) > show:
                    print(
                        f"\n  {Fore.CYAN}BOTTOM {show} least correlated:{Style.RESET_ALL}"
                    )
                    for v, a, b in pairs[-show:]:
                        print(
                            f"    {Fore.GREEN}{a[:name_len]:<{name_len}} {Fore.WHITE}× {Fore.GREEN}{b[:name_len]:<{name_len}}  {Fore.YELLOW}{v:+.3f}"
                        )

        print(f"{Fore.WHITE}{'=' * width}\n")

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

        from colorama import Fore, Style

        width = getattr(self, "terminal_width", 80)
        sep = f"{Fore.WHITE}{'=' * width}"
        print(f"\n{Fore.CYAN}{Style.BRIGHT}Strategy: {name}{Style.RESET_ALL}")
        print(sep)
        print(f"  {Fore.CYAN}{'Net Profit:':<22}{Fore.WHITE}{net_profit:>14,.2f}")
        print(f"  {Fore.CYAN}{'Max Drawdown:':<22}{Fore.RED}{max_dd:>14,.2f}")
        print(f"  {Fore.CYAN}{'Ret/DD:':<22}{Fore.BLUE}{ret_dd:>14.2f}")
        print(f"  {Fore.CYAN}{'Total Trades:':<22}{Fore.WHITE}{total:>14}")
        print(f"  {Fore.CYAN}{'Win Rate:':<22}{Fore.YELLOW}{win_rate:>13.1f}%")
        print(f"  {Fore.CYAN}{'Avg Win:':<22}{Fore.GREEN}{avg_win:>14,.2f}")
        print(f"  {Fore.CYAN}{'Avg Loss:':<22}{Fore.RED}{avg_loss:>14,.2f}")
        print(f"  {Fore.CYAN}{'Win/Loss Ratio:':<22}{Fore.MAGENTA}{wl_ratio:>14.2f}")
        print(f"  {Fore.CYAN}{'Date Range:':<22}{Fore.WHITE}{date_from} → {date_to}")
        print(f"{Fore.WHITE}{'=' * width}\n")

        if show_chart:
            plot_portfolio_equity((name,), self.portfolio_manager.strategies)  # type: ignore[attr-defined]
