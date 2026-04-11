from __future__ import annotations

import numpy as np
import pandas as pd
from trademachine.tradingmonitor_analytics.metrics.plugins.base import BaseMetric


class DrawdownMetric(BaseMetric):
    @property
    def name(self) -> str:
        return "Drawdown"

    def calculate(
        self, _deals_df: pd.DataFrame, daily_returns: pd.Series | None = None, **_kwargs
    ) -> float | None:
        if daily_returns is None or daily_returns.empty:
            return None
        r = daily_returns.values
        if len(r) < 2:
            return None
        prices = np.concatenate([[1.0], np.cumprod(1 + r)])
        peaks = np.maximum.accumulate(prices)
        safe_peaks = np.where(peaks > 0, peaks, 1.0)
        drawdown = float(np.max((peaks - prices) / safe_peaks))
        return -drawdown * 100  # negative percentage — matches legacy convention
