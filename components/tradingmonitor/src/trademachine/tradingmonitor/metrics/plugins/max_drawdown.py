from __future__ import annotations

import pandas as pd
import quantstats as qs
from trademachine.tradingmonitor.metrics.plugins.base import BaseMetric


class MaxDrawdown(BaseMetric):
    @property
    def name(self) -> str:
        return "Max Drawdown (%)"

    def calculate(
        self, deals_df: pd.DataFrame, daily_returns: pd.Series | None = None, **kwargs
    ) -> float | None:
        if daily_returns is None or daily_returns.empty:
            return None
        try:
            return float(qs.stats.max_drawdown(daily_returns) * 100)
        except (ValueError, ZeroDivisionError):
            return None
