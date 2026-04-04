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
        return self._safe_calc(lambda r: qs.stats.max_drawdown(r) * 100, daily_returns)  # type: ignore[no-any-return]
