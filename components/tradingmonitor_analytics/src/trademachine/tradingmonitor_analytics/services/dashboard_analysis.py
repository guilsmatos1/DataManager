from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Literal

import pandas as pd
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload
from trademachine.tradingmonitor_analytics.analysis.benchmarks import (
    benchmark_to_dict,
    load_benchmark_curve,
)
from trademachine.tradingmonitor_analytics.metrics.calculator import (
    calculate_metrics_from_df,
    calculate_portfolio_metrics,
)
from trademachine.tradingmonitor_analytics.metrics.repository import (
    get_backtest_deals,
    get_backtest_equity,
    get_strategy_deals,
    get_strategy_equity_curve,
)
from trademachine.tradingmonitor_analytics.metrics.utils import net_pnl
from trademachine.tradingmonitor_analytics.services.dashboard_shared import (
    closed_trades_for_side as _closed_trades_for_side,
)
from trademachine.tradingmonitor_analytics.services.dashboard_shared import (
    strategy_matches_history_type as _strategy_matches_history_type,
)
from trademachine.tradingmonitor_analytics.services.dashboard_shared import (
    synthetic_equity as _synthetic_equity,
)
from trademachine.tradingmonitor_storage.api_schemas import (
    BacktestResponse,
    PortfolioResponse,
)
from trademachine.tradingmonitor_storage.public import (
    Backtest,
    BacktestDeal,
    Benchmark,
    Deal,
    DealType,
    EquityCurve,
    Portfolio,
    Strategy,
    to_iso,
)

logger = logging.getLogger(__name__)


class DashboardAnalysisNotFoundError(LookupError):
    """Raised when a requested resource cannot be found."""


class DashboardAnalysisValidationError(ValueError):
    """Raised when request inputs are invalid for analysis."""


def _extract_profit(metrics: dict[str, object]) -> float | None:
    value = metrics.get("Profit")
    return float(value) if value is not None else None


def _normalize_series_to_base(series: pd.Series, base_value: float) -> pd.Series:
    if series.empty:
        return series
    first_value = float(series.iloc[0] or 0.0)
    if first_value == 0:
        return series
    return (series.astype(float) / first_value) * base_value


def _series_return_pct(series: pd.Series) -> float | None:
    if series.empty:
        return None
    first_value = float(series.iloc[0] or 0.0)
    last_value = float(series.iloc[-1] or 0.0)
    if first_value == 0:
        return None
    return ((last_value / first_value) - 1.0) * 100


def _series_max_drawdown_pct(series: pd.Series) -> float | None:
    if series.empty:
        return None
    values = [float(value) for value in series.tolist()]
    peak = values[0]
    max_drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - value) / peak)
    return max_drawdown * 100


def _series_correlation(series_a: pd.Series, series_b: pd.Series) -> float | None:
    if series_a.empty or series_b.empty:
        return None
    joined = pd.concat([series_a, series_b], axis=1, join="inner").dropna()
    if len(joined) < 3:
        return None
    returns = joined.pct_change().dropna()
    if len(returns) < 2:
        return None
    correlation = returns.iloc[:, 0].corr(returns.iloc[:, 1])
    return None if pd.isna(correlation) else float(correlation)


def _combine_equity_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame()
    combined = (
        pd.concat([frame["equity"] for frame in frames], axis=1)
        .sort_index()
        .ffill(limit=5)
        .fillna(0)
        .sum(axis=1)
    )
    return pd.DataFrame(combined, columns=["equity"])


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


