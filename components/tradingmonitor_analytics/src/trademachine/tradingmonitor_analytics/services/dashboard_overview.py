from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import numpy as np
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload
from trademachine.tradingmonitor_analytics.services.dashboard_shared import (
    compute_max_drawdown as _compute_max_drawdown,
)
from trademachine.tradingmonitor_analytics.services.dashboard_shared import (
    strategy_matches_history_type as _strategy_matches_history_type,
)
from trademachine.tradingmonitor_storage.api_schemas import (
    AccountResponse,
    SummaryResponse,
    SymbolResponse,
)
from trademachine.tradingmonitor_storage.public import (
    Account,
    Deal,
    DealType,
    EquityCurve,
    Portfolio,
    Strategy,
    StrategyRuntimeSnapshot,
    Symbol,
    get_setting_str,
    get_strategy_daily_profit_rows,
    get_strategy_intraday_profit_map,
    get_strategy_net_profit_map,
    to_iso,
)

REAL_OVERVIEW_TIMEZONE = ZoneInfo("Europe/Athens")


def _get_net_profits(db: Session, strategy_ids: list[str]) -> dict[str, float]:
    return get_strategy_net_profit_map(db, strategy_ids)


def _get_intraday_net_profits(
    db: Session,
    strategy_ids: list[str],
    now_utc: datetime | None = None,
) -> dict[str, float]:
    if not strategy_ids:
        return {}

    now_utc = now_utc or datetime.now(UTC)
    now_local = now_utc.astimezone(REAL_OVERVIEW_TIMEZONE)
    day_start_local = datetime(
        now_local.year,
        now_local.month,
        now_local.day,
        tzinfo=REAL_OVERVIEW_TIMEZONE,
    )
    day_start_utc = day_start_local.astimezone(UTC)

    return get_strategy_intraday_profit_map(
        db,
        strategy_ids=strategy_ids,
        day_start_utc=day_start_utc,
        now_utc=now_utc,
    )


def _append_current_local_day_point(
    rows: list[dict[str, object]],
    *,
    timezone: ZoneInfo,
    now_utc: datetime | None = None,
) -> list[dict[str, object]]:
    if not rows:
        return rows

    current_local_day = (
        (now_utc or datetime.now(UTC)).astimezone(timezone).date().isoformat()
    )
    if any(str(row.get("date")) == current_local_day for row in rows):
        return rows

    rows_with_today = [*rows]
    rows_with_today.append(
        {
            "date": current_local_day,
            "net_profit": 0.0,
            "trades_count": 0,
        }
    )
    rows_with_today.sort(key=lambda row: str(row["date"]))
    return rows_with_today


def _get_latest_equity(db: Session, strategy_ids: list[str]) -> dict[str, EquityCurve]:
    subquery = (
        db.query(
            EquityCurve.strategy_id, func.max(EquityCurve.timestamp).label("latest_ts")
        )
        .filter(EquityCurve.strategy_id.in_(strategy_ids))
        .group_by(EquityCurve.strategy_id)
        .subquery()
    )
    rows = (
        db.query(EquityCurve)
        .join(
            subquery,
            (EquityCurve.strategy_id == subquery.c.strategy_id)
            & (EquityCurve.timestamp == subquery.c.latest_ts),
        )
        .all()
    )
    return {str(row.strategy_id): row for row in rows}


def _get_latest_runtime_snapshots(
    db: Session, strategy_ids: list[str]
) -> dict[str, StrategyRuntimeSnapshot]:
    if not strategy_ids:
        return {}
    rows = (
        db.query(StrategyRuntimeSnapshot)
        .filter(StrategyRuntimeSnapshot.strategy_id.in_(strategy_ids))
        .all()
    )
    return {str(row.strategy_id): row for row in rows}


