"""Return-related formulas."""

from __future__ import annotations

from datetime import datetime

from trademachine.metrics.utils.time import years_between


def yearly_avg_return_pct(profit: float, initial_capital: float) -> float | None:
    """Yearly AVG % Return = Yearly AVG Profit / Initial Capital.

    Returns a fraction (0.10 = 10%). None if initial_capital is zero.
    """
    if initial_capital == 0:
        return None
    return profit / initial_capital


def cagr(
    initial_capital: float,
    ending_capital: float,
    start: datetime,
    end: datetime,
) -> float | None:
    """Compound Annual Growth Rate.

    CAGR = (Ending Capital / Initial Capital) ^ (1 / years) - 1
    Returns a fraction. None if inputs are invalid.
    """
    if initial_capital <= 0 or ending_capital <= 0:
        return None
    years = years_between(start, end)
    if years <= 0:
        return None
    return (ending_capital / initial_capital) ** (1.0 / years) - 1.0


def annual_over_maxdd(
    cagr_value: float | None, drawdown_pct: float | None
) -> float | None:
    """Annual% / Max DD% = CAGR / Drawdown %.

    Both inputs are fractions. None if drawdown is zero or inputs missing.
    """
    if cagr_value is None or drawdown_pct is None:
        return None
    if drawdown_pct == 0:
        return None
    # drawdown_pct is stored as a positive fraction representing the loss
    return cagr_value / abs(drawdown_pct)