def _build_comparison_curve(
    db: Session,
    chart_series: pd.Series,
    selected_benchmark: Benchmark | None,
    dt_from: datetime | None,
    dt_to: datetime | None,
    metrics: dict[str, object],
) -> list[dict[str, object]]:
    if selected_benchmark is None:
        return [
            {
                "timestamp": to_iso(timestamp),
                "portfolio": float(value),
                "benchmark": None,
            }
            for timestamp, value in chart_series.items()
        ]

    benchmark_df = load_benchmark_curve(
        db,
        selected_benchmark.id,
        date_from=dt_from,
        date_to=dt_to,
    )
    if benchmark_df.empty:
        metrics["Benchmark Status"] = "Selected benchmark has no synced local prices."
        return [
            {
                "timestamp": to_iso(timestamp),
                "portfolio": float(value),
                "benchmark": None,
            }
            for timestamp, value in chart_series.items()
        ]

    deduped_series = chart_series[~chart_series.index.duplicated(keep="last")]
    portfolio_start = deduped_series.index[0]
    portfolio_end = deduped_series.index[-1]
    first_equity = float(deduped_series.iloc[0])

    benchmark_close = benchmark_df["close"].astype(float)
    benchmark_in_range = benchmark_close.loc[portfolio_start:portfolio_end]
    scaled_benchmark = _normalize_series_to_base(benchmark_in_range, first_equity)

    joined = (
        pd.concat(
            [
                deduped_series.rename("portfolio"),
                scaled_benchmark.rename("benchmark"),
            ],
            axis=1,
            join="outer",
        )
        .sort_index()
        .ffill()
        .bfill()
        .loc[portfolio_start:portfolio_end]
    )

    benchmark_return = _series_return_pct(benchmark_df["close"].astype(float))
    benchmark_drawdown = _series_max_drawdown_pct(benchmark_df["close"].astype(float))
    portfolio_return = _series_return_pct(deduped_series)
    correlation = _series_correlation(
        deduped_series, benchmark_df["close"].astype(float)
    )

    metrics["Benchmark Return"] = benchmark_return
    metrics["Benchmark Drawdown"] = benchmark_drawdown
    metrics["Portfolio Return"] = portfolio_return
    metrics["Excess Return vs Benchmark"] = (
        portfolio_return - benchmark_return
        if portfolio_return is not None and benchmark_return is not None
        else None
    )
    metrics["Correlation vs Benchmark"] = correlation

    return [
        {
            "timestamp": to_iso(timestamp),
            "portfolio": float(row["portfolio"])
            if not pd.isna(row["portfolio"])
            else None,
            "benchmark": float(row["benchmark"])
            if not pd.isna(row["benchmark"])
            else None,
        }
        for timestamp, row in joined.iterrows()
    ]


def _apply_time_filter(
    df: pd.DataFrame, dt_from: datetime | None, dt_to: datetime | None
) -> pd.DataFrame:
    """Trim a DatetimeIndex DataFrame to [dt_from, dt_to]."""
    if df.empty:
        return df
    if dt_from is not None:
        df = df[df.index >= dt_from]
    if dt_to is not None:
        df = df[df.index <= dt_to]
    return df


def _load_backtest_frames(
    db: Session,
    selected_strategies: list[Strategy],
    dt_from: datetime | None,
    dt_to: datetime | None,
) -> tuple[list[pd.DataFrame], list[pd.DataFrame]]:
    backtests = (
        db.query(Backtest)
        .filter(Backtest.strategy_id.in_([s.id for s in selected_strategies]))
        .filter(or_(Backtest.status == "complete", Backtest.status.is_(None)))
        .all()
    )
    if not backtests:
        raise DashboardAnalysisValidationError(
            "No backtest history found for selected strategies."
        )

    deal_frames: list[pd.DataFrame] = []
    equity_frames: list[pd.DataFrame] = []
    for backtest in backtests:
        deals_df = get_backtest_deals(backtest.id)
        if not deals_df.empty:
            deals_df["strategy_id"] = backtest.strategy_id
        deals_df = _apply_time_filter(deals_df, dt_from, dt_to)
        if not deals_df.empty:
            deal_frames.append(deals_df)

        equity_df = _apply_time_filter(get_backtest_equity(backtest.id), dt_from, dt_to)
        if not equity_df.empty:
            equity_frames.append(equity_df)

    return deal_frames, equity_frames


