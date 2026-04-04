from __future__ import annotations

import pandas as pd
import quantstats as qs
from trademachine.tradingmonitor.metrics.plugins.base import BaseMetric


class SharpeRatio(BaseMetric):
    @property
    def name(self) -> str:
        return "Sharpe Ratio"

    def calculate(
        self, deals_df: pd.DataFrame, daily_returns: pd.Series | None = None, **kwargs
    ) -> float | None:
        return self._safe_calc(qs.stats.sharpe, daily_returns)  # type: ignore[no-any-return]
