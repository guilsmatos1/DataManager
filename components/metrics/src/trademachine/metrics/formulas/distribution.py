"""Distribution metrics: Z-Score, Z-Probability, Deviation, Stability."""

from __future__ import annotations

import math


def deviation(pnls: list[float]) -> float | None:
    """Deviation = average absolute difference between each P&L and the mean trade.

    None if fewer than 2 trades.
    """
    n = len(pnls)
    if n < 2:
        return None
    mean = sum(pnls) / n
    return sum(abs(p - mean) for p in pnls) / n


def z_score(pnls: list[float]) -> float | None:
    """Z-Score = (mean_trade - 0) / (std_dev / sqrt(n)).

    Measures how many standard errors the average trade is from zero.
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
    return mean / (std / math.sqrt(n))


def z_probability(pnls: list[float]) -> float | None:
    """Z-Probability = P(Z <= z_score) using the standard normal CDF.

    Uses math.erf approximation — no scipy dependency.
    Returns a value in [0, 1]. None if z_score is None.
    """
    z = z_score(pnls)
    if z is None:
        return None
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def stability(equity: list[float]) -> float | None:
    """Stability = R² of a linear regression on the equity curve.

    Measures how straight the equity curve is (1.0 = perfect straight line).
    None if fewer than 2 equity points or variance is zero.
    """
    n = len(equity)
    if n < 2:
        return None
    xs = list(range(n))
    mean_x = (n - 1) / 2.0
    mean_y = sum(equity) / n
    ss_xx = sum((x - mean_x) ** 2 for x in xs)
    ss_yy = sum((y - mean_y) ** 2 for y in equity)
    if ss_xx == 0 or ss_yy == 0:
        return None
    ss_xy = sum((xs[i] - mean_x) * (equity[i] - mean_y) for i in range(n))
    r_squared = (ss_xy**2) / (ss_xx * ss_yy)
    return r_squared
