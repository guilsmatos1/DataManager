"""Profit-related formulas.

All functions are pure: (inputs) -> float.
"""

from __future__ import annotations

from datetime import datetime

from trademachine.metrics.utils.time import days_between, months_between, years_between


def total_profit(ending_capital: float, initial_capital: float) -> float:
    """Total Profit = Ending Capital - Initial Capital."""
    return ending_capital - initial_capital


def gross_profit(pnls: list[float]) -> float:
    """Gross Profit = sum of all winning (positive) trades."""
    return sum(p for p in pnls if p > 0)


def gross_loss(pnls: list[float]) -> float:
    """Gross Loss = sum of all losing (negative) trades (returned as negative number)."""
    return sum(p for p in pnls if p < 0)


def average_win(pnls: list[float]) -> float | None:
    """Average Win = Gross Profit / Number of Wins. None if no wins."""
    wins = [p for p in pnls if p > 0]
    if not wins:
        return None
    return sum(wins) / len(wins)


def average_loss(pnls: list[float]) -> float | None:
    """Average Loss = Gross Loss / Number of Losses. None if no losses.

    Returned as a negative number (mirrors trade P&L sign).
    """
    losses = [p for p in pnls if p < 0]
    if not losses:
        return None
    return sum(losses) / len(losses)


def average_trade(pnls: list[float]) -> float | None:
    """Average Trade = Total Profit / Number of trades. None if no trades."""
    if not pnls:
        return None
    return sum(pnls) / len(pnls)


def daily_avg_profit(profit: float, start: datetime, end: datetime) -> float | None:
    """Daily AVG Profit = Total Profit / Number of days. None if period is zero."""
    days = days_between(start, end)
    if days <= 0:
        return None
    return profit / days


def monthly_avg_profit(profit: float, start: datetime, end: datetime) -> float | None:
    """Monthly AVG Profit = Total Profit / Number of months. None if period is zero."""
    months = months_between(start, end)
    if months <= 0:
        return None
    return profit / months


def yearly_avg_profit(profit: float, start: datetime, end: datetime) -> float | None:
    """Yearly AVG Profit = Total Profit / Number of years. None if period is zero."""
    years = years_between(start, end)
    if years <= 0:
        return None
    return profit / years