def _load_live_frames(
    selected_strategies: list[Strategy],
    dt_from: datetime | None,
    dt_to: datetime | None,
) -> tuple[list[pd.DataFrame], list[pd.DataFrame]]:
    deal_frames: list[pd.DataFrame] = []
    equity_frames: list[pd.DataFrame] = []
    for strategy in selected_strategies:
        deals_df = get_strategy_deals(strategy.id, since=dt_from)
        deals_df = _apply_time_filter(deals_df, None, dt_to)
        if not deals_df.empty:
            deal_frames.append(deals_df)

        equity_df = _apply_time_filter(
            get_strategy_equity_curve(strategy.id), dt_from, dt_to
        )
        if not equity_df.empty:
            equity_frames.append(equity_df)

    return deal_frames, equity_frames


def _collect_deal_and_equity_frames(
    db: Session,
    history_type: str,
    selected_strategies: list[Strategy],
    dt_from: datetime | None,
    dt_to: datetime | None,
) -> tuple[list[pd.DataFrame], list[pd.DataFrame]]:
    if history_type == "backtest":
        return _load_backtest_frames(db, selected_strategies, dt_from, dt_to)
    return _load_live_frames(selected_strategies, dt_from, dt_to)


def _get_backtest_net_profit_map(
    db: Session, backtest_ids: list[int]
) -> dict[int, float]:
    if not backtest_ids:
        return {}
    return dict(
        db.query(
            BacktestDeal.backtest_id,
            func.sum(BacktestDeal.profit + BacktestDeal.commission + BacktestDeal.swap),
        )
        .filter(
            BacktestDeal.backtest_id.in_(backtest_ids),
            BacktestDeal.type.in_([DealType.BUY, DealType.SELL]),
        )
        .group_by(BacktestDeal.backtest_id)
        .all()
    )


def _inject_backtest_net_profit(
    backtest: Backtest,
    net_profit_map: dict[int, float],
) -> BacktestResponse:
    response = BacktestResponse.model_validate(backtest)
    net_profit = net_profit_map.get(backtest.id)
    response.net_profit = (
        round(float(net_profit), 2) if net_profit is not None else None
    )
    return response


def _calculate_backtest_portfolio_net_profit(
    db: Session, strategy_ids: list[str]
) -> float | None:
    all_deals: list[pd.DataFrame] = []
    all_equity: list[pd.DataFrame] = []

    for strategy_id in strategy_ids:
        backtest = (
            db.query(Backtest)
            .filter(Backtest.strategy_id == strategy_id, Backtest.status == "complete")
            .order_by(Backtest.created_at.desc())
            .first()
        )
        if backtest is None:
            continue

        deals_df = get_backtest_deals(backtest.id)
        equity_df = get_backtest_equity(backtest.id)
        if not deals_df.empty:
            all_deals.append(deals_df)
        if not equity_df.empty:
            all_equity.append(equity_df)

    if not all_deals:
        return None

    combined_deals = pd.concat(all_deals).sort_index()
    if all_equity:
        equity_combined_df = pd.concat(
            [frame["equity"] for frame in all_equity], axis=1
        ).sort_index()
        equity_combined_df = equity_combined_df.ffill(limit=5).fillna(0)
        portfolio_equity = equity_combined_df.sum(axis=1)
        combined_equity_df = pd.DataFrame(portfolio_equity, columns=["equity"])
    else:
        combined_equity_df = pd.DataFrame()

    metrics = calculate_metrics_from_df(combined_deals, combined_equity_df)
    return _extract_profit(metrics)


