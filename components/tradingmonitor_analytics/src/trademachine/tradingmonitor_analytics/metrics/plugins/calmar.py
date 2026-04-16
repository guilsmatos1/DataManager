from __future__ import annotations

import numpy as np
import pandas as pd
from trademachine.tradingmonitor_analytics.metrics.plugins.base import BaseMetric


class CalmarRatio(BaseMetric):
    @property
    def name(self) -> str:
        return "Calmar Ratio"

    @property
    def is_advanced(self) -> bool:
        return True

    def calculate(
        self, _deals_df: pd.DataFrame, daily_returns: pd.Series | None = None, **_kwargs
    ) -> float | None:
        if daily_returns is None or daily_returns.empty:
            return None
        r = daily_returns.values
        if len(r) < 2:
            return None
        # Annualised return (CAGR)
        total_ret = float(np.prod(1 + r)) - 1.0
        base = 1.0 + total_ret
        if base <= 0:
            return None
        annual_ret = base ** (252.0 / len(r)) - 1.0
        # Max drawdown from cumulative price series
        prices = np.concatenate([[1.0], np.cumprod(1 + r)])
        peaks = np.maximum.accumulate(prices)
        safe_peaks = np.where(peaks > 0, peaks, 1.0)
        max_dd = float(np.max((peaks - prices) / safe_peaks))
        if max_dd == 0:
            return None
        return float(annual_ret / max_dd)