def _get_equity_by_sid(
    db: Session,
    strategy_ids: list[str],
    max_points_per_strategy: int,
) -> dict[str, list[dict[str, object]]]:
    if not strategy_ids:
        return {}

    ranked_rows = (
        db.query(
            EquityCurve.strategy_id.label("strategy_id"),
            EquityCurve.timestamp.label("timestamp"),
            EquityCurve.balance.label("balance"),
            EquityCurve.equity.label("equity"),
            func.row_number()
            .over(
                partition_by=EquityCurve.strategy_id,
                order_by=EquityCurve.timestamp.desc(),
            )
            .label("rn"),
        )
        .filter(EquityCurve.strategy_id.in_(strategy_ids))
        .subquery()
    )

    rows = (
        db.query(ranked_rows)
        .filter(ranked_rows.c.rn <= max_points_per_strategy)
        .order_by(ranked_rows.c.strategy_id, ranked_rows.c.timestamp)
        .all()
    )
    result: dict[str, list[dict[str, object]]] = {
        strategy_id: [] for strategy_id in strategy_ids
    }
    for row in rows:
        result[str(row.strategy_id)].append(
            {
                "ts": to_iso(row.timestamp),
                "balance": float(row.balance),
                "equity": float(row.equity),
            }
        )
    return result


def _compute_var(equity_series: list[float], percentile: float = 95) -> float | None:
    if len(equity_series) < 5:
        return None

    equity_array = np.asarray(equity_series, dtype=float)
    previous_equity = equity_array[:-1]
    returns = np.divide(
        np.diff(equity_array),
        previous_equity,
        out=np.full(previous_equity.shape, np.nan, dtype=float),
        where=(previous_equity != 0) & np.isfinite(previous_equity),
    )
    returns = returns[np.isfinite(returns)]
    if len(returns) < 5:
        return None

    var = -np.percentile(returns, 100 - percentile)
    return float(var)


def _load_real_page_mode(db: Session) -> str:
    return get_setting_str(db, "real_page_mode", default="real")


def _load_overview_strategies(db: Session, real_page_mode: str) -> list[Strategy]:
    return [
        strategy
        for strategy in db.query(Strategy).options(joinedload(Strategy.account)).all()
        if _strategy_matches_history_type(strategy, real_page_mode)
    ]


def get_summary_payload(db: Session) -> SummaryResponse:
    strategies = db.query(Strategy).all()
    portfolios_count = db.query(Portfolio).count()
    accounts_count = db.query(Account).count()

    by_symbol: dict[str, int] = {}
    by_style: dict[str, int] = {}
    by_duration: dict[str, int] = {}

    for strategy in strategies:
        symbol = strategy.symbol or "Unknown"
        style = strategy.operational_style or "Unknown"
        duration = strategy.trade_duration or "Unknown"
        by_symbol[symbol] = by_symbol.get(symbol, 0) + 1
        by_style[style] = by_style.get(style, 0) + 1
        by_duration[duration] = by_duration.get(duration, 0) + 1

    return SummaryResponse(
        strategies_count=len(strategies),
        portfolios_count=portfolios_count,
        accounts_count=accounts_count,
        by_symbol=by_symbol,
        by_style=by_style,
        by_duration=by_duration,
    )


