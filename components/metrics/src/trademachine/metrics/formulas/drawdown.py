"""Drawdown and stagnation formulas."""

from __future__ import annotations

from datetime import datetime


def drawdown(equity: list[float]) -> float | None:
    """Drawdown = max(equity_peak - following_trough).

    Returns the absolute drawdown value (positive number).
    None if fewer than 2 equity points.
    """
    if len(equity) < 2:
        return None
    max_dd = 0.0
    peak = equity[0]
    for value in equity[1:]:
        if value > peak:
            peak = value
        dd = peak - value
        if dd > max_dd:
            max_dd = dd
    return max_dd


def drawdown_pct(equity: list[float]) -> float | None:
    """Drawdown % = Drawdown / Previous Capital Peak.

    Returns a positive fraction (0.10 = 10% drawdown).
    None if fewer than 2 equity points or peak is zero.
    """
    if len(equity) < 2:
        return None
    max_dd_pct = 0.0
    peak = equity[0]
    for value in equity[1:]:
        if value > peak:
            peak = value
        if peak == 0:
            continue
        dd_pct = (peak - value) / peak
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct
    return max_dd_pct


def stagnation_days(equity: list[float], timestamps: list[datetime]) -> int | None:
    """Stagnation in Days = longest period without making a new equity high.

    Returns the number of days. None if fewer than 2 points.
    """
    if len(equity) < 2 or len(equity) != len(timestamps):
        return None
    max_stagnation = 0
    peak_idx = 0
    peak_val = equity[0]
    for i in range(1, len(equity)):
        if equity[i] > peak_val:
            peak_val = equity[i]
            peak_idx = i
        else:
            days = (timestamps[i] - timestamps[peak_idx]).days
            if days > max_stagnation:
                max_stagnation = days
    return max_stagnation


def stagnation_pct(equity: list[float], timestamps: list[datetime]) -> float | None:
    """Stagnation % = max stagnation period / total period.

    Returns a fraction (0.30 = 30% of time spent without new highs).
    None if period is zero or fewer than 2 points.
    """
    if len(equity) < 2 or len(equity) != len(timestamps):
        return None
    total_days = (timestamps[-1] - timestamps[0]).days
    if total_days == 0:
        return None
    stag = stagnation_days(equity, timestamps)
    return stag / total_days if stag is not None else None
