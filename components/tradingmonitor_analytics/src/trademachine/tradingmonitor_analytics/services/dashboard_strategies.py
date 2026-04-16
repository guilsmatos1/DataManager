from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Literal

import numpy as np
import pandas as pd
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload
from trademachine.tradingmonitor_analytics.services.dashboard_shared import (
    compute_max_drawdown as _compute_max_drawdown,
)
from trademachine.tradingmonitor_analytics.services.dashboard_shared import (
    strategy_matches_history_type as _strategy_matches_history_type,
)
from trademachine.tradingmonitor_storage.api_schemas import StrategyResponse
from trademachine.tradingmonitor_storage.public import (
    Backtest,
    BacktestDeal,
    Deal,
    DealType,
    EquityCurve,
    Portfolio,
    Strategy,
    get_strategy_net_profit_map,
    get_strategy_trade_count_map,
)


class DashboardStrategiesNotFoundError(LookupError):
    """Raised when a requested strategy-related resource does not exist."""


def _compute_ret_dd(
    equity_points: list[tuple[datetime, float]], net_profit: float | None
) -> float | None:
    if net_profit is None or len(equity_points) < 2:
        return None

    timestamps = [
        timestamp if timestamp.tzinfo is not None else timestamp.replace(tzinfo=UTC)
        for timestamp, _ in equity_points
    ]
    equity_series = pd.Series(
        [equity for _, equity in equity_points],
        index=pd.DatetimeIndex(timestamps),
        dtype=float,
    ).sort_index()
    daily_equity = equity_series.resample("D").last().ffill().dropna()
    if len(daily_equity) < 2:
        return None

    daily_returns = daily_equity.pct_change().dropna()
    if len(daily_returns) < 2:
        return None

    returns = daily_returns.to_numpy(dtype=float)
    if not np.isfinite(returns).all():
        return None

    prices = np.concatenate([[1.0], np.cumprod(1 + returns)])
    peaks = np.maximum.accumulate(prices)
    safe_peaks = np.where(peaks > 0, peaks, 1.0)
    drawdown = float(np.max((peaks - prices) / safe_peaks))
    if drawdown == 0:
        return 0.0

    total_return = float(prices[-1]) - 1.0
    ret_dd = total_return / drawdown
    return -abs(ret_dd) if net_profit < 0 else abs(ret_dd)


def _strategy_ids_with_saved_runtime_history(db: Session) -> set[str]:
    deal_strategy_ids = {
        strategy_id
        for (strategy_id,) in (
            db.query(Deal.strategy_id)
            .filter(Deal.type.in_([DealType.BUY, DealType.SELL]))
            .distinct()
            .all()
        )
    }
    equity_strategy_ids = {
        strategy_id
        for (strategy_id,) in db.query(EquityCurve.strategy_id).distinct().all()
    }
    return deal_strategy_ids | equity_strategy_ids


def _strategy_ids_with_saved_backtest_history(db: Session) -> set[str]:
    backtest_deal_strategy_ids = {
        strategy_id
        for (strategy_id,) in (
            db.query(Backtest.strategy_id)
            .join(BacktestDeal, BacktestDeal.backtest_id == Backtest.id)
            .filter(or_(Backtest.status == "complete", Backtest.status.is_(None)))
            .distinct()
            .all()
        )
    }
    backtest_equity_strategy_ids = {
        strategy_id
        for (strategy_id,) in (
            db.query(Backtest.strategy_id)
            .join(BacktestDeal, BacktestDeal.backtest_id == Backtest.id, isouter=True)
            .filter(or_(Backtest.status == "complete", Backtest.status.is_(None)))
            .distinct()
            .all()
        )
    }
    return backtest_deal_strategy_ids | backtest_equity_strategy_ids


def _filter_strategies_by_history_type(
    db: Session,
    strategies: list[Strategy],
    history_type: Literal["backtest", "demo", "real"] | None,
) -> list[Strategy]:
    runtime_history_ids = (
        _strategy_ids_with_saved_runtime_history(db)
        if history_type in {"real", "demo"}
        else set()
    )
    backtest_history_ids = (
        _strategy_ids_with_saved_backtest_history(db)
        if history_type == "backtest"
        else set()
    )
    if history_type in {"real", "demo"}:
        return [
            strategy
            for strategy in strategies
            if _strategy_matches_history_type(strategy, history_type)
            and strategy.id in runtime_history_ids
        ]
    if history_type == "backtest":
        return [
            strategy for strategy in strategies if strategy.id in backtest_history_ids
        ]
    return strategies


