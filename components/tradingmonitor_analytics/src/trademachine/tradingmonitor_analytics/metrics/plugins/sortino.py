from __future__ import annotations

import numpy as np
import pandas as pd
from trademachine.tradingmonitor_analytics.metrics.plugins.base import BaseMetric


class SortinoRatio(BaseMetric):
    @property
    def name(self) -> str:
        return "Sortino Ratio"

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
        downside = r[r < 0]
        if len(downside) == 0:
            return None
        downside_std = (
            float(np.std(downside, ddof=1))
            if len(downside) > 1
            else float(abs(downside[0]))
        )
        if downside_std == 0:
            return None
        return float(np.mean(r) / downside_std * np.sqrt(252))
