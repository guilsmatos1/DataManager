from __future__ import annotations

import pandas as pd
import quantstats as qs
from trademachine.tradingmonitor.metrics.plugins.base import BaseMetric


class CalmarRatio(BaseMetric):
    @property
    def name(self) -> str:
        return "Calmar Ratio"

    @property
    def is_advanced(self) -> bool:
        return True

    def calculate(
        self, deals_df: pd.DataFrame, daily_returns: pd.Series | None = None, **kwargs
    ) -> float | None:
        return self._safe_calc(qs.stats.calmar, daily_returns)  # type: ignore[no-any-return]