def list_portfolios_payload(
    db: Session,
    mode: Literal["backtest", "demo", "real"] = "demo",
) -> list[PortfolioResponse]:
    portfolios = db.query(Portfolio).options(joinedload(Portfolio.strategies)).all()

    results: list[PortfolioResponse] = []
    for portfolio in portfolios:
        strategy_ids = [strategy.id for strategy in portfolio.strategies]
        demo_strategy_ids = [
            strategy.id
            for strategy in portfolio.strategies
            if not strategy.real_account
        ]
        real_strategy_ids = [
            strategy.id for strategy in portfolio.strategies if strategy.real_account
        ]
        response = PortfolioResponse.from_orm_portfolio(portfolio)

        if strategy_ids:
            try:
                response.backtest_net_profit = _calculate_backtest_portfolio_net_profit(
                    db, strategy_ids
                )
                if demo_strategy_ids:
                    response.demo_net_profit = _extract_profit(
                        calculate_portfolio_metrics(demo_strategy_ids)
                    )
                if real_strategy_ids:
                    response.real_net_profit = _extract_profit(
                        calculate_portfolio_metrics(real_strategy_ids)
                    )

                if mode == "demo":
                    response.net_profit = response.demo_net_profit
                elif mode == "real":
                    response.net_profit = response.real_net_profit
                else:
                    response.net_profit = response.backtest_net_profit
            except (ValueError, KeyError, TypeError, ZeroDivisionError) as exc:
                logger.exception(
                    "Failed to calculate portfolio payload metrics for portfolio %s",
                    portfolio.id,
                )
                response.metrics_error = str(exc)

        results.append(response)

    return results


def list_strategy_backtests_payload(
    db: Session, strategy_id: str
) -> list[BacktestResponse]:
    strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if strategy is None:
        raise DashboardAnalysisNotFoundError("Strategy not found")

    backtests = (
        db.query(Backtest)
        .filter(Backtest.strategy_id == strategy_id)
        .order_by(Backtest.created_at.desc())
        .all()
    )
    net_profit_map = _get_backtest_net_profit_map(
        db, [backtest.id for backtest in backtests]
    )
    return [
        _inject_backtest_net_profit(backtest, net_profit_map) for backtest in backtests
    ]


def get_backtest_payload(db: Session, backtest_id: int) -> BacktestResponse:
    backtest = db.query(Backtest).filter(Backtest.id == backtest_id).first()
    if backtest is None:
        raise DashboardAnalysisNotFoundError("Backtest not found")
    net_profit_map = _get_backtest_net_profit_map(db, [backtest.id])
    return _inject_backtest_net_profit(backtest, net_profit_map)


def _filter_strategies_for_analysis(
    db: Session, strategies: list[Strategy], history_type: str
) -> list[Strategy]:
    if history_type in {"real", "demo"}:
        runtime_ids = _strategy_ids_with_saved_runtime_history(db)
        filtered = [
            s
            for s in strategies
            if _strategy_matches_history_type(s, history_type) and s.id in runtime_ids
        ]
        if not filtered:
            raise DashboardAnalysisValidationError(
                f"No selected strategies with saved {history_type} history."
            )
        return filtered
    if history_type == "backtest":
        backtest_ids = _strategy_ids_with_saved_backtest_history(db)
        filtered = [s for s in strategies if s.id in backtest_ids]
        if not filtered:
            raise DashboardAnalysisValidationError(
                "No backtest history found for selected strategies."
            )
        return filtered
    return strategies


def _resolve_benchmark(db: Session, benchmark_id: int | None) -> Benchmark | None:
    if benchmark_id is not None:
        bm = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
        if bm is None:
            raise DashboardAnalysisNotFoundError("Benchmark not found.")
        return bm
    return db.query(Benchmark).filter(Benchmark.is_default.is_(True)).first()


def _compute_combined_equity(
    deal_frames: list[pd.DataFrame],
    equity_frames: list[pd.DataFrame],
    side: str | None,
    initial_balance: float | None,
) -> pd.DataFrame:
    combined_deals = pd.concat(deal_frames).sort_index()
    if side in {"buy", "sell"}:
        combined_deals = _closed_trades_for_side(combined_deals, side)
    return combined_deals, _synthetic_equity(
        combined_deals, balance_baseline=initial_balance
    )


