from __future__ import annotations

from typing import Any

import pandas as pd
from sqlalchemy.orm import Session
from trademachine.tradingmonitor_analytics.metrics.calculator import (
    calculate_metrics_from_df,
    calculate_portfolio_metrics,
)
from trademachine.tradingmonitor_analytics.metrics.repository import (
    get_backtest_deals,
    get_backtest_equity,
    get_strategy_deals,
)
from trademachine.tradingmonitor_analytics.metrics.utils import combine_equity_series
from trademachine.tradingmonitor_analytics.services.dashboard_shared import (
    equity_points_from_deals as _equity_points_from_deals,
)
from trademachine.tradingmonitor_analytics.services.dashboard_shared import (
    synthetic_equity as _synthetic_equity,
)
from trademachine.tradingmonitor_storage.public import (
    Backtest,
    BacktestEquity,
    EquityCurve,
    Portfolio,
    Strategy,
)


class DashboardMetricsNotFoundError(LookupError):
    """Raised when a dashboard metrics resource cannot be found."""


class DashboardMetricsValidationError(ValueError):
    """Raised when a dashboard metrics request is semantically invalid."""


def _orm_equity_points(
    rows: list[EquityCurve] | list[BacktestEquity],
    *,
    id_field: str,
    id_getter: str,
) -> list[dict[str, Any]]:
    return [
        {
            "timestamp": row.timestamp,
            id_field: getattr(row, id_getter),
            "balance": float(row.balance),
            "equity": float(row.equity),
        }
        for row in rows
    ]


def _get_strategy_or_error(db: Session, strategy_id: str) -> Strategy:
    strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if strategy is None:
        raise DashboardMetricsNotFoundError("Strategy not found")
    return strategy


def _get_backtest_or_error(db: Session, backtest_id: int) -> Backtest:
    backtest = db.query(Backtest).filter(Backtest.id == backtest_id).first()
    if backtest is None:
        raise DashboardMetricsNotFoundError("Backtest not found")
    return backtest


def _get_portfolio_or_error(db: Session, portfolio_id: int) -> Portfolio:
    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if portfolio is None:
        raise DashboardMetricsNotFoundError("Portfolio not found")
    return portfolio


def _get_portfolio_strategy_ids(portfolio: Portfolio) -> list[str]:
    return [strategy.id for strategy in portfolio.strategies]


def _deal_type_for_side(side: str) -> str:
    return "BUY" if side == "buy" else "SELL"


def _inject_return(
    metrics: dict[str, Any], initial_balance: float | None
) -> dict[str, Any]:
    normalized_initial_balance = float(initial_balance or 0.0)
    if normalized_initial_balance > 0 and metrics.get("Profit") is not None:
        metrics["Return (%)"] = (
            float(metrics["Profit"]) / normalized_initial_balance * 100
        )
    else:
        metrics["Return (%)"] = None
    return metrics


def get_strategy_metrics_payload(
    db: Session,
    strategy_id: str,
    side: str | None = None,
) -> dict[str, Any]:
    strategy = _get_strategy_or_error(db, strategy_id)
    deals_df = get_strategy_deals(strategy_id)
    if side in {"buy", "sell"}:
        deals_df = deals_df[deals_df["type"] == _deal_type_for_side(side)]
    equity_df = _synthetic_equity(deals_df, balance_baseline=strategy.initial_balance)
    metrics = calculate_metrics_from_df(deals_df, equity_df)
    metrics = _inject_return(metrics, strategy.initial_balance)
    return metrics


def get_strategy_equity_payload(
    db: Session,
    strategy_id: str,
    side: str | None = None,
) -> list[dict[str, Any]]:
    _get_strategy_or_error(db, strategy_id)
    deals_df = get_strategy_deals(strategy_id)
    if side in {"buy", "sell"}:
        deals_df = deals_df[deals_df["type"] == _deal_type_for_side(side)]
    return _equity_points_from_deals(
        deals_df,
        balance_baseline=0,
        id_field="strategy_id",
        id_value=strategy_id,
    )