def get_real_overview_payload(
    db: Session,
    *,
    max_points_per_strategy: int,
) -> dict[str, object]:
    real_page_mode = _load_real_page_mode(db)
    overview_strategies = _load_overview_strategies(db, real_page_mode)
    if not overview_strategies:
        return {
            "mode": real_page_mode,
            "strategies": [],
            "totals": {
                "net_profit": 0.0,
                "floating_pnl": 0.0,
                "day_pnl": 0.0,
                "open_trades_count": None,
                "pending_orders_count": None,
                "counts_available": False,
            },
        }

    strategy_ids = [str(strategy.id) for strategy in overview_strategies]
    net_profit_map = _get_net_profits(db, strategy_ids)
    day_net_profit_map = _get_intraday_net_profits(db, strategy_ids)
    latest_equity_map = _get_latest_equity(db, strategy_ids)
    runtime_map = _get_latest_runtime_snapshots(db, strategy_ids)
    equity_by_sid = _get_equity_by_sid(
        db,
        strategy_ids,
        max_points_per_strategy=max_points_per_strategy,
    )

    result = []
    total_net_profit = 0.0
    total_floating_pnl = 0.0
    total_day_pnl = 0.0
    total_open_trades = 0
    total_pending_orders = 0
    counts_available = False

    for strategy in overview_strategies:
        strategy_id = str(strategy.id)
        net_profit = net_profit_map.get(strategy_id, 0.0)
        day_net_profit = day_net_profit_map.get(strategy_id, 0.0)
        latest_equity = latest_equity_map.get(strategy_id)
        runtime = runtime_map.get(strategy_id)
        balance = float(latest_equity.balance) if latest_equity else None
        equity = float(latest_equity.equity) if latest_equity else None
        open_trades_count = runtime.open_trades_count if runtime else None
        pending_orders_count = runtime.pending_orders_count if runtime else None
        floating_pnl = (
            float(runtime.open_profit)
            if runtime is not None and runtime.open_profit is not None
            else (
                (equity - balance)
                if (equity is not None and balance is not None)
                else 0.0
            )
        )

        equity_series = [
            float(str(point["equity"])) for point in equity_by_sid.get(strategy_id, [])
        ]
        max_drawdown = _compute_max_drawdown(equity_series)
        var_95 = _compute_var(equity_series, percentile=95)

        ret_dd = None
        initial_balance = (
            float(strategy.initial_balance) if strategy.initial_balance else None
        )
        if (
            max_drawdown
            and max_drawdown > 0
            and initial_balance
            and initial_balance > 0
        ):
            ret_dd = round(net_profit / (abs(max_drawdown) * initial_balance), 3)

        result.append(
            {
                "id": strategy.id,
                "name": strategy.name,
                "symbol": strategy.symbol,
                "net_profit": round(net_profit, 2),
                "day_pnl": round(day_net_profit, 2),
                "open_trades_count": open_trades_count,
                "pending_orders_count": pending_orders_count,
                "max_drawdown_pct": round(max_drawdown * 100, 2)
                if max_drawdown is not None
                else None,
                "var_95_pct": round(var_95 * 100, 2) if var_95 is not None else None,
                "ret_dd": ret_dd,
                "floating_pnl": round(floating_pnl, 2),
                "balance": round(balance, 2) if balance is not None else None,
                "equity": round(equity, 2) if equity is not None else None,
                "initial_balance": initial_balance,
                "last_update": to_iso(latest_equity.timestamp)
                if latest_equity
                else None,
                "equity_curve": equity_by_sid.get(strategy_id, []),
            }
        )
        total_net_profit += net_profit
        total_floating_pnl += floating_pnl
        total_day_pnl += day_net_profit
        if open_trades_count is not None and pending_orders_count is not None:
            total_open_trades += open_trades_count
            total_pending_orders += pending_orders_count
            counts_available = True

    return {
        "mode": real_page_mode,
        "strategies": result,
        "totals": {
            "net_profit": round(total_net_profit, 2),
            "floating_pnl": round(total_floating_pnl, 2),
            "day_pnl": round(total_day_pnl, 2),
            "open_trades_count": total_open_trades if counts_available else None,
            "pending_orders_count": total_pending_orders if counts_available else None,
            "counts_available": counts_available,
        },
    }


def get_real_daily_payload(
    db: Session, *, now_utc: datetime | None = None
) -> list[dict[str, object]]:
    real_page_mode = _load_real_page_mode(db)
    overview_strategies = _load_overview_strategies(db, real_page_mode)
    if not overview_strategies:
        return []

    strategy_ids = [str(strategy.id) for strategy in overview_strategies]
    rows = get_strategy_daily_profit_rows(
        db,
        strategy_ids,
        timezone=REAL_OVERVIEW_TIMEZONE,
    )
    return _append_current_local_day_point(
        rows,
        timezone=REAL_OVERVIEW_TIMEZONE,
        now_utc=now_utc,
    )


