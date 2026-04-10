"""Risk metrics: Expectancy, R-Expectancy, SQN."""

from __future__ import annotations

import math


def expectancy(pnls: list[float]) -> float | None:
    """Expectancy = (win_rate * avg_win) + (loss_rate * avg_loss).

    Returns the expected P&L per trade. None if no trades.
    """
    if not pnls:
        return None
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    n = len(pnls)
    win_rate = len(wins) / n
    loss_rate = len(losses) / n
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    return (win_rate * avg_win) + (loss_rate * avg_loss)


def r_expectancy(pnls: list[float], risk_per_trade: float) -> float | None:
    """R Expectancy = Expectancy / risk_per_trade.

    Average trade expressed as a multiple of risk. None if risk is zero.
    """
    if risk_per_trade == 0:
        return None
    exp = expectancy(pnls)
    if exp is None:
        return None
    return exp / abs(risk_per_trade)


def r_expectancy_score(
    pnls: list[float], risk_per_trade: float, years: float
) -> float | None:
    """R Expectancy Score = R Expectancy * (num_trades / years).

    Extends R Expectancy by trade frequency. None if years <= 0 or risk zero.
    """
    if years <= 0 or not pnls:
        return None
    re = r_expectancy(pnls, risk_per_trade)
    if re is None:
        return None
    trades_per_year = len(pnls) / years
    return re * trades_per_year


def sqn(pnls: list[float]) -> float | None:
    """System Quality Number = (mean / std_dev) * sqrt(num_trades).

    None if fewer than 2 trades or std_dev is zero.
    """
    n = len(pnls)
    if n < 2:
        return None
    mean = sum(pnls) / n
    variance = sum((p - mean) ** 2 for p in pnls) / (n - 1)
    std = math.sqrt(variance)
    if std == 0:
        return None
    return (mean / std) * math.sqrt(n)


def sqn_score(pnls: list[float], years: float) -> float | None:
    """SQN Score = SQN adjusted for trade frequency per year.

    SQN Score = SQN * sqrt(num_trades / years) / sqrt(num_trades)
              = SQN * sqrt(1 / years)  (normalises to 1-year window)
    None if years <= 0 or SQN is None.
    """
    if years <= 0:
        return None
    sq = sqn(pnls)
    if sq is None:
        return None
    return sq * math.sqrt(1.0 / years)
