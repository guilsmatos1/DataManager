from __future__ import annotations

import numpy as np
import pandas as pd
from trademachine.tradingmonitor_analytics.metrics.plugins.base import BaseMetric


class SharpeRatio(BaseMetric):
    @property
    def name(self) -> str:
        return "Sharpe Ratio"

    def calculate(
        self, _deals_df: pd.DataFrame, daily_returns: pd.Series | None = None, **_kwargs
    ) -> float | None:
        if daily_returns is None or daily_returns.empty:
            return None
        r = daily_returns.values
        if len(r) < 2:
            return None
        std = float(np.std(r, ddof=1))
        if std == 0:
            return None
        return float(np.mean(r) / std * np.sqrt(252))
