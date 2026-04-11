from __future__ import annotations

import numpy as np
import pandas as pd
from trademachine.tradingmonitor_analytics.metrics.plugins.base import BaseMetric


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
        return self._safe_calc(  # type: ignore[no-any-return]
            lambda r: r[r <= np.percentile(r, 5)].mean(), daily_returns
        )
