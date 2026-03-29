from __future__ import annotations

import pandas as pd
from trademachine.tradingmonitor.metrics.plugins.base import BaseMetric


class ExpectedValue(BaseMetric):
    @property
    def name(self) -> str:
        return "Expected Value"

    def calculate(
        self, deals_df: pd.DataFrame, daily_returns: pd.Series | None = None, **kwargs
    ) -> float | None:
        if deals_df is None or deals_df.empty:
            return None
        net = deals_df["profit"] + deals_df["commission"] + deals_df["swap"]
        if net.empty:
            return None
        wins = net[net > 0]
        losses = net[net < 0]
        total = len(net)
        win_rate = len(wins) / total
        loss_rate = len(losses) / total
        avg_win = float(wins.mean()) if len(wins) > 0 else 0.0
        avg_loss = float(abs(losses.mean())) if len(losses) > 0 else 0.0
        return round((win_rate * avg_win) - (loss_rate * avg_loss), 4)
