"""Symmetry metrics: long vs short profit and trade comparisons."""

from __future__ import annotations

from trademachine.metrics.types import TradeRecord


def symmetry(trades: list[TradeRecord]) -> float | None:
    """Symmetry = long_profit - short_profit.

    Positive means longs outperform shorts. None if no trades.
    """
    if not trades:
        return None
    long_profit = sum(t.pnl for t in trades if t.side == "long")
    short_profit = sum(t.pnl for t in trades if t.side == "short")
    return long_profit - short_profit


def trades_symmetry(trades: list[TradeRecord]) -> float | None:
    """Trades Symmetry = long_count - short_count.

    Positive means more long trades. None if no trades.
    """
    if not trades:
        return None
    long_count = sum(1 for t in trades if t.side == "long")
    short_count = sum(1 for t in trades if t.side == "short")
    return float(long_count - short_count)


def nsymmetry(trades: list[TradeRecord]) -> int | None:
    """NSymmetry: -1 if one side profitable and the other losing, else 0.

    -1 = asymmetric (one side wins, other loses).
     0 = both sides profitable, both losing, or no data.
    None if no trades.
    """
    if not trades:
        return None
    long_pnl = sum(t.pnl for t in trades if t.side == "long")
    short_pnl = sum(t.pnl for t in trades if t.side == "short")
    long_trades = [t for t in trades if t.side == "long"]
    short_trades = [t for t in trades if t.side == "short"]
    if not long_trades or not short_trades:
        return 0
    if (long_pnl > 0) != (short_pnl > 0):
        return -1
    return 0
