"""Metrics engine — orchestrates formula calls. Stub for PR1."""

from __future__ import annotations

from trademachine.metrics.types import (
    EquityPoint,
    MetricsInput,
    MetricsResult,
    TradeRecord,
)


def compute_all(
    trades: list[TradeRecord],
    equity: list[EquityPoint],
    initial_capital: float,
    risk_per_trade: float | None = None,
) -> MetricsResult:
    """Compute every supported metric. Formulas land in PRs 2-4."""
    _ = MetricsInput(
        trades=trades,
        equity=equity,
        initial_capital=initial_capital,
        risk_per_trade=risk_per_trade,
    )
    return MetricsResult()


def compute_subset(
    trades: list[TradeRecord],
    equity: list[EquityPoint],
    initial_capital: float,
    metrics: set[str],
    risk_per_trade: float | None = None,
) -> dict[str, float | int | None]:
    """Compute only the requested metric names."""
    result = compute_all(trades, equity, initial_capital, risk_per_trade)
    dumped = result.model_dump()
    return {name: dumped[name] for name in metrics if name in dumped}
