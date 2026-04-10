"""Ratio-related formulas."""

from __future__ import annotations


def profit_factor(pnls: list[float]) -> float | None:
    """Profit Factor = Sum of Winning Trades / |Sum of Losing Trades|.

    None if there are no losing trades.
    """
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p < 0))
    if gl == 0:
        return None
    return gp / gl


def return_dd_ratio(profit: float, drawdown: float) -> float | None:
    """Return / DD Ratio = Total Profit / Drawdown.

    None if drawdown is zero.
    """
    if drawdown == 0:
        return None
    return profit / abs(drawdown)


def payout_ratio(avg_win: float | None, avg_loss: float | None) -> float | None:
    """Payout Ratio = Average Win / |Average Loss|.

    How many times the average win is bigger than the average loss.
    None if avg_loss is zero or inputs are missing.
    """
    if avg_win is None or avg_loss is None:
        return None
    if avg_loss == 0:
        return None
    return avg_win / abs(avg_loss)


def wins_losses_ratio(pnls: list[float]) -> float | None:
    """Wins / Losses Ratio = Number of Wins / Number of Losses.

    None if there are no losses.
    """
    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p < 0)
    if losses == 0:
        return None
    return wins / losses


def winning_pct(pnls: list[float]) -> float | None:
    """Winning Percentage = Number of Wins / Total Trades.

    Returns a fraction (0.60 = 60%). None if no trades.
    """
    if not pnls:
        return None
    wins = sum(1 for p in pnls if p > 0)
    return wins / len(pnls)