def get_backtest_metrics_payload(
    db: Session,
    backtest_id: int,
    side: str | None = None,
) -> dict[str, Any]:
    backtest = _get_backtest_or_error(db, backtest_id)
    deals_df = get_backtest_deals(backtest_id)
    if side in {"buy", "sell"}:
        deals_df = deals_df[deals_df["type"] == _deal_type_for_side(side)]
        equity_df = _synthetic_equity(
            deals_df, balance_baseline=backtest.initial_balance
        )
    else:
        equity_df = get_backtest_equity(backtest_id)
    metrics = calculate_metrics_from_df(deals_df, equity_df)
    metrics = _inject_return(metrics, backtest.initial_balance)
    return metrics


def get_backtest_equity_payload(
    db: Session,
    backtest_id: int,
    side: str | None = None,
) -> list[dict[str, Any]]:
    backtest = _get_backtest_or_error(db, backtest_id)
    if side in {"buy", "sell"}:
        deals_df = get_backtest_deals(backtest_id)
        deals_df = deals_df[deals_df["type"] == _deal_type_for_side(side)]
        return _equity_points_from_deals(
            deals_df,
            balance_baseline=backtest.initial_balance,
            id_field="backtest_id",
            id_value=backtest_id,
        )

    rows = (
        db.query(BacktestEquity)
        .filter(BacktestEquity.backtest_id == backtest_id)
        .order_by(BacktestEquity.timestamp)
        .all()
    )
    return _orm_equity_points(rows, id_field="backtest_id", id_getter="backtest_id")


def get_portfolio_metrics_payload(db: Session, portfolio_id: int) -> dict[str, Any]:
    portfolio = _get_portfolio_or_error(db, portfolio_id)
    strategy_ids = _get_portfolio_strategy_ids(portfolio)
    if not strategy_ids:
        raise DashboardMetricsValidationError("No strategies in this portfolio")
    metrics = calculate_portfolio_metrics(strategy_ids)
    metrics = _inject_return(metrics, portfolio.initial_balance)
    return metrics


def get_portfolio_equity_payload(
    db: Session, portfolio_id: int
) -> list[dict[str, Any]]:
    portfolio = _get_portfolio_or_error(db, portfolio_id)
    strategy_ids = _get_portfolio_strategy_ids(portfolio)
    if not strategy_ids:
        return []

    series: list[pd.Series] = []
    for strategy_id in strategy_ids:
        deals_df = get_strategy_deals(strategy_id)
        if not deals_df.empty:
            df = _synthetic_equity(deals_df)
            series.append(df["equity"].rename(strategy_id))
    if not series:
        return []

    combined = combine_equity_series(series).sum(axis=1)
    return [
        {"timestamp": timestamp, "equity": float(value)}
        for timestamp, value in combined.items()
    ]


def get_portfolio_equity_breakdown_payload(
    db: Session, portfolio_id: int
) -> dict[str, Any]:
    portfolio = _get_portfolio_or_error(db, portfolio_id)
    strategies = {
        strategy.id: strategy.name or strategy.id for strategy in portfolio.strategies
    }
    if not strategies:
        return {"total": [], "strategies": {}}

    series: dict[str, pd.Series] = {}
    for strategy_id in strategies:
        deals_df = get_strategy_deals(strategy_id)
        if not deals_df.empty:
            df = _synthetic_equity(deals_df)
            series[strategy_id] = df["equity"].rename(strategy_id)

    if not series:
        return {"total": [], "strategies": {}}

    combined_df = combine_equity_series(list(series.values()))
    total = combined_df.sum(axis=1)

    result_strategies: dict[str, dict[str, Any]] = {}
    for strategy_id, name in strategies.items():
        if strategy_id in series:
            column = combined_df[strategy_id]
            result_strategies[strategy_id] = {
                "name": name,
                "points": [
                    {"timestamp": timestamp, "equity": float(value)}
                    for timestamp, value in column.items()
                ],
            }

    return {
        "total": [
            {"timestamp": timestamp, "equity": float(value)}
            for timestamp, value in total.items()
        ],
        "strategies": result_strategies,
    }
