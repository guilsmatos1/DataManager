"""Exposure formula."""

from __future__ import annotations

from datetime import datetime

from trademachine.metrics.types import TradeRecord


def exposure(
    trades: list[TradeRecord],
    period_start: datetime,
    period_end: datetime,
) -> float | None:
    """Exposure = total time in position / total sample period.

    Returns a fraction (0.40 = 40% of time in a trade).
    None if the period is zero or there are no trades.
    """
    if not trades:
        return None
    total_seconds = (period_end - period_start).total_seconds()
    if total_seconds <= 0:
        return None
    in_trade_seconds = sum((t.exit_time - t.entry_time).total_seconds() for t in trades)
    return min(in_trade_seconds / total_seconds, 1.0)