def _build_strategy_responses(
    db: Session,
    strategies: list[Strategy],
) -> list[StrategyResponse]:
    strategy_ids = [strategy.id for strategy in strategies]
    if not strategy_ids:
        return []

    net_profits = get_strategy_net_profit_map(db, strategy_ids)
    backtest_net_profits: dict[str, float] = dict(
        db.query(
            Backtest.strategy_id,
            func.sum(BacktestDeal.profit + BacktestDeal.commission + BacktestDeal.swap),
        )
        .join(BacktestDeal, BacktestDeal.backtest_id == Backtest.id)
        .filter(Backtest.strategy_id.in_(strategy_ids))
        .filter(BacktestDeal.type.in_([DealType.BUY, DealType.SELL]))
        .group_by(Backtest.strategy_id)
        .all()
    )
    trades_counts = get_strategy_trade_count_map(db, strategy_ids)
    deal_range_rows = (
        db.query(
            Deal.strategy_id,
            func.max(Deal.timestamp).label("last_trade_at"),
            func.min(Deal.timestamp).label("first_trade_at"),
        )
        .filter(Deal.strategy_id.in_(strategy_ids))
        .filter(Deal.type.in_([DealType.BUY, DealType.SELL]))
        .group_by(Deal.strategy_id)
        .all()
    )
    last_trade_map = {row.strategy_id: row.last_trade_at for row in deal_range_rows}
    first_trade_map = {row.strategy_id: row.first_trade_at for row in deal_range_rows}

    equity_rows = (
        db.query(EquityCurve.strategy_id, EquityCurve.equity, EquityCurve.timestamp)
        .filter(EquityCurve.strategy_id.in_(strategy_ids))
        .order_by(EquityCurve.strategy_id, EquityCurve.timestamp)
        .all()
    )
    equity_by_strategy: dict[str, list[float]] = defaultdict(list)
    equity_points_by_strategy: dict[str, list[tuple[datetime, float]]] = defaultdict(
        list
    )
    last_seen_map: dict[str, datetime] = {}
    for row in equity_rows:
        equity_value = float(row.equity)
        equity_by_strategy[row.strategy_id].append(equity_value)
        equity_points_by_strategy[row.strategy_id].append((row.timestamp, equity_value))
        last_seen_map[row.strategy_id] = row.timestamp

    now_utc = datetime.now(UTC)
    result: list[StrategyResponse] = []
    for strategy in strategies:
        response = StrategyResponse.model_validate(strategy)
        response.account_name = strategy.account.name if strategy.account else None
        response.account_type = (
            strategy.account.account_type if strategy.account else None
        )

        raw_net_profit = net_profits.get(strategy.id)
        response.net_profit = (
            float(raw_net_profit) if raw_net_profit is not None else None
        )
        raw_backtest_profit = backtest_net_profits.get(strategy.id)
        response.backtest_net_profit = (
            float(raw_backtest_profit) if raw_backtest_profit is not None else None
        )
        response.trades_count = trades_counts.get(strategy.id)
        response.max_drawdown = _compute_max_drawdown(
            equity_by_strategy.get(strategy.id, [])
        )
        response.ret_dd = _compute_ret_dd(
            equity_points_by_strategy.get(strategy.id, []),
            response.net_profit,
        )
        response.last_seen_at = last_seen_map.get(strategy.id)
        response.last_trade_at = last_trade_map.get(strategy.id)

        response.zombie_alert = False
        if strategy.live and response.last_trade_at and response.trades_count:
            first_trade = first_trade_map.get(strategy.id)
            days_active = (
                max(1, (now_utc - first_trade.replace(tzinfo=UTC)).days)
                if first_trade
                else 1
            )
            avg_trades_per_day = response.trades_count / days_active
            if avg_trades_per_day >= 0.2:
                expected_interval_hours = 24.0 / avg_trades_per_day
                last_trade_aware = (
                    response.last_trade_at.replace(tzinfo=UTC)
                    if response.last_trade_at.tzinfo is None
                    else response.last_trade_at
                )
                hours_since = (now_utc - last_trade_aware).total_seconds() / 3600
                response.zombie_alert = hours_since > max(
                    48.0, expected_interval_hours * 2
                )

        result.append(response)

    return result


def list_strategies_payload(
    db: Session,
    history_type: Literal["backtest", "demo", "real"] | None = None,
) -> list[StrategyResponse]:
    strategies = db.query(Strategy).options(joinedload(Strategy.account)).all()
    strategies = _filter_strategies_by_history_type(db, strategies, history_type)
    return _build_strategy_responses(db, strategies)


def get_portfolio_strategies_payload(
    db: Session,
    portfolio_id: int,
) -> list[StrategyResponse]:
    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if portfolio is None:
        raise DashboardStrategiesNotFoundError("Portfolio not found")

    strategy_ids = [strategy.id for strategy in portfolio.strategies]
    if not strategy_ids:
        return []

    strategies = (
        db.query(Strategy)
        .options(joinedload(Strategy.account))
        .filter(Strategy.id.in_(strategy_ids))
        .all()
    )
    return _build_strategy_responses(db, strategies)
