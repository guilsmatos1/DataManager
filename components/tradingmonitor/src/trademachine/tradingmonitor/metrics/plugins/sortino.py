from __future__ import annotations

import pandas as pd
import quantstats as qs
from trademachine.tradingmonitor.metrics.plugins.base import BaseMetric


class SortinoRatio(BaseMetric):
    @property
    def name(self) -> str:
        return "Sortino Ratio"

    @property
    def is_advanced(self) -> bool:
        return True

    def calculate(
        self, deals_df: pd.DataFrame, daily_returns: pd.Series | None = None, **kwargs
    ) -> float | None:
        if daily_returns is None or daily_returns.empty:
            return None
        try:
            return float(qs.stats.sortino(daily_returns))
        except (ValueError, ZeroDivisionError):
            return None
