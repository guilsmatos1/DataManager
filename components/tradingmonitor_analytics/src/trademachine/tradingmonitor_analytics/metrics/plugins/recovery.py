from __future__ import annotations

import numpy as np
import pandas as pd
from trademachine.tradingmonitor_analytics.metrics.plugins.base import BaseMetric
from trademachine.tradingmonitor_analytics.metrics.utils import net_pnl


class RetDDMetric(BaseMetric):
    @property
    def name(self) -> str:
        return "Ret/DD"

    def calculate(
        self, deals_df: pd.DataFrame, daily_returns: pd.Series | None = None, **_kwargs
    ) -> float | None:
        if deals_df.empty:
            return None
        if daily_returns is None or daily_returns.empty:
            return None
        r = daily_returns.values
        if len(r) < 2:
            return None
        try:
            profit = net_pnl(deals_df).sum()
            prices = np.concatenate([[1.0], np.cumprod(1 + r)])
            peaks = np.maximum.accumulate(prices)
            safe_peaks = np.where(peaks > 0, peaks, 1.0)
            drawdown = float(np.max((peaks - prices) / safe_peaks))
            if drawdown == 0:
                return 0.0
            # Total compound return over the period
            total_ret = float(prices[-1]) - 1.0
            ret_dd = total_ret / drawdown
            if profit < 0:
                return -abs(ret_dd)
            return abs(ret_dd)
        except (ValueError, ZeroDivisionError):
            return None
