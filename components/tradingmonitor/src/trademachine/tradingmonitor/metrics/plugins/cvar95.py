from __future__ import annotations

import numpy as np
import pandas as pd
from trademachine.tradingmonitor.metrics.plugins.base import BaseMetric


class CVaR95(BaseMetric):
    @property
    def name(self) -> str:
        return "CVaR 95% (daily)"

    @property
    def is_advanced(self) -> bool:
        return True

    def calculate(
        self, deals_df: pd.DataFrame, daily_returns: pd.Series | None = None, **kwargs
    ) -> float | None:
        if daily_returns is None or daily_returns.empty:
            return None
        try:
            var_5 = np.percentile(daily_returns, 5)
            return float(daily_returns[daily_returns <= var_5].mean())
        except (ValueError, ZeroDivisionError):
            return None