def get_real_recent_deals_payload(
    db: Session, *, limit: int
) -> list[dict[str, object]]:
    real_page_mode = _load_real_page_mode(db)
    overview_strategies = _load_overview_strategies(db, real_page_mode)
    if not overview_strategies:
        return []

    strategy_by_id = {str(strategy.id): strategy for strategy in overview_strategies}
    deals = (
        db.query(Deal)
        .filter(Deal.strategy_id.in_(list(strategy_by_id.keys())))
        .filter(Deal.type.in_([DealType.BUY, DealType.SELL]))
        .order_by(Deal.timestamp.desc(), Deal.ticket.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "timestamp": to_iso(deal.timestamp),
            "ticket": int(deal.ticket),
            "strategy_id": str(deal.strategy_id),
            "strategy_name": strategy_by_id[str(deal.strategy_id)].name,
            "symbol": deal.symbol,
            "type": deal.type.value if deal.type else "",
            "profit": float(deal.profit or 0),
            "commission": float(deal.commission or 0),
            "swap": float(deal.swap or 0),
            "net_profit": float(
                (deal.profit or 0) + (deal.commission or 0) + (deal.swap or 0)
            ),
        }
        for deal in deals
    ]


def list_accounts_payload(db: Session) -> list[AccountResponse]:
    accounts = db.query(Account).all()
    net_profits: dict[str | None, float] = dict(
        db.query(
            Strategy.account_id,
            func.sum(Deal.profit + Deal.commission + Deal.swap),
        )
        .join(Deal, Deal.strategy_id == Strategy.id)
        .filter(Deal.type.in_([DealType.BUY, DealType.SELL]))
        .filter(Strategy.account_id.isnot(None))
        .group_by(Strategy.account_id)
        .all()
    )
    result = []
    for a in accounts:
        r = AccountResponse.model_validate(a)
        raw = net_profits.get(a.id)
        r.net_profit = float(raw) if raw is not None else None
        result.append(r)
    return result


def get_floating_pnl_payload(db: Session) -> dict:
    latest_ts = (
        db.query(
            EquityCurve.strategy_id,
            func.max(EquityCurve.timestamp).label("max_ts"),
        )
        .group_by(EquityCurve.strategy_id)
        .subquery()
    )
    rows = (
        db.query(
            EquityCurve.strategy_id,
            EquityCurve.balance,
            EquityCurve.equity,
            Strategy.name,
        )
        .join(
            latest_ts,
            (EquityCurve.strategy_id == latest_ts.c.strategy_id)
            & (EquityCurve.timestamp == latest_ts.c.max_ts),
        )
        .join(Strategy, Strategy.id == EquityCurve.strategy_id)
        .all()
    )
    result = []
    total_floating = 0.0
    for row in rows:
        floating = float(row.equity) - float(row.balance)
        total_floating += floating
        result.append(
            {
                "strategy_id": row.strategy_id,
                "strategy_name": row.name,
                "balance": float(row.balance),
                "equity": float(row.equity),
                "floating_pnl": floating,
            }
        )
    result.sort(key=lambda x: abs(x["floating_pnl"]), reverse=True)
    return {"total_floating_pnl": total_floating, "positions": result}


def list_symbols_payload(db: Session) -> list[SymbolResponse]:
    strat_counts = (
        db.query(Strategy.symbol_id, func.count(Strategy.id).label("count"))
        .group_by(Strategy.symbol_id)
        .subquery()
    )
    symbols_data = (
        db.query(
            Symbol,
            func.coalesce(strat_counts.c.count, 0).label("strategies_count"),
        )
        .outerjoin(strat_counts, Symbol.id == strat_counts.c.symbol_id)
        .order_by(Symbol.market, Symbol.name)
        .all()
    )
    result = []
    for sym, count in symbols_data:
        resp = SymbolResponse.model_validate(sym)
        resp.strategies_count = count
        result.append(resp)
    return result
