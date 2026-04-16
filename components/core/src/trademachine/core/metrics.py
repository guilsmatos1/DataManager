"""Shared metrics computation for all components."""

from __future__ import annotations

import numpy as np


def compute_sharpe_ratio(returns: np.ndarray, risk_free: float = 0.0) -> float:
    """Compute Sharpe ratio from returns array.

    Args:
        returns: Array of returns (daily or any frequency).
        risk_free: Risk-free rate (annualized if returns are annualized).

    Returns:
        Sharpe ratio as float.
    """
    if len(returns) < 2:
        return 0.0
    excess = returns - risk_free
    if np.std(excess) == 0:
        return 0.0
    return float(np.mean(excess) / np.std(excess))


def compute_max_drawdown(returns: np.ndarray) -> float:
    """Compute maximum drawdown percentage from returns array.

    Builds an equity curve starting from 0 and computes max drawdown.

    Args:
        returns: Array of returns.

    Returns:
        Maximum drawdown as a positive percentage (e.g., 10.5 for 10.5% drawdown).
    """
    if len(returns) < 1:
        return 0.0
    equity = np.cumsum(np.insert(returns, 0, 0.0))
    peaks = np.maximum.accumulate(equity)
    drawdowns = peaks - equity
    return float(np.max(drawdowns))


def compute_equity_curve(returns: np.ndarray) -> np.ndarray:
    """Build a cumulative equity curve starting at 0.

    Args:
        returns: Array of per-period returns.

    Returns:
        Equity curve with len(returns)+1 elements, starting at 0.
    """
    if len(returns) == 0:
        return np.array([0.0])
    return np.cumsum(np.insert(returns, 0, 0.0))


def compute_win_rate(returns: np.ndarray) -> float:
    """Compute win rate (percentage of winning trades among non-zero trades).

    Break-even trades (profit == 0) are excluded from the calculation.

    Args:
        returns: Array of individual trade/period returns.

    Returns:
        Win rate as a percentage (0-100).
    """
    if len(returns) == 0:
        return 0.0
    non_zero = returns[returns != 0]
    if len(non_zero) == 0:
        return 0.0
    wins = np.sum(non_zero > 0)
    return float((wins / len(non_zero)) * 100)


def compute_profit_factor(returns: np.ndarray) -> float:
    """Compute profit factor (gross profit / gross loss).

    Args:
        returns: Array of trade/period returns.

    Returns:
        Profit factor ratio (inf if no losses).
    """
    gross_profit = float(np.sum(returns[returns > 0]))
    gross_loss = abs(float(np.sum(returns[returns < 0])))
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def compute_retdd(returns: np.ndarray) -> float:
    """Compute Return/Drawdown ratio (Recovery Factor).

    Args:
        returns: Array of trade/period returns.

    Returns:
        Return/Drawdown ratio.
    """
    profit = float(np.sum(returns))
    max_dd = compute_max_drawdown(returns)
    if max_dd == 0:
        return 0.0
    return profit / max_dd


def compute_win_loss_ratio(returns: np.ndarray) -> float:
    """Compute win/loss ratio (number of wins / number of losses).

    Args:
        returns: Array of trade/period returns.

    Returns:
        Win/loss ratio (inf if no losses).
    """
    wins = np.sum(returns > 0)
    losses = np.sum(returns < 0)
    if losses == 0:
        return float("inf") if wins > 0 else 0.0
    return float(wins) / float(losses)
