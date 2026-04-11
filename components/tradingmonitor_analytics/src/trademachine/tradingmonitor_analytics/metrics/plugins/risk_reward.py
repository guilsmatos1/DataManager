from __future__ import annotations

import pandas as pd
from trademachine.tradingmonitor_analytics.metrics.plugins.base import BaseMetric


class RiskRewardRatio(BaseMetric):
    @property
    def name(self) -> str:
        return "Risk-Reward Ratio"

    @property
    def is_advanced(self) -> bool:
        return True

    def calculate(
        self, deals_df: pd.DataFrame, daily_returns: pd.Series | None = None, **kwargs
    ) -> float | None:
        if deals_df.empty:
            return None
        wins = deals_df[deals_df["profit"] > 0]["profit"]
        losses = deals_df[deals_df["profit"] < 0]["profit"]
        if not wins.empty and not losses.empty:
            avg_win = wins.mean()
            avg_loss = abs(losses.mean())
            return float(avg_win / avg_loss) if avg_loss > 0 else None
        return None
