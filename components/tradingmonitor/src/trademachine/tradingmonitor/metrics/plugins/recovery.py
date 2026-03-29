from __future__ import annotations

import pandas as pd
import quantstats as qs
from trademachine.tradingmonitor.metrics.plugins.base import BaseMetric


class RecoveryFactor(BaseMetric):
    @property
    def name(self) -> str:
        return "Recovery Factor"

    def calculate(
        self, deals_df: pd.DataFrame, daily_returns: pd.Series | None = None, **kwargs
    ) -> float | None:
        if deals_df.empty:
            return None

        # Net profit includes commissions and swaps
        net_profit = (
            deals_df["profit"].sum()
            + deals_df["commission"].sum()
            + deals_df["swap"].sum()
        )

        if daily_returns is None or daily_returns.empty:
            return None

        try:
            # quantstats returns max_drawdown as a negative fraction (e.g. -0.15)
            max_dd = qs.stats.max_drawdown(daily_returns)
            if max_dd == 0:
                return 0.0

            # Recovery Factor = Net Profit / |Max Drawdown|
            # But we want it to be negative if Net Profit is negative.
            # Using absolute value of drawdown to avoid double negative.
            # We also need the absolute monetary drawdown.
            # However, since daily_returns are fractional, qs.stats.recovery_factor
            # usually works on returns. Let's just fix the sign of quantstats result.
            rf = float(qs.stats.recovery_factor(daily_returns))

            if net_profit < 0:
                return -abs(rf)
            return abs(rf)

        except (ValueError, ZeroDivisionError):
            return None
