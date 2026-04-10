"""Canonical input/output types for the metrics component."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Side = Literal["long", "short"]


class TradeRecord(BaseModel):
    """A single closed trade."""

    entry_time: datetime
    exit_time: datetime
    pnl: float
    side: Side


class EquityPoint(BaseModel):
    """A point on the equity curve."""

    timestamp: datetime
    equity: float


class MetricsResult(BaseModel):
    """Unified metrics output. All fields optional until PRs 2-4 implement them."""

    # Profit
    total_profit: float | None = None
    gross_profit: float | None = None
    gross_loss: float | None = None
    average_win: float | None = None
    average_loss: float | None = None
    average_trade: float | None = None
    daily_avg_profit: float | None = None
    monthly_avg_profit: float | None = None
    yearly_avg_profit: float | None = None

    # Returns
    yearly_avg_return_pct: float | None = None
    cagr: float | None = None
    annual_over_maxdd: float | None = None

    # Ratios
    profit_factor: float | None = None
    return_dd_ratio: float | None = None
    payout_ratio: float | None = None
    wins_losses_ratio: float | None = None
    winning_pct: float | None = None

    # Drawdown
    drawdown: float | None = None
    drawdown_pct: float | None = None
    stagnation_days: int | None = None
    stagnation_pct: float | None = None

    # Risk
    expectancy: float | None = None
    r_expectancy: float | None = None
    r_expectancy_score: float | None = None
    sqn: float | None = None
    sqn_score: float | None = None

    # Distribution
    deviation: float | None = None
    z_score: float | None = None
    z_probability: float | None = None
    stability: float | None = None

    # Streaks
    max_consec_wins: int | None = None
    max_consec_losses: int | None = None

    # Symmetry
    symmetry: float | None = None
    trades_symmetry: float | None = None
    nsymmetry: int | None = None

    # Exposure
    exposure: float | None = None

    model_config = {"frozen": True}


class MetricsInput(BaseModel):
    """Bundle of inputs consumed by the metrics engine."""

    trades: list[TradeRecord]
    equity: list[EquityPoint]
    initial_capital: float = Field(gt=0)
    risk_per_trade: float | None = None
