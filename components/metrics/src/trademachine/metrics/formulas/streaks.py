"""Streak and win-rate formulas."""

from __future__ import annotations


def max_consec_wins(pnls: list[float]) -> int:
    """Maximum number of consecutive winning trades."""
    best = current = 0
    for p in pnls:
        if p > 0:
            current += 1
            if current > best:
                best = current
        else:
            current = 0
    return best


def max_consec_losses(pnls: list[float]) -> int:
    """Maximum number of consecutive losing trades."""
    best = current = 0
    for p in pnls:
        if p < 0:
            current += 1
            if current > best:
                best = current
        else:
            current = 0
    return best