def _build_per_strategy_equity(
    deal_frames: list[pd.DataFrame],
    strategy_name_map: dict[str, str],
    side: str | None,
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for df in deal_frames:
        if df.empty or "strategy_id" not in df.columns:
            continue
        sid = str(df["strategy_id"].iloc[0])
        filtered = df
        if side in {"buy", "sell"}:
            filtered = _closed_trades_for_side(df, side)
        if filtered.empty:
            continue
        equity_df = _synthetic_equity(filtered)
        points = [
            {"timestamp": to_iso(ts), "equity": float(v)}
            for ts, v in equity_df["equity"].items()
        ]
        result.append(
            {
                "strategy_id": sid,
                "name": strategy_name_map.get(sid, sid),
                "points": points,
            }
        )
    return result


def _build_daily_pnl(combined_deals: pd.DataFrame) -> list[dict[str, object]]:
    if combined_deals.empty:
        return []
    net = net_pnl(combined_deals)
    daily = net.groupby(combined_deals.index.date).sum()
    return [
        {"date": str(d), "net_profit": round(float(v), 2)}
        for d, v in sorted(daily.items())
    ]


def _build_trade_stats(
    combined_deals: pd.DataFrame,
) -> dict[str, list[dict[str, object]]]:
    dow_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    by_hour = [{"hour": h, "count": 0, "net_profit": 0.0} for h in range(24)]
    by_dow = [
        {"dow": i + 1, "label": dow_labels[i], "count": 0, "net_profit": 0.0}
        for i in range(7)
    ]
    if combined_deals.empty:
        return {"by_hour": by_hour, "by_dow": by_dow}

    net = net_pnl(combined_deals)
    hours = combined_deals.index.hour
    for hour in range(24):
        mask = hours == hour
        by_hour[hour] = {
            "hour": hour,
            "count": int(mask.sum()),
            "net_profit": round(float(net[mask].sum()), 2),
        }

    weekdays = combined_deals.index.weekday  # Monday=0
    for wd in range(7):
        mask = weekdays == wd
        by_dow[wd] = {
            "dow": wd + 1,
            "label": dow_labels[wd],
            "count": int(mask.sum()),
            "net_profit": round(float(net[mask].sum()), 2),
        }

    return {"by_hour": by_hour, "by_dow": by_dow}


def _build_strategy_contributions(
    combined_deals: pd.DataFrame, strategy_name_map: dict[str, str]
) -> list[dict[str, object]]:
    if combined_deals.empty or "strategy_id" not in combined_deals.columns:
        return []
    grouped = combined_deals.groupby("strategy_id")["profit"].sum()
    return [
        {
            "strategy_id": sid,
            "name": strategy_name_map.get(sid, sid),
            "profit": round(float(profit), 2),
        }
        for sid, profit in grouped.items()
    ]


def get_advanced_analysis_payload(
    db: Session,
    *,
    strategy_ids: list[str],
    history_type: str,
    date_from: str | None,
    date_to: str | None,
    initial_balance: float | None,
    benchmark_id: int | None,
    side: str | None,
) -> dict[str, Any]:
    if not strategy_ids:
        raise DashboardAnalysisValidationError("Select at least one strategy.")

    normalized_history_type = history_type.lower()
    if normalized_history_type not in {"backtest", "demo", "real"}:
        raise DashboardAnalysisValidationError(
            "history_type must be one of backtest, demo, real."
        )

    dt_from = (
        datetime.fromisoformat(date_from).replace(tzinfo=UTC) if date_from else None
    )
    dt_to = datetime.fromisoformat(date_to).replace(tzinfo=UTC) if date_to else None

    strategies = (
        db.query(Strategy)
        .options(joinedload(Strategy.account))
        .filter(Strategy.id.in_(strategy_ids))
        .all()
    )
    if not strategies:
        raise DashboardAnalysisNotFoundError("Strategies not found.")

    selected_strategies = _filter_strategies_for_analysis(
        db, strategies, normalized_history_type
    )
    deal_frames, equity_frames = _collect_deal_and_equity_frames(
        db, normalized_history_type, selected_strategies, dt_from, dt_to
    )
    selected_benchmark = _resolve_benchmark(db, benchmark_id)

    if not deal_frames:
        return {
            "metrics": {"error": "No trades found."},
            "equity_curve": [],
            "comparison_curve": [],
            "benchmark": benchmark_to_dict(db, selected_benchmark)
            if selected_benchmark
            else None,
            "selected_strategies": [s.id for s in selected_strategies],
            "history_type": normalized_history_type,
            "strategy_contributions": [],
        }

    combined_deals, combined_equity = _compute_combined_equity(
        deal_frames, equity_frames, side, initial_balance
    )

    metrics = calculate_metrics_from_df(combined_deals, combined_equity, advanced=True)
    if initial_balance and metrics.get("Profit") is not None:
        metrics["Return on Capital (%)"] = (metrics["Profit"] / initial_balance) * 100

    equity_curve: list[dict[str, object]] = []
    comparison_curve: list[dict[str, object]] = []
    if not combined_equity.empty:
        equity_curve = [
            {"timestamp": to_iso(ts), "equity": float(v)}
            for ts, v in combined_equity["equity"].items()
        ]
        chart_series = combined_equity["equity"].astype(float)
        comparison_curve = _build_comparison_curve(
            db, chart_series, selected_benchmark, dt_from, dt_to, metrics
        )

    strategy_name_map = {s.id: s.name or s.id for s in selected_strategies}
    daily_pnl = _build_daily_pnl(combined_deals)
    trade_stats = _build_trade_stats(combined_deals)
    per_strategy_equity = _build_per_strategy_equity(
        deal_frames, strategy_name_map, side
    )
    return {
        "metrics": metrics,
        "equity_curve": equity_curve,
        "comparison_curve": comparison_curve,
        "benchmark": benchmark_to_dict(db, selected_benchmark)
        if selected_benchmark
        else None,
        "selected_strategies": [s.id for s in selected_strategies],
        "history_type": normalized_history_type,
        "strategy_contributions": _build_strategy_contributions(
            combined_deals, strategy_name_map
        ),
        "daily_pnl": daily_pnl,
        "trade_stats": trade_stats,
        "per_strategy_equity": per_strategy_equity,
    }


def get_portfolio_contributions_payload(
    db: Session,
    strategies: list[Strategy],
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, dict[str, float]]:
    strategy_ids = [s.id for s in strategies]
    if not strategy_ids:
        return {"positive": {}, "negative": {}}

    query = db.query(
        Deal.strategy_id, func.sum(Deal.profit).label("total_profit")
    ).filter(Deal.strategy_id.in_(strategy_ids))
    if date_from is not None:
        query = query.filter(Deal.timestamp >= date_from)
    if date_to is not None:
        query = query.filter(Deal.timestamp <= date_to)

    rows = query.group_by(Deal.strategy_id).all()
    profit_map = {row.strategy_id: float(row.total_profit or 0.0) for row in rows}

    per_strategy: dict[str, float] = {}
    for s in strategies:
        label = s.name or s.id
        per_strategy[label] = profit_map.get(s.id, 0.0)

    positive = {k: v for k, v in per_strategy.items() if v > 0}
    negative = {k: v for k, v in per_strategy.items() if v < 0}

    total_pos = sum(positive.values()) if positive else 0.0
    total_neg = sum(abs(v) for v in negative.values()) if negative else 0.0

    pos_pct = (
        {k: round(v / total_pos * 100, 2) for k, v in positive.items()}
        if total_pos > 0
        else {}
    )
    neg_pct = (
        {k: round(abs(v) / total_neg * 100, 2) for k, v in negative.items()}
        if total_neg > 0
        else {}
    )

    return {"positive": pos_pct, "negative": neg_pct}
