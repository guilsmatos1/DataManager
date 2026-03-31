import csv
import hashlib
import io
import logging
import math
from datetime import UTC, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from bs4 import BeautifulSoup
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Security,
    UploadFile,
)
from fastapi.responses import StreamingResponse
from fastapi.security import APIKeyHeader
from sqlalchemy import cast, extract, func, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.types import Date, String
from trademachine.mt5.parser import (
    _EN_TO_PT_COLUMNS,
    MT5ReportParser,
)
from trademachine.tradingmonitor.analysis.benchmarks import (
    benchmark_to_dict,
    list_remote_databases,
    load_benchmark_curve,
    set_default_benchmark,
    sync_benchmark_from_datamanager,
)
from trademachine.tradingmonitor.api_schemas import (
    AccountResponse,
    AccountUpdate,
    BacktestDealResponse,
    BacktestEquityPointResponse,
    BacktestResponse,
    BenchmarkCreate,
    BenchmarkRemoteDatabaseResponse,
    BenchmarkResponse,
    BenchmarkUpdate,
    DataManagerSettings,
    DealResponse,
    EquityPointResponse,
    PaginatedBacktestDeals,
    PaginatedDeals,
    PortfolioCreate,
    PortfolioResponse,
    PortfolioUpdate,
    StrategyResponse,
    StrategyUpdate,
    SummaryResponse,
    SymbolCreate,
    SymbolResponse,
    SymbolUpdate,
    TelegramSettings,
)
from trademachine.tradingmonitor.config import settings
from trademachine.tradingmonitor.db.database import get_db
from trademachine.tradingmonitor.db.models import (
    Account,
    Backtest,
    BacktestDeal,
    BacktestEquity,
    Benchmark,
    Deal,
    DealType,
    EquityCurve,
    Portfolio,
    Setting,
    Strategy,
    StrategyRuntimeSnapshot,
    Symbol,
)
from trademachine.tradingmonitor.db.repository import to_iso
from trademachine.tradingmonitor.ingestion.tcp_server import (
    invalidate_cache,
    send_kill_command,
)

logger = logging.getLogger(__name__)
REAL_OVERVIEW_MAX_POINTS_PER_STRATEGY = 2_000
REAL_OVERVIEW_TIMEZONE = ZoneInfo("America/Sao_Paulo")


def _side_types(side: str | None) -> list[DealType]:
    """Map side filter param to DealType list (excludes BALANCE)."""
    if side == "long":
        return [DealType.BUY]
    if side == "short":
        return [DealType.SELL]
    return [DealType.BUY, DealType.SELL]


def _synthetic_equity(deals_df: pd.DataFrame) -> pd.DataFrame:
    """Build a synthetic equity curve from cumulative deal P&L.

    Used when filtering by side, since the real EquityCurve table is
    account-level and cannot be split by direction.
    """
    if deals_df.empty:
        return pd.DataFrame()
    pnl = deals_df["profit"] + deals_df["commission"] + deals_df["swap"]
    return pd.DataFrame({"equity": pnl.cumsum()})


# ── Authentication ────────────────────────────────────────────────────────────

API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=True)


def get_api_key(api_key: str = Security(api_key_header)):
    if api_key != settings.api_key:
        raise HTTPException(status_code=403, detail="Invalid or missing API Key")
    return api_key


def _sanitize_metrics(metrics: dict) -> dict:
    """Replace NaN/Inf float values with None so JSON serialization doesn't fail."""
    result: dict[str, float | None] = {}
    for k, v in metrics.items():
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            result[k] = None
        else:
            result[k] = v
    return result


def _compute_max_drawdown(equity_series: list[float]) -> float | None:
    """Return max drawdown as a 0-1 fraction from an ordered equity series."""
    if not equity_series:
        return None
    peak = equity_series[0]
    max_dd = 0.0
    for e in equity_series:
        peak = max(peak, e)
        if peak > 0:
            dd = (peak - e) / peak
            max_dd = max(max_dd, dd)
    return max_dd


def _get_portfolio_or_404(db: Session, portfolio_id: int) -> Portfolio:
    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return portfolio


def _get_portfolio_strategy_ids(
    portfolio: Portfolio,
    *,
    required_count: int | None = None,
    detail: str | None = None,
    status_code: int = 422,
) -> list[str]:
    strategy_ids = [strategy.id for strategy in portfolio.strategies]
    if required_count is not None and len(strategy_ids) < required_count:
        raise HTTPException(
            status_code=status_code,
            detail=detail or "No strategies in this portfolio",
        )
    return strategy_ids


def _compute_var(equity_series: list[float], percentile: float = 95) -> float | None:
    """Compute Value at Risk (VaR) from equity series using daily returns."""
    if len(equity_series) < 5:
        return None

    # Calculate daily returns (approximate if equity_series is daily)
    returns = np.diff(equity_series) / equity_series[:-1]
    returns = returns[~np.isnan(returns) & ~np.isinf(returns)]

    if len(returns) < 5:
        return None

    # VaR is the negative of the specified percentile of the returns
    var = -np.percentile(returns, 100 - percentile)
    return float(var)


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
    values = [float(v) for v in series.tolist()]
    max_dd = _compute_max_drawdown(values)
    return None if max_dd is None else max_dd * 100


def _series_correlation(series_a: pd.Series, series_b: pd.Series) -> float | None:
    if series_a.empty or series_b.empty:
        return None
    joined = pd.concat([series_a, series_b], axis=1, join="inner").dropna()
    if len(joined) < 3:
        return None
    returns = joined.pct_change().dropna()
    if len(returns) < 2:
        return None
    corr = returns.iloc[:, 0].corr(returns.iloc[:, 1])
    return None if pd.isna(corr) else float(corr)


router = APIRouter(prefix="/api", dependencies=[Depends(get_api_key)])


@router.get("/summary", response_model=SummaryResponse)
def get_summary(db: Session = Depends(get_db)):
    strategies = db.query(Strategy).all()
    portfolios_count = db.query(Portfolio).count()
    accounts_count = db.query(Account).count()

    by_symbol: dict[str, int] = {}
    by_style: dict[str, int] = {}
    by_duration: dict[str, int] = {}

    for s in strategies:
        sym = s.symbol or "Unknown"
        style = s.operational_style or "Unknown"
        duration = s.trade_duration or "Unknown"
        by_symbol[sym] = by_symbol.get(sym, 0) + 1
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


def _get_net_profits(db: Session, sids: list[str]) -> dict[str, float]:
    rows = (
        db.query(Deal.strategy_id, func.sum(Deal.profit + Deal.commission + Deal.swap))
        .filter(
            Deal.strategy_id.in_(sids), Deal.type.in_([DealType.BUY, DealType.SELL])
        )
        .group_by(Deal.strategy_id)
        .all()
    )
    return {str(r[0]): float(r[1] or 0.0) for r in rows}


def _get_intraday_net_profits(
    db: Session,
    sids: list[str],
    now_utc: datetime | None = None,
) -> dict[str, float]:
    if not sids:
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

    rows = (
        db.query(Deal.strategy_id, func.sum(Deal.profit + Deal.commission + Deal.swap))
        .filter(
            Deal.strategy_id.in_(sids),
            Deal.type.in_([DealType.BUY, DealType.SELL]),
            Deal.timestamp >= day_start_utc,
            Deal.timestamp <= now_utc,
        )
        .group_by(Deal.strategy_id)
        .all()
    )
    return {str(r[0]): float(r[1] or 0.0) for r in rows}


def _get_latest_equity(db: Session, sids: list[str]) -> dict[str, EquityCurve]:
    subq = (
        db.query(
            EquityCurve.strategy_id, func.max(EquityCurve.timestamp).label("latest_ts")
        )
        .filter(EquityCurve.strategy_id.in_(sids))
        .group_by(EquityCurve.strategy_id)
        .subquery()
    )
    rows = (
        db.query(EquityCurve)
        .join(
            subq,
            (EquityCurve.strategy_id == subq.c.strategy_id)
            & (EquityCurve.timestamp == subq.c.latest_ts),
        )
        .all()
    )
    return {str(r.strategy_id): r for r in rows}


def _get_latest_runtime_snapshots(
    db: Session, sids: list[str]
) -> dict[str, StrategyRuntimeSnapshot]:
    if not sids:
        return {}
    rows = (
        db.query(StrategyRuntimeSnapshot)
        .filter(StrategyRuntimeSnapshot.strategy_id.in_(sids))
        .all()
    )
    return {str(r.strategy_id): r for r in rows}


def _get_equity_by_sid(
    db: Session,
    sids: list[str],
    max_points_per_strategy: int = REAL_OVERVIEW_MAX_POINTS_PER_STRATEGY,
) -> dict[str, list[dict[str, object]]]:
    if not sids:
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
        .filter(EquityCurve.strategy_id.in_(sids))
        .subquery()
    )

    rows = (
        db.query(ranked_rows)
        .filter(ranked_rows.c.rn <= max_points_per_strategy)
        .order_by(ranked_rows.c.strategy_id, ranked_rows.c.timestamp)
        .all()
    )
    result: dict[str, list[dict[str, object]]] = {sid: [] for sid in sids}
    for row in rows:
        result[str(row.strategy_id)].append(
            {
                "ts": to_iso(row.timestamp),
                "balance": float(row.balance),
                "equity": float(row.equity),
            }
        )
    return result


def _combine_equity_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame()
    combined = (
        pd.concat([df["equity"] for df in frames], axis=1)
        .sort_index()
        .ffill(limit=5)
        .fillna(0)
        .sum(axis=1)
    )
    return pd.DataFrame(combined, columns=["equity"])


def _setting_bool(db: Session, key: str, default: bool = False) -> bool:
    setting = db.query(Setting).filter(Setting.key == key).first()
    if not setting or setting.value is None:
        return default
    return str(setting.value).strip().lower() in {"1", "true", "yes", "on"}


def _setting_str(db: Session, key: str, default: str) -> str:
    setting = db.query(Setting).filter(Setting.key == key).first()
    if not setting or setting.value is None or not str(setting.value).strip():
        return default
    return str(setting.value).strip().lower()


def _strategy_matches_history_type(strategy: Strategy, history_type: str) -> bool:
    account_type = (
        (strategy.account.account_type or "").strip().lower()
        if strategy.account
        else ""
    )
    if "demo" in account_type:
        return history_type == "demo"
    if "real" in account_type:
        return history_type == "real"
    if history_type == "real":
        return bool(strategy.real_account)
    if history_type == "demo":
        return not bool(strategy.real_account)
    return True


@router.get("/real")
def get_real_overview(
    max_points_per_strategy: int = Query(
        default=REAL_OVERVIEW_MAX_POINTS_PER_STRATEGY, ge=100, le=10_000
    ),
    db: Session = Depends(get_db),
):
    """Aggregated view of all real-account strategies.

    Caps equity history per strategy so the overview endpoint stays bounded as
    time-series data grows.
    """
    real_page_mode = _setting_str(db, "real_page_mode", default="real")
    overview_strategies = [
        strategy
        for strategy in db.query(Strategy).options(joinedload(Strategy.account)).all()
        if _strategy_matches_history_type(strategy, real_page_mode)
    ]
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

    sids = [str(s.id) for s in overview_strategies]
    np_map = _get_net_profits(db, sids)
    day_np_map = _get_intraday_net_profits(db, sids)
    latest_eq_map = _get_latest_equity(db, sids)
    runtime_map = _get_latest_runtime_snapshots(db, sids)
    equity_by_sid = _get_equity_by_sid(
        db, sids, max_points_per_strategy=max_points_per_strategy
    )

    result = []
    total_np = 0.0
    total_floating = 0.0
    total_day_pnl = 0.0
    total_open_trades = 0
    total_pending_orders = 0
    counts_available = True

    for s in overview_strategies:
        np_val = np_map.get(str(s.id), 0.0)
        day_np_val = day_np_map.get(str(s.id), 0.0)
        eq = latest_eq_map.get(str(s.id))
        runtime = runtime_map.get(str(s.id))
        balance = float(eq.balance) if eq else None
        equity = float(eq.equity) if eq else None
        open_trades_count = runtime.open_trades_count if runtime else None
        pending_orders_count = runtime.pending_orders_count if runtime else None
        floating = (
            float(runtime.open_profit)
            if runtime is not None and runtime.open_profit is not None
            else (
                (equity - balance)
                if (equity is not None and balance is not None)
                else 0.0
            )
        )

        equity_series = [float(str(p["equity"])) for p in equity_by_sid[str(s.id)]]
        max_dd = _compute_max_drawdown(equity_series)
        var_95 = _compute_var(equity_series, percentile=95)

        ret_dd = None
        ib = float(s.initial_balance) if s.initial_balance else None
        if max_dd and max_dd > 0 and ib and ib > 0:
            # Ensure sign follows net profit and use absolute drawdown
            ret_dd = round(np_val / (abs(max_dd) * ib), 3)

        result.append(
            {
                "id": s.id,
                "name": s.name,
                "symbol": s.symbol,
                "net_profit": round(np_val, 2),
                "day_pnl": round(day_np_val, 2),
                "open_trades_count": open_trades_count,
                "pending_orders_count": pending_orders_count,
                "max_drawdown_pct": round(max_dd * 100, 2)
                if max_dd is not None
                else None,
                "var_95_pct": round(var_95 * 100, 2) if var_95 is not None else None,
                "ret_dd": ret_dd,
                "floating_pnl": round(floating, 2),
                "balance": round(balance, 2) if balance is not None else None,
                "equity": round(equity, 2) if equity is not None else None,
                "initial_balance": ib,
                "last_update": to_iso(eq.timestamp) if eq else None,
                "equity_curve": equity_by_sid[str(s.id)],
            }
        )
        total_np += np_val
        total_floating += floating
        total_day_pnl += day_np_val
        if open_trades_count is None or pending_orders_count is None:
            counts_available = False
        else:
            total_open_trades += open_trades_count
            total_pending_orders += pending_orders_count

    return {
        "mode": real_page_mode,
        "strategies": result,
        "totals": {
            "net_profit": round(total_np, 2),
            "floating_pnl": round(total_floating, 2),
            "day_pnl": round(total_day_pnl, 2),
            "open_trades_count": total_open_trades if counts_available else None,
            "pending_orders_count": total_pending_orders if counts_available else None,
            "counts_available": counts_available,
        },
    }


@router.get("/real/daily")
def get_real_daily(
    db: Session = Depends(get_db),
):
    real_page_mode = _setting_str(db, "real_page_mode", default="real")
    overview_strategies = [
        strategy
        for strategy in db.query(Strategy).options(joinedload(Strategy.account)).all()
        if _strategy_matches_history_type(strategy, real_page_mode)
    ]
    if not overview_strategies:
        return []

    strategy_ids = [str(strategy.id) for strategy in overview_strategies]
    date_expr = func.date(Deal.timestamp)
    rows = (
        db.query(
            date_expr.label("date"),
            func.sum(Deal.profit + Deal.commission + Deal.swap).label("net_profit"),
        )
        .filter(Deal.strategy_id.in_(strategy_ids))
        .filter(Deal.type.in_([DealType.BUY, DealType.SELL]))
        .group_by(date_expr)
        .order_by(date_expr)
        .all()
    )
    return [
        {"date": str(row.date), "net_profit": float(row.net_profit)} for row in rows
    ]


@router.get("/real/recent-deals")
def get_real_recent_deals(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    real_page_mode = _setting_str(db, "real_page_mode", default="real")
    overview_strategies = [
        strategy
        for strategy in db.query(Strategy).options(joinedload(Strategy.account)).all()
        if _strategy_matches_history_type(strategy, real_page_mode)
    ]
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


@router.get("/accounts", response_model=list[AccountResponse])
def list_accounts(db: Session = Depends(get_db)):
    accounts = db.query(Account).all()
    net_profits: dict[str | None, float] = dict(
        db.query(
            Strategy.account_id, func.sum(Deal.profit + Deal.commission + Deal.swap)
        )
        .join(Deal, Deal.strategy_id == Strategy.id)
        .filter(Deal.type.in_([DealType.BUY, DealType.SELL]))
        .filter(Strategy.account_id.isnot(None))
        .group_by(Strategy.account_id)
        .all()  # type: ignore[arg-type]
    )
    result = []
    for a in accounts:
        r = AccountResponse.model_validate(a)
        raw = net_profits.get(a.id)
        r.net_profit = float(raw) if raw is not None else None
        result.append(r)
    return result


@router.delete("/accounts/{account_id}", status_code=204)
def delete_account(account_id: str, db: Session = Depends(get_db)):
    a = db.query(Account).filter(Account.id == account_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Account not found")
    db.delete(a)
    db.commit()
    invalidate_cache(account_id=account_id)


@router.patch("/accounts/{account_id}", response_model=AccountResponse)
def update_account(
    account_id: str, payload: AccountUpdate, db: Session = Depends(get_db)
):
    a = db.query(Account).filter(Account.id == account_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Account not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(a, field, value)
    db.commit()
    db.refresh(a)
    return a


@router.get("/strategies", response_model=list[StrategyResponse])
def list_strategies(db: Session = Depends(get_db)):
    from collections import defaultdict

    net_profits: dict[str, float] = dict(
        db.query(Deal.strategy_id, func.sum(Deal.profit + Deal.commission + Deal.swap))
        .filter(Deal.type.in_([DealType.BUY, DealType.SELL]))
        .group_by(Deal.strategy_id)
        .all()  # type: ignore[arg-type]
    )
    bt_net_profits: dict[str, float] = dict(
        db.query(
            Backtest.strategy_id,
            func.sum(BacktestDeal.profit + BacktestDeal.commission + BacktestDeal.swap),
        )
        .join(BacktestDeal, BacktestDeal.backtest_id == Backtest.id)
        .filter(BacktestDeal.type.in_([DealType.BUY, DealType.SELL]))
        .group_by(Backtest.strategy_id)
        .all()  # type: ignore[arg-type]
    )
    trades_counts: dict[str, int] = dict(
        db.query(Deal.strategy_id, func.count(Deal.ticket))
        .filter(Deal.type.in_([DealType.BUY, DealType.SELL]))
        .group_by(Deal.strategy_id)
        .all()  # type: ignore[arg-type]
    )
    # Last and first trade timestamps per strategy (for zombie detection)
    deal_range_rows = (
        db.query(
            Deal.strategy_id,
            func.max(Deal.timestamp).label("last_trade_at"),
            func.min(Deal.timestamp).label("first_trade_at"),
        )
        .filter(Deal.type.in_([DealType.BUY, DealType.SELL]))
        .group_by(Deal.strategy_id)
        .all()
    )
    last_trade_map: dict = {}
    first_trade_map: dict = {}
    for row in deal_range_rows:
        last_trade_map[row.strategy_id] = row.last_trade_at
        first_trade_map[row.strategy_id] = row.first_trade_at

    # Fetch equity data for max drawdown computation and last_seen_at
    equity_rows = (
        db.query(EquityCurve.strategy_id, EquityCurve.equity, EquityCurve.timestamp)
        .order_by(EquityCurve.strategy_id, EquityCurve.timestamp)
        .all()
    )
    equity_by_strat: dict = defaultdict(list)
    last_seen_map: dict = {}
    for row in equity_rows:
        equity_by_strat[row.strategy_id].append(float(row.equity))
        last_seen_map[row.strategy_id] = row.timestamp

    now_utc = datetime.now(UTC)
    strategies = db.query(Strategy).options(joinedload(Strategy.account)).all()
    result = []
    for s in strategies:
        r = StrategyResponse.model_validate(s)
        r.account_name = s.account.name if s.account else None
        r.account_type = s.account.account_type if s.account else None
        raw_np = net_profits.get(s.id)
        r.net_profit = float(raw_np) if raw_np is not None else None
        raw_bt = bt_net_profits.get(s.id)
        r.backtest_net_profit = float(raw_bt) if raw_bt is not None else None
        r.trades_count = trades_counts.get(s.id)
        r.max_drawdown = _compute_max_drawdown(equity_by_strat.get(s.id, []))
        r.last_seen_at = last_seen_map.get(s.id)
        r.last_trade_at = last_trade_map.get(s.id)

        # Zombie alert: live strategy that has gone silent relative to its historical pace
        r.zombie_alert = False
        if s.live and r.last_trade_at and r.trades_count:
            first_trade = first_trade_map.get(s.id)
            days_active = (
                max(1, (now_utc - first_trade.replace(tzinfo=UTC)).days)
                if first_trade
                else 1
            )
            avg_trades_per_day = r.trades_count / days_active
            # Only flag strategies with meaningful trading frequency (≥1 trade per 5 days)
            if avg_trades_per_day >= 0.2:
                expected_interval_h = 24.0 / avg_trades_per_day
                last_trade_aware = (
                    r.last_trade_at.replace(tzinfo=UTC)
                    if r.last_trade_at.tzinfo is None
                    else r.last_trade_at
                )
                hours_since = (now_utc - last_trade_aware).total_seconds() / 3600
                r.zombie_alert = hours_since > max(48.0, expected_interval_h * 2)

        result.append(r)
    return result


@router.get("/strategies/{strategy_id}", response_model=StrategyResponse)
def get_strategy(strategy_id: str, db: Session = Depends(get_db)):
    s = (
        db.query(Strategy)
        .options(joinedload(Strategy.account))
        .filter(Strategy.id == strategy_id)
        .first()
    )
    if not s:
        raise HTTPException(status_code=404, detail="Strategy not found")
    r = StrategyResponse.model_validate(s)
    r.account_name = s.account.name if s.account else None
    return r


@router.patch("/strategies/{strategy_id}", response_model=StrategyResponse)
def update_strategy(
    strategy_id: str, payload: StrategyUpdate, db: Session = Depends(get_db)
):
    s = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Strategy not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(s, field, value)
    db.commit()
    db.refresh(s)
    r = StrategyResponse.model_validate(s)
    r.account_name = s.account.name if s.account else None
    return r


@router.delete("/strategies/{strategy_id}", status_code=204)
def delete_strategy(strategy_id: str, db: Session = Depends(get_db)):
    s = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Strategy not found")
    # strategy_id is part of composite PKs in child tables, so ORM cascade would try
    # to NULL the FK before deletion — violating the PK constraint. Delete explicitly.
    db.execute(text("DELETE FROM deals WHERE strategy_id = :sid"), {"sid": strategy_id})
    db.execute(
        text("DELETE FROM equity_curve WHERE strategy_id = :sid"), {"sid": strategy_id}
    )
    db.execute(
        text("""
        DELETE FROM backtest_deals WHERE backtest_id IN (
            SELECT id FROM backtests WHERE strategy_id = :sid
        )
    """),
        {"sid": strategy_id},
    )
    db.execute(
        text("""
        DELETE FROM backtest_equity WHERE backtest_id IN (
            SELECT id FROM backtests WHERE strategy_id = :sid
        )
    """),
        {"sid": strategy_id},
    )
    db.execute(
        text("DELETE FROM backtests WHERE strategy_id = :sid"), {"sid": strategy_id}
    )
    db.execute(
        text("DELETE FROM portfolio_strategy WHERE strategy_id = :sid"),
        {"sid": strategy_id},
    )
    db.delete(s)
    db.commit()
    invalidate_cache(strategy_id=strategy_id)


@router.get("/strategies/{strategy_id}/metrics")
def get_strategy_metrics(
    strategy_id: str,
    side: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    from trademachine.tradingmonitor.metrics.calculator import calculate_metrics_from_df
    from trademachine.tradingmonitor.metrics.repository import (
        get_strategy_deals,
        get_strategy_equity_curve,
    )

    try:
        deals_df = get_strategy_deals(strategy_id)
        side_values = [t.value for t in _side_types(side)]
        if not deals_df.empty:
            deals_df = deals_df[deals_df["type"].isin(side_values)]
        if side in ("long", "short"):
            equity_df = _synthetic_equity(deals_df)
        else:
            equity_df = get_strategy_equity_curve(strategy_id)
        return _sanitize_metrics(calculate_metrics_from_df(deals_df, equity_df))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Metrics calculation failed: {e}")


@router.get("/strategies/{strategy_id}/advanced-metrics")
def get_strategy_advanced_metrics(
    strategy_id: str,
    date_from: str | None = Query(
        default=None, description="ISO date string, e.g. 2024-01-01"
    ),
    date_to: str | None = Query(
        default=None, description="ISO date string, e.g. 2024-12-31"
    ),
    initial_balance: float | None = Query(default=None),
    side: str | None = Query(default=None),
    history_type: str = Query(default="real"),
    db: Session = Depends(get_db),
):
    strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    from trademachine.tradingmonitor.metrics.calculator import calculate_metrics_from_df
    from trademachine.tradingmonitor.metrics.repository import (
        get_backtest_deals,
        get_backtest_equity,
        get_strategy_deals,
        get_strategy_equity_curve,
    )

    dt_from = (
        datetime.fromisoformat(date_from).replace(tzinfo=UTC) if date_from else None
    )
    dt_to = datetime.fromisoformat(date_to).replace(tzinfo=UTC) if date_to else None
    side_values = [t.value for t in _side_types(side)]

    if history_type == "backtest":
        backtests = (
            db.query(Backtest)
            .filter(Backtest.strategy_id == strategy_id)
            .filter(or_(Backtest.status == "complete", Backtest.status.is_(None)))
            .all()
        )
        if not backtests:
            raise HTTPException(
                status_code=422,
                detail="No backtest history found for this strategy.",
            )
        deal_frames: list[pd.DataFrame] = []
        equity_frames: list[pd.DataFrame] = []
        for bt in backtests:
            deals_df = get_backtest_deals(bt.id)
            if not deals_df.empty:
                if dt_from is not None:
                    deals_df = deals_df[deals_df.index >= dt_from]
                if dt_to is not None:
                    deals_df = deals_df[deals_df.index <= dt_to]
                if not deals_df.empty:
                    deal_frames.append(deals_df)

            equity_df = get_backtest_equity(bt.id)
            if not equity_df.empty:
                if dt_from is not None:
                    equity_df = equity_df[equity_df.index >= dt_from]
                if dt_to is not None:
                    equity_df = equity_df[equity_df.index <= dt_to]
                if not equity_df.empty:
                    equity_frames.append(equity_df)

        deals_df = pd.concat(deal_frames) if deal_frames else pd.DataFrame()
        equity_df = pd.concat(equity_frames) if equity_frames else pd.DataFrame()
    else:
        if not _strategy_matches_history_type(strategy, history_type):
            raise HTTPException(
                status_code=422,
                detail=f"Strategy does not have {history_type} history.",
            )

        deals_df = get_strategy_deals(strategy_id, since=dt_from)
        if not deals_df.empty and dt_to is not None:
            deals_df = deals_df[deals_df.index <= dt_to]

        if side in ("long", "short"):
            equity_df = _synthetic_equity(deals_df)
        else:
            equity_df = get_strategy_equity_curve(strategy_id)
            if not equity_df.empty:
                if dt_from is not None:
                    equity_df = equity_df[equity_df.index >= dt_from]
                if dt_to is not None:
                    equity_df = equity_df[equity_df.index <= dt_to]

    if not deals_df.empty and side_values:
        deals_df = deals_df[deals_df["type"].isin(side_values)]

    try:
        metrics = calculate_metrics_from_df(deals_df, equity_df, advanced=True)
        if (
            initial_balance
            and "Net Profit" in metrics
            and metrics["Net Profit"] is not None
        ):
            metrics["Return on Capital (%)"] = (
                metrics["Net Profit"] / initial_balance
            ) * 100
        return _sanitize_metrics(metrics)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/strategies/{strategy_id}/trade-stats")
def get_strategy_trade_stats(
    strategy_id: str,
    side: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    types = _side_types(side)

    def _q(group_expr):
        return (
            db.query(
                group_expr.label("key"),
                func.count().label("count"),
                func.sum(Deal.profit + Deal.commission + Deal.swap).label("net_profit"),
            )
            .filter(Deal.strategy_id == strategy_id)
            .filter(Deal.type.in_(types))
            .group_by(group_expr)
            .order_by(group_expr)
            .all()
        )

    hour_rows = _q(extract("hour", Deal.timestamp))
    dow_rows = _q(extract("isodow", Deal.timestamp))

    by_hour = [{"hour": h, "count": 0, "net_profit": 0.0} for h in range(24)]
    for r in hour_rows:
        h = int(r.key)
        by_hour[h] = {
            "hour": h,
            "count": int(r.count),
            "net_profit": round(float(r.net_profit or 0), 2),
        }

    DOW_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    by_dow = [
        {"dow": i + 1, "label": DOW_LABELS[i], "count": 0, "net_profit": 0.0}
        for i in range(7)
    ]
    for r in dow_rows:
        d = int(r.key) - 1
        by_dow[d] = {
            "dow": d + 1,
            "label": DOW_LABELS[d],
            "count": int(r.count),
            "net_profit": round(float(r.net_profit or 0), 2),
        }

    return {"by_hour": by_hour, "by_dow": by_dow}


@router.get("/strategies/{strategy_id}/daily")
def get_strategy_daily(
    strategy_id: str,
    side: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    rows = (
        db.query(
            cast(Deal.timestamp, Date).label("date"),
            func.sum(Deal.profit + Deal.commission + Deal.swap).label("net_profit"),
        )
        .filter(Deal.strategy_id == strategy_id)
        .filter(Deal.type.in_(_side_types(side)))
        .group_by(cast(Deal.timestamp, Date))
        .order_by(cast(Deal.timestamp, Date))
        .all()
    )
    return [{"date": str(r.date), "net_profit": float(r.net_profit)} for r in rows]


@router.get(
    "/strategies/{strategy_id}/equity", response_model=list[EquityPointResponse]
)
def get_strategy_equity(strategy_id: str, db: Session = Depends(get_db)):
    strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return (
        db.query(EquityCurve)
        .filter(EquityCurve.strategy_id == strategy_id)
        .order_by(EquityCurve.timestamp)
        .all()
    )


@router.get("/strategies/{strategy_id}/deals", response_model=PaginatedDeals)
def get_strategy_deals(
    strategy_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    q: str | None = Query(default=None),
    side: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    base = db.query(Deal).filter(Deal.strategy_id == strategy_id)
    if side in ("long", "short"):
        base = base.filter(Deal.type.in_(_side_types(side)))
    if q:
        term = f"%{q}%"
        conditions: list[Any] = [
            Deal.symbol.ilike(term),
            cast(Deal.ticket, String).ilike(term),
        ]
        try:
            conditions.append(Deal.type == DealType(q.upper()))
        except ValueError:
            pass
        base = base.filter(or_(*conditions))

    total = base.count()
    deals = (
        base.order_by(Deal.timestamp.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PaginatedDeals(
        items=[DealResponse.from_orm_deal(d) for d in deals],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/portfolios", response_model=list[PortfolioResponse])
def list_portfolios(
    mode: Literal["backtest", "demo", "real"] = Query(default="demo"),
    db: Session = Depends(get_db),
):
    portfolios = db.query(Portfolio).options(joinedload(Portfolio.strategies)).all()

    import pandas as pd
    from trademachine.tradingmonitor.metrics.calculator import (
        calculate_metrics_from_df,
        calculate_portfolio_metrics,
    )
    from trademachine.tradingmonitor.metrics.repository import (
        get_backtest_deals,
        get_backtest_equity,
    )

    def _extract_np(metrics: dict) -> float | None:
        v = metrics.get("Net Profit")
        return float(v) if v is not None else None

    def _backtest_np(db_session: Session, sids: list[str]) -> float | None:
        all_deals = []
        all_equity = []
        for sid in sids:
            bt = (
                db_session.query(Backtest)
                .filter(Backtest.strategy_id == sid, Backtest.status == "complete")
                .order_by(Backtest.created_at.desc())
                .first()
            )
            if bt:
                df_deals = get_backtest_deals(bt.id)
                df_equity = get_backtest_equity(bt.id)
                if not df_deals.empty:
                    all_deals.append(df_deals)
                if not df_equity.empty:
                    all_equity.append(df_equity)
        if not all_deals:
            return None
        combined_deals = pd.concat(all_deals).sort_index()
        if all_equity:
            equity_combined_df = pd.concat(
                [df["equity"] for df in all_equity], axis=1
            ).sort_index()
            equity_combined_df = equity_combined_df.ffill(limit=5).fillna(0)
            portfolio_equity = equity_combined_df.sum(axis=1)
            combined_equity_df = pd.DataFrame(portfolio_equity, columns=["equity"])
        else:
            combined_equity_df = pd.DataFrame()
        metrics = calculate_metrics_from_df(combined_deals, combined_equity_df)
        return _extract_np(metrics)

    result = []
    for p in portfolios:
        strategy_ids = [s.id for s in p.strategies]
        demo_strategy_ids = [s.id for s in p.strategies if not s.real_account]
        real_strategy_ids = [s.id for s in p.strategies if s.real_account]
        r = PortfolioResponse.from_orm_portfolio(p)

        if strategy_ids:
            # Backtest
            r.backtest_net_profit = _backtest_np(db, strategy_ids)

            # Demo
            if demo_strategy_ids:
                demo_metrics = calculate_portfolio_metrics(demo_strategy_ids)
                r.demo_net_profit = _extract_np(demo_metrics)

            # Real
            if real_strategy_ids:
                real_metrics = calculate_portfolio_metrics(real_strategy_ids)
                r.real_net_profit = _extract_np(real_metrics)

            # net_profit based on selected mode (for backward compat)
            if mode == "demo":
                r.net_profit = r.demo_net_profit
            elif mode == "real":
                r.net_profit = r.real_net_profit
            elif mode == "backtest":
                r.net_profit = r.backtest_net_profit

        result.append(r)
    return result


@router.get("/portfolios/{portfolio_id}", response_model=PortfolioResponse)
def get_portfolio(portfolio_id: int, db: Session = Depends(get_db)):
    p = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return PortfolioResponse.from_orm_portfolio(p)


@router.post("/portfolios", response_model=PortfolioResponse, status_code=201)
def create_portfolio(payload: PortfolioCreate, db: Session = Depends(get_db)):
    p = Portfolio(
        name=payload.name,
        description=payload.description,
        live=payload.live,
        real_account=payload.real_account,
        initial_balance=payload.initial_balance,
    )
    if payload.strategy_ids:
        strategies = (
            db.query(Strategy).filter(Strategy.id.in_(payload.strategy_ids)).all()
        )
        p.strategies = strategies
    db.add(p)
    db.commit()
    db.refresh(p)
    return PortfolioResponse.from_orm_portfolio(p)


@router.patch("/portfolios/{portfolio_id}", response_model=PortfolioResponse)
def update_portfolio(
    portfolio_id: int, payload: PortfolioUpdate, db: Session = Depends(get_db)
):
    p = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    for field, value in payload.model_dump(
        exclude_unset=True, exclude={"strategy_ids"}
    ).items():
        setattr(p, field, value)
    if payload.strategy_ids is not None:
        p.strategies = (
            db.query(Strategy).filter(Strategy.id.in_(payload.strategy_ids)).all()
        )
    db.commit()
    db.refresh(p)
    return PortfolioResponse.from_orm_portfolio(p)


@router.delete("/portfolios/{portfolio_id}", status_code=204)
def delete_portfolio(portfolio_id: int, db: Session = Depends(get_db)):
    p = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    db.delete(p)
    db.commit()


@router.get(
    "/portfolios/{portfolio_id}/strategies", response_model=list[StrategyResponse]
)
def get_portfolio_strategies(portfolio_id: int, db: Session = Depends(get_db)):
    p = _get_portfolio_or_404(db, portfolio_id)
    strategy_ids = _get_portfolio_strategy_ids(p)
    if not strategy_ids:
        return []

    # Net profits from live deals
    net_profits: dict[str, float] = dict(
        db.query(Deal.strategy_id, func.sum(Deal.profit + Deal.commission + Deal.swap))
        .filter(Deal.strategy_id.in_(strategy_ids))
        .filter(Deal.type.in_([DealType.BUY, DealType.SELL]))
        .group_by(Deal.strategy_id)
        .all()  # type: ignore[arg-type]
    )
    # Backtest net profits
    bt_net_profits: dict[str, float] = dict(
        db.query(
            Backtest.strategy_id,
            func.sum(BacktestDeal.profit + BacktestDeal.commission + BacktestDeal.swap),
        )
        .join(BacktestDeal, BacktestDeal.backtest_id == Backtest.id)
        .filter(Backtest.strategy_id.in_(strategy_ids))
        .filter(BacktestDeal.type.in_([DealType.BUY, DealType.SELL]))
        .group_by(Backtest.strategy_id)
        .all()  # type: ignore[arg-type]
    )
    # Trades count
    trades_counts: dict[str, int] = dict(
        db.query(Deal.strategy_id, func.count(Deal.ticket))
        .filter(Deal.strategy_id.in_(strategy_ids))
        .filter(Deal.type.in_([DealType.BUY, DealType.SELL]))
        .group_by(Deal.strategy_id)
        .all()  # type: ignore[arg-type]
    )
    # Equity for max drawdown
    equity_rows = (
        db.query(EquityCurve.strategy_id, EquityCurve.equity, EquityCurve.timestamp)
        .filter(EquityCurve.strategy_id.in_(strategy_ids))
        .order_by(EquityCurve.strategy_id, EquityCurve.timestamp)
        .all()
    )
    from collections import defaultdict

    equity_by_strat: dict = defaultdict(list)
    for row in equity_rows:
        equity_by_strat[row.strategy_id].append(float(row.equity))

    strategies = (
        db.query(Strategy)
        .options(joinedload(Strategy.account))
        .filter(Strategy.id.in_(strategy_ids))
        .all()
    )
    result = []
    for s in strategies:
        r = StrategyResponse.model_validate(s)
        r.account_name = s.account.name if s.account else None
        r.account_type = s.account.account_type if s.account else None
        raw_np = net_profits.get(s.id)
        r.net_profit = float(raw_np) if raw_np is not None else None
        raw_bt = bt_net_profits.get(s.id)
        r.backtest_net_profit = float(raw_bt) if raw_bt is not None else None
        r.trades_count = trades_counts.get(s.id)
        r.max_drawdown = _compute_max_drawdown(equity_by_strat.get(s.id, []))
        result.append(r)
    return result


@router.get("/portfolios/{portfolio_id}/daily")
def get_portfolio_daily(portfolio_id: int, db: Session = Depends(get_db)):
    p = _get_portfolio_or_404(db, portfolio_id)
    strategy_ids = _get_portfolio_strategy_ids(p)
    if not strategy_ids:
        return []
    rows = (
        db.query(
            cast(Deal.timestamp, Date).label("date"),
            func.sum(Deal.profit + Deal.commission + Deal.swap).label("net_profit"),
            func.count(Deal.id).label("trades_count"),
        )
        .filter(Deal.strategy_id.in_(strategy_ids))
        .filter(Deal.type != "BALANCE")
        .group_by(cast(Deal.timestamp, Date))
        .order_by(cast(Deal.timestamp, Date))
        .all()
    )
    return [
        {
            "date": str(r.date),
            "net_profit": float(r.net_profit),
            "trades_count": int(r.trades_count),
        }
        for r in rows
    ]


@router.get("/portfolios/{portfolio_id}/equity")
def get_portfolio_equity(portfolio_id: int, db: Session = Depends(get_db)):
    p = _get_portfolio_or_404(db, portfolio_id)
    strategy_ids = _get_portfolio_strategy_ids(p)
    if not strategy_ids:
        return []
    from trademachine.tradingmonitor.metrics.repository import get_strategy_equity_curve

    series = []
    for sid in strategy_ids:
        df = get_strategy_equity_curve(sid)
        if not df.empty:
            series.append(df["equity"].rename(sid))
    if not series:
        return []
    combined = pd.concat(series, axis=1).sort_index().ffill().fillna(0).sum(axis=1)
    return [{"timestamp": to_iso(ts), "equity": float(v)} for ts, v in combined.items()]


def _ensure_utc(dt: datetime | None) -> datetime | None:
    """Ensure a datetime is timezone-aware (UTC). Treats naive datetimes as UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


@router.get("/portfolios/{portfolio_id}/correlation")
def get_portfolio_correlation(
    portfolio_id: int,
    period: str = "daily",
    since: datetime | None = None,
    db: Session = Depends(get_db),
):
    p = _get_portfolio_or_404(db, portfolio_id)
    strategy_ids = _get_portfolio_strategy_ids(
        p,
        required_count=2,
        detail="Need at least 2 strategies in this portfolio.",
    )
    from trademachine.tradingmonitor.metrics.calculator import (
        calculate_correlation_matrix,
    )

    return calculate_correlation_matrix(strategy_ids, period, since=_ensure_utc(since))


@router.get("/portfolios/{portfolio_id}/correlation/dynamic")
def get_portfolio_dynamic_correlation(
    portfolio_id: int,
    window_days: int = Query(default=30, ge=3, le=365),
    db: Session = Depends(get_db),
):
    p = _get_portfolio_or_404(db, portfolio_id)
    strategy_ids = _get_portfolio_strategy_ids(
        p,
        required_count=2,
        detail="Need at least 2 strategies in this portfolio.",
    )
    from trademachine.tradingmonitor.metrics.calculator import (
        calculate_dynamic_correlation,
    )

    return calculate_dynamic_correlation(strategy_ids, window_days)


@router.get("/portfolios/{portfolio_id}/concurrency")
def get_portfolio_concurrency(
    portfolio_id: int,
    since: datetime | None = None,
    db: Session = Depends(get_db),
):
    p = _get_portfolio_or_404(db, portfolio_id)
    strategy_ids = _get_portfolio_strategy_ids(
        p,
        required_count=2,
        detail="Need at least 2 strategies in this portfolio.",
    )
    from trademachine.tradingmonitor.metrics.calculator import calculate_concurrency

    return calculate_concurrency(strategy_ids, since=_ensure_utc(since))


@router.get("/portfolios/{portfolio_id}/metrics")
def get_portfolio_metrics(portfolio_id: int, db: Session = Depends(get_db)):
    portfolio = _get_portfolio_or_404(db, portfolio_id)
    strategy_ids = _get_portfolio_strategy_ids(
        portfolio,
        required_count=1,
        detail="No strategies in this portfolio",
    )
    from trademachine.tradingmonitor.metrics.calculator import (
        calculate_portfolio_metrics,
    )

    try:
        return _sanitize_metrics(calculate_portfolio_metrics(strategy_ids))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Metrics calculation failed: {e}")


@router.get("/portfolios/{portfolio_id}/advanced-metrics")
def get_portfolio_advanced_metrics(
    portfolio_id: int,
    date_from: str | None = Query(
        default=None, description="ISO date string, e.g. 2024-01-01"
    ),
    date_to: str | None = Query(
        default=None, description="ISO date string, e.g. 2024-12-31"
    ),
    initial_balance: float | None = Query(default=None),
    db: Session = Depends(get_db),
):
    portfolio = _get_portfolio_or_404(db, portfolio_id)
    strategy_ids = _get_portfolio_strategy_ids(
        portfolio,
        required_count=1,
        detail="No strategies in this portfolio",
    )

    from trademachine.tradingmonitor.metrics.calculator import calculate_metrics_from_df
    from trademachine.tradingmonitor.metrics.repository import (
        get_strategy_deals,
        get_strategy_equity_curve,
    )

    dt_from = (
        datetime.fromisoformat(date_from).replace(tzinfo=UTC) if date_from else None
    )
    dt_to = datetime.fromisoformat(date_to).replace(tzinfo=UTC) if date_to else None

    all_deals = []
    all_equity = []
    for sid in strategy_ids:
        deals_df = get_strategy_deals(sid, since=dt_from)
        if not deals_df.empty and dt_to is not None:
            deals_df = deals_df[deals_df.index <= dt_to]
        if not deals_df.empty:
            all_deals.append(deals_df)

        equity_df = get_strategy_equity_curve(sid)
        if not equity_df.empty:
            if dt_from is not None:
                equity_df = equity_df[equity_df.index >= dt_from]
            if dt_to is not None:
                equity_df = equity_df[equity_df.index <= dt_to]
        if not equity_df.empty:
            all_equity.append(equity_df)

    combined_deals = pd.concat(all_deals).sort_index() if all_deals else pd.DataFrame()
    combined_equity = (
        pd.concat(all_equity).sort_index() if all_equity else pd.DataFrame()
    )

    try:
        metrics = calculate_metrics_from_df(
            combined_deals, combined_equity, advanced=True
        )
        if (
            initial_balance
            and "Net Profit" in metrics
            and metrics["Net Profit"] is not None
        ):
            metrics["Return on Capital (%)"] = (
                metrics["Net Profit"] / initial_balance
            ) * 100
        return _sanitize_metrics(metrics)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/portfolios/{portfolio_id}/strategy-contributions")
def get_portfolio_strategy_contributions(
    portfolio_id: int,
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    portfolio = _get_portfolio_or_404(db, portfolio_id)
    strategies = portfolio.strategies
    if not strategies:
        raise HTTPException(status_code=422, detail="No strategies in this portfolio")

    from trademachine.tradingmonitor.metrics.repository import get_strategy_deals

    dt_from = (
        datetime.fromisoformat(date_from).replace(tzinfo=UTC) if date_from else None
    )
    dt_to = datetime.fromisoformat(date_to).replace(tzinfo=UTC) if date_to else None

    per_strategy: dict[str, float] = {}
    for s in strategies:
        label = s.name or s.id
        deals_df = get_strategy_deals(s.id, since=dt_from)
        if not deals_df.empty:
            if dt_to is not None:
                deals_df = deals_df[deals_df.index <= dt_to]
        if deals_df.empty or "profit" not in deals_df.columns:
            per_strategy[label] = 0.0
        else:
            per_strategy[label] = float(deals_df["profit"].sum())

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


@router.get("/advanced-analysis")
def get_advanced_analysis(
    strategy_ids: list[str] = Query(default=[]),
    history_type: str = Query(default="real"),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    initial_balance: float | None = Query(default=None),
    benchmark_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if not strategy_ids:
        raise HTTPException(status_code=422, detail="Select at least one strategy.")

    history_type = history_type.lower()
    if history_type not in {"backtest", "demo", "real"}:
        raise HTTPException(
            status_code=422, detail="history_type must be one of backtest, demo, real."
        )

    dt_from = (
        datetime.fromisoformat(date_from).replace(tzinfo=UTC) if date_from else None
    )
    dt_to = datetime.fromisoformat(date_to).replace(tzinfo=UTC) if date_to else None

    from trademachine.tradingmonitor.metrics.calculator import calculate_metrics_from_df
    from trademachine.tradingmonitor.metrics.repository import (
        get_backtest_deals,
        get_backtest_equity,
        get_strategy_deals,
        get_strategy_equity_curve,
    )

    strategies = db.query(Strategy).filter(Strategy.id.in_(strategy_ids)).all()
    if not strategies:
        raise HTTPException(status_code=404, detail="Strategies not found.")

    selected_strategies = strategies
    if history_type in {"real", "demo"}:
        selected_strategies = [
            s for s in strategies if _strategy_matches_history_type(s, history_type)
        ]

    if history_type in {"real", "demo"} and not selected_strategies:
        raise HTTPException(
            status_code=422,
            detail=f"No selected strategies with {history_type} history.",
        )

    deal_frames: list[pd.DataFrame] = []
    equity_frames: list[pd.DataFrame] = []

    if history_type == "backtest":
        backtests = (
            db.query(Backtest)
            .filter(Backtest.strategy_id.in_(strategy_ids))
            .filter(or_(Backtest.status == "complete", Backtest.status.is_(None)))
            .all()
        )
        if not backtests:
            raise HTTPException(
                status_code=422,
                detail="No backtest history found for selected strategies.",
            )

        for bt in backtests:
            deals_df = get_backtest_deals(bt.id)
            if not deals_df.empty:
                if dt_from is not None:
                    deals_df = deals_df[deals_df.index >= dt_from]
                if dt_to is not None:
                    deals_df = deals_df[deals_df.index <= dt_to]
                if not deals_df.empty:
                    deal_frames.append(deals_df)

            equity_df = get_backtest_equity(bt.id)
            if not equity_df.empty:
                if dt_from is not None:
                    equity_df = equity_df[equity_df.index >= dt_from]
                if dt_to is not None:
                    equity_df = equity_df[equity_df.index <= dt_to]
                if not equity_df.empty:
                    equity_frames.append(equity_df)
    else:
        for strategy in selected_strategies:
            deals_df = get_strategy_deals(strategy.id, since=dt_from)
            if not deals_df.empty and dt_to is not None:
                deals_df = deals_df[deals_df.index <= dt_to]
            if not deals_df.empty:
                deal_frames.append(deals_df)

            equity_df = get_strategy_equity_curve(strategy.id)
            if not equity_df.empty:
                if dt_from is not None:
                    equity_df = equity_df[equity_df.index >= dt_from]
                if dt_to is not None:
                    equity_df = equity_df[equity_df.index <= dt_to]
                if not equity_df.empty:
                    equity_frames.append(equity_df)

    if not deal_frames:
        selected_benchmark = None
        if benchmark_id is not None:
            selected_benchmark = (
                db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
            )
        elif benchmark_id is None:
            selected_benchmark = (
                db.query(Benchmark).filter(Benchmark.is_default.is_(True)).first()
            )
        return {
            "metrics": {"error": "No trades found."},
            "equity_curve": [],
            "comparison_curve": [],
            "benchmark": benchmark_to_dict(db, selected_benchmark)
            if selected_benchmark
            else None,
            "selected_strategies": [s.id for s in selected_strategies],
            "history_type": history_type,
        }

    combined_deals = pd.concat(deal_frames).sort_index()
    combined_equity = _combine_equity_frames(equity_frames)

    metrics = calculate_metrics_from_df(combined_deals, combined_equity, advanced=True)
    if (
        initial_balance
        and "Net Profit" in metrics
        and metrics["Net Profit"] is not None
    ):
        metrics["Return on Capital (%)"] = (
            metrics["Net Profit"] / initial_balance
        ) * 100

    equity_curve = []
    if not combined_equity.empty:
        equity_curve = [
            {"timestamp": to_iso(ts), "equity": float(v)}
            for ts, v in combined_equity["equity"].items()
        ]

    selected_benchmark = None
    if benchmark_id is not None:
        selected_benchmark = (
            db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
        )
        if benchmark_id is not None and not selected_benchmark:
            raise HTTPException(status_code=404, detail="Benchmark not found.")
    else:
        selected_benchmark = (
            db.query(Benchmark).filter(Benchmark.is_default.is_(True)).first()
        )

    comparison_curve: list[dict[str, object]] = []
    if not combined_equity.empty:
        chart_series = combined_equity["equity"].astype(float)
        chart_base = (
            float(initial_balance)
            if initial_balance and initial_balance > 0
            else float(chart_series.iloc[0])
        )
        benchmark_payload = (
            benchmark_to_dict(db, selected_benchmark) if selected_benchmark else None
        )

        if selected_benchmark:
            benchmark_df = load_benchmark_curve(
                db,
                selected_benchmark.id,
                date_from=dt_from,
                date_to=dt_to,
            )
            if not benchmark_df.empty:
                normalized_portfolio = _normalize_series_to_base(
                    chart_series, chart_base
                )
                normalized_benchmark = _normalize_series_to_base(
                    benchmark_df["close"].astype(float),
                    chart_base,
                )
                joined = (
                    pd.concat(
                        [
                            normalized_portfolio.rename("portfolio"),
                            normalized_benchmark.rename("benchmark"),
                        ],
                        axis=1,
                        join="outer",
                    )
                    .sort_index()
                    .ffill()
                    .dropna(how="all")
                )

                comparison_curve = [
                    {
                        "timestamp": to_iso(ts),
                        "portfolio": float(row["portfolio"])
                        if not pd.isna(row["portfolio"])
                        else None,
                        "benchmark": float(row["benchmark"])
                        if not pd.isna(row["benchmark"])
                        else None,
                    }
                    for ts, row in joined.iterrows()
                ]

                benchmark_return = _series_return_pct(
                    benchmark_df["close"].astype(float)
                )
                benchmark_drawdown = _series_max_drawdown_pct(
                    benchmark_df["close"].astype(float)
                )
                portfolio_return = _series_return_pct(chart_series)
                correlation = _series_correlation(
                    chart_series, benchmark_df["close"].astype(float)
                )

                metrics["Benchmark Return (%)"] = benchmark_return
                metrics["Benchmark Max Drawdown (%)"] = benchmark_drawdown
                metrics["Portfolio Return (%)"] = portfolio_return
                metrics["Excess Return vs Benchmark (%)"] = (
                    portfolio_return - benchmark_return
                    if portfolio_return is not None and benchmark_return is not None
                    else None
                )
                metrics["Correlation vs Benchmark"] = correlation
            else:
                metrics["Benchmark Status"] = (
                    "Selected benchmark has no synced local prices."
                )
        else:
            comparison_curve = [
                {
                    "timestamp": to_iso(ts),
                    "portfolio": float(v),
                    "benchmark": None,
                }
                for ts, v in chart_series.items()
            ]
        if not selected_benchmark:
            benchmark_payload = None
    else:
        benchmark_payload = (
            benchmark_to_dict(db, selected_benchmark) if selected_benchmark else None
        )

    return {
        "metrics": _sanitize_metrics(metrics),
        "equity_curve": equity_curve,
        "comparison_curve": comparison_curve,
        "benchmark": benchmark_payload,
        "selected_strategies": [s.id for s in selected_strategies],
        "history_type": history_type,
    }


# ── Backtest endpoints ────────────────────────────────────────────────────────


def _inject_bt_net_profit(bt: Backtest, db: Session) -> BacktestResponse:
    r = BacktestResponse.model_validate(bt)
    net = (
        db.query(
            func.sum(BacktestDeal.profit + BacktestDeal.commission + BacktestDeal.swap)
        )
        .filter(
            BacktestDeal.backtest_id == bt.id,
            BacktestDeal.type.in_([DealType.BUY, DealType.SELL]),
        )
        .scalar()
    )
    r.net_profit = round(float(net), 2) if net is not None else None
    return r


@router.post("/strategies/{strategy_id}/kill")
def kill_strategy(strategy_id: str, db: Session = Depends(get_db)):
    """Send a kill command to the active connection for this strategy."""
    s = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Strategy not found")

    success = send_kill_command(strategy_id)
    if not success:
        raise HTTPException(
            status_code=400,
            detail="Failed to send kill command. Strategy might not be connected.",
        )

    return {
        "status": "success",
        "message": f"Kill command sent to strategy {strategy_id}",
    }


@router.get(
    "/strategies/{strategy_id}/backtests", response_model=list[BacktestResponse]
)
def list_strategy_backtests(strategy_id: str, db: Session = Depends(get_db)):
    s = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Strategy not found")
    backtests = (
        db.query(Backtest)
        .filter(Backtest.strategy_id == strategy_id)
        .order_by(Backtest.created_at.desc())
        .all()
    )
    if not backtests:
        return []

    # Fetch all net_profits in a single query instead of N+1 calls.
    bt_ids = [bt.id for bt in backtests]
    net_profit_map: dict[int, float] = dict(
        db.query(
            BacktestDeal.backtest_id,
            func.sum(BacktestDeal.profit + BacktestDeal.commission + BacktestDeal.swap),
        )
        .filter(
            BacktestDeal.backtest_id.in_(bt_ids),
            BacktestDeal.type.in_([DealType.BUY, DealType.SELL]),
        )
        .group_by(BacktestDeal.backtest_id)
        .all()  # type: ignore[arg-type]
    )

    result = []
    for bt in backtests:
        r = BacktestResponse.model_validate(bt)
        net = net_profit_map.get(bt.id)
        r.net_profit = round(float(net), 2) if net is not None else None
        result.append(r)
    return result


@router.get("/backtests/{backtest_id}", response_model=BacktestResponse)
def get_backtest(backtest_id: int, db: Session = Depends(get_db)):
    bt = db.query(Backtest).filter(Backtest.id == backtest_id).first()
    if not bt:
        raise HTTPException(status_code=404, detail="Backtest not found")
    return _inject_bt_net_profit(bt, db)


@router.delete("/backtests/{backtest_id}", status_code=204)
def delete_backtest(backtest_id: int, db: Session = Depends(get_db)):
    bt = db.query(Backtest).filter(Backtest.id == backtest_id).first()
    if not bt:
        raise HTTPException(status_code=404, detail="Backtest not found")
    db.delete(bt)
    db.commit()


@router.get("/backtests/{backtest_id}/metrics")
def get_backtest_metrics(
    backtest_id: int,
    side: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    bt = db.query(Backtest).filter(Backtest.id == backtest_id).first()
    if not bt:
        raise HTTPException(status_code=404, detail="Backtest not found")
    from trademachine.tradingmonitor.metrics.calculator import calculate_metrics_from_df
    from trademachine.tradingmonitor.metrics.repository import (
        get_backtest_deals,
        get_backtest_equity,
    )

    try:
        deals_df = get_backtest_deals(backtest_id)
        side_values = [t.value for t in _side_types(side)]
        if not deals_df.empty:
            deals_df = deals_df[deals_df["type"].isin(side_values)]
        if side in ("long", "short"):
            equity_df = _synthetic_equity(deals_df)
        else:
            equity_df = get_backtest_equity(backtest_id)
        return _sanitize_metrics(calculate_metrics_from_df(deals_df, equity_df))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Metrics calculation failed: {e}")


@router.get(
    "/backtests/{backtest_id}/equity", response_model=list[BacktestEquityPointResponse]
)
def get_backtest_equity_endpoint(backtest_id: int, db: Session = Depends(get_db)):
    bt = db.query(Backtest).filter(Backtest.id == backtest_id).first()
    if not bt:
        raise HTTPException(status_code=404, detail="Backtest not found")
    return (
        db.query(BacktestEquity)
        .filter(BacktestEquity.backtest_id == backtest_id)
        .order_by(BacktestEquity.timestamp)
        .all()
    )


@router.get("/backtests/{backtest_id}/deals", response_model=PaginatedBacktestDeals)
def get_backtest_deals_endpoint(
    backtest_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    side: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    bt = db.query(Backtest).filter(Backtest.id == backtest_id).first()
    if not bt:
        raise HTTPException(status_code=404, detail="Backtest not found")
    base = db.query(BacktestDeal).filter(BacktestDeal.backtest_id == backtest_id)
    if side in ("long", "short"):
        base = base.filter(BacktestDeal.type.in_(_side_types(side)))
    total = base.count()
    deals = (
        base.order_by(BacktestDeal.timestamp.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PaginatedBacktestDeals(
        items=[BacktestDealResponse.from_orm(d) for d in deals],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/backtests/{backtest_id}/deals/export")
def export_backtest_deals(backtest_id: int, db: Session = Depends(get_db)):
    bt = db.query(Backtest).filter(Backtest.id == backtest_id).first()
    if not bt:
        raise HTTPException(status_code=404, detail="Backtest not found")

    def _csv_generator():
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "timestamp",
                "ticket",
                "backtest_id",
                "symbol",
                "type",
                "volume",
                "price",
                "profit",
                "commission",
                "swap",
            ]
        )
        yield output.getvalue()
        output.truncate(0)
        output.seek(0)

        query = (
            db.query(BacktestDeal)
            .filter(BacktestDeal.backtest_id == backtest_id)
            .order_by(BacktestDeal.timestamp)
        )
        for d in query.yield_per(1000):
            writer.writerow(
                [
                    to_iso(d.timestamp) or "",
                    d.ticket,
                    d.backtest_id,
                    d.symbol or "",
                    d.type.value if d.type else "",
                    d.volume,
                    d.price,
                    d.profit,
                    d.commission,
                    d.swap,
                ]
            )
            yield output.getvalue()
            output.truncate(0)
            output.seek(0)

    filename = f"backtest_{backtest_id}_{datetime.now(UTC).strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        _csv_generator(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/backtests/{backtest_id}/daily")
def get_backtest_daily(
    backtest_id: int,
    side: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    bt = db.query(Backtest).filter(Backtest.id == backtest_id).first()
    if not bt:
        raise HTTPException(status_code=404, detail="Backtest not found")
    rows = (
        db.query(
            cast(BacktestDeal.timestamp, Date).label("date"),
            func.sum(
                BacktestDeal.profit + BacktestDeal.commission + BacktestDeal.swap
            ).label("net_profit"),
        )
        .filter(BacktestDeal.backtest_id == backtest_id)
        .filter(BacktestDeal.type.in_(_side_types(side)))
        .group_by(cast(BacktestDeal.timestamp, Date))
        .order_by(cast(BacktestDeal.timestamp, Date))
        .all()
    )
    return [{"date": str(r.date), "net_profit": float(r.net_profit)} for r in rows]


@router.get("/backtests/{backtest_id}/trade-stats")
def get_backtest_trade_stats(
    backtest_id: int,
    side: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    bt = db.query(Backtest).filter(Backtest.id == backtest_id).first()
    if not bt:
        raise HTTPException(status_code=404, detail="Backtest not found")
    types = _side_types(side)

    def _q(group_expr):
        return (
            db.query(
                group_expr.label("key"),
                func.count().label("count"),
                func.sum(
                    BacktestDeal.profit + BacktestDeal.commission + BacktestDeal.swap
                ).label("net_profit"),
            )
            .filter(BacktestDeal.backtest_id == backtest_id)
            .filter(BacktestDeal.type.in_(types))
            .group_by(group_expr)
            .order_by(group_expr)
            .all()
        )

    hour_rows = _q(extract("hour", BacktestDeal.timestamp))
    dow_rows = _q(extract("isodow", BacktestDeal.timestamp))

    by_hour = [{"hour": h, "count": 0, "net_profit": 0.0} for h in range(24)]
    for r in hour_rows:
        h = int(r.key)
        by_hour[h] = {
            "hour": h,
            "count": int(r.count),
            "net_profit": round(float(r.net_profit or 0), 2),
        }

    DOW_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    by_dow = [
        {"dow": i + 1, "label": DOW_LABELS[i], "count": 0, "net_profit": 0.0}
        for i in range(7)
    ]
    for r in dow_rows:
        d = int(r.key) - 1
        by_dow[d] = {
            "dow": d + 1,
            "label": DOW_LABELS[d],
            "count": int(r.count),
            "net_profit": round(float(r.net_profit or 0), 2),
        }

    return {"by_hour": by_hour, "by_dow": by_dow}


# ── Settings ──────────────────────────────────────────────────────────────────


@router.get("/settings/telegram", response_model=TelegramSettings)
def get_telegram_settings(db: Session = Depends(get_db)):
    bot_token = db.query(Setting).filter(Setting.key == "telegram_bot_token").first()
    chat_id = db.query(Setting).filter(Setting.key == "telegram_chat_id").first()
    var_95_threshold = db.query(Setting).filter(Setting.key == "var_95_limit").first()
    default_ib = (
        db.query(Setting).filter(Setting.key == "default_initial_balance").first()
    )
    real_page_mode = _setting_str(db, "real_page_mode", default="real")
    if real_page_mode not in {"real", "demo"}:
        real_page_mode = "real"
    return TelegramSettings(
        bot_token=bot_token.value if bot_token else None,
        chat_id=chat_id.value if chat_id else None,
        var_95_threshold=float(var_95_threshold.value) if var_95_threshold else None,
        default_initial_balance=float(default_ib.value)
        if default_ib and default_ib.value
        else 100_000.0,
        real_page_mode=real_page_mode,
    )


@router.post("/settings/telegram", status_code=204)
def update_telegram_settings(payload: TelegramSettings, db: Session = Depends(get_db)):
    def _set(key, val):
        s = db.query(Setting).filter(Setting.key == key).first()
        if not s:
            s = Setting(key=key, value=str(val) if val is not None else "")
            db.add(s)
        else:
            s.value = str(val) if val is not None else ""

    _set("telegram_bot_token", payload.bot_token)
    _set("telegram_chat_id", payload.chat_id)
    _set("var_95_limit", payload.var_95_threshold)
    _set("default_initial_balance", payload.default_initial_balance)
    _set("real_page_mode", payload.real_page_mode)
    db.commit()


@router.post("/settings/telegram/test")
def test_telegram_settings(db: Session = Depends(get_db)):
    bot_token = db.query(Setting).filter(Setting.key == "telegram_bot_token").first()
    chat_id = db.query(Setting).filter(Setting.key == "telegram_chat_id").first()

    if not bot_token or not bot_token.value:
        raise HTTPException(status_code=400, detail="Bot Token não configurado")
    if not chat_id or not chat_id.value:
        raise HTTPException(status_code=400, detail="Chat ID não configurado")

    import httpx

    try:
        resp = httpx.post(
            f"https://api.telegram.org/bot{bot_token.value}/sendMessage",
            json={
                "chat_id": chat_id.value,
                "text": "✅ Teste do TradingMonitor\n\nSe você está lendo esta mensagem, a integração com o Telegram está funcionando!",
            },
            timeout=10,
        )
        if resp.status_code != 200:
            raise HTTPException(
                status_code=502, detail=f"Erro do Telegram: {resp.text}"
            )
        return {"ok": True}
    except httpx.Timeout:
        raise HTTPException(status_code=504, detail="Timeout ao enviar mensagem")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── DataManager Settings ──────────────────────────────────────────────────────


@router.get("/settings/datamanager", response_model=DataManagerSettings)
def get_datamanager_settings(db: Session = Depends(get_db)):
    url = _setting_str(db, "datamanager_url", default=settings.datamanager_url)
    api_key = db.query(Setting).filter(Setting.key == "datamanager_api_key").first()
    timeout = db.query(Setting).filter(Setting.key == "datamanager_timeout").first()
    return DataManagerSettings(
        url=url,
        api_key=api_key.value
        if api_key and api_key.value
        else settings.datamanager_api_key,
        timeout=float(timeout.value)
        if timeout and timeout.value
        else settings.datamanager_timeout,
    )


@router.post("/settings/datamanager", status_code=204)
def update_datamanager_settings(
    payload: DataManagerSettings, db: Session = Depends(get_db)
):
    def _set(key: str, val: object) -> None:
        s = db.query(Setting).filter(Setting.key == key).first()
        if not s:
            s = Setting(key=key, value=str(val) if val is not None else "")
            db.add(s)
        else:
            s.value = str(val) if val is not None else ""

    _set("datamanager_url", payload.url)
    _set("datamanager_api_key", payload.api_key)
    _set("datamanager_timeout", payload.timeout)
    db.commit()


@router.post("/settings/datamanager/test")
def test_datamanager_settings(db: Session = Depends(get_db)):
    dm_settings = get_datamanager_settings(db)
    from trademachine.datamanager.client import DataManagerClient

    try:
        client = DataManagerClient(
            base_url=dm_settings.url,
            api_key=dm_settings.api_key,
            timeout=dm_settings.timeout,
        )
        dbs = client.list_databases()
        return {"ok": True, "databases_count": len(dbs)}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ── Ingestion Errors (Dead Letters) ──────────────────────────────────────────


@router.get("/ingestion-errors")
def list_ingestion_errors(
    limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db)
):
    from trademachine.tradingmonitor.db.models import IngestionError

    rows = (
        db.query(IngestionError)
        .order_by(IngestionError.timestamp.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "timestamp": to_iso(r.timestamp),
            "topic": r.topic,
            "error_message": r.error_message,
            "raw_message": r.raw_message,
        }
        for r in rows
    ]


@router.delete("/ingestion-errors", status_code=204)
def clear_ingestion_errors(db: Session = Depends(get_db)):
    from trademachine.tradingmonitor.db.models import IngestionError

    db.query(IngestionError).delete()
    db.commit()


# ── Portfolio Equity Breakdown ────────────────────────────────────────────────


@router.get("/portfolios/{portfolio_id}/equity/breakdown")
def get_portfolio_equity_breakdown(portfolio_id: int, db: Session = Depends(get_db)):
    p = _get_portfolio_or_404(db, portfolio_id)
    strategies = {s.id: s.name or s.id for s in p.strategies}
    if not strategies:
        return {"total": [], "strategies": {}}
    from trademachine.tradingmonitor.metrics.repository import get_strategy_equity_curve

    series = {}
    for sid in strategies:
        df = get_strategy_equity_curve(sid)
        if not df.empty:
            series[sid] = df["equity"].rename(sid)

    if not series:
        return {"total": [], "strategies": {}}

    combined_df = pd.concat(series.values(), axis=1).sort_index().ffill().fillna(0)
    total = combined_df.sum(axis=1)

    result_strategies = {}
    for sid, name in strategies.items():
        if sid in series:
            col = combined_df[sid]
            result_strategies[sid] = {
                "name": name,
                "points": [
                    {"timestamp": to_iso(ts), "equity": float(v)}
                    for ts, v in col.items()
                ],
            }

    return {
        "total": [
            {"timestamp": to_iso(ts), "equity": float(v)} for ts, v in total.items()
        ],
        "strategies": result_strategies,
    }


# ── Benchmarks ────────────────────────────────────────────────────────────────


@router.get("/benchmarks", response_model=list[BenchmarkResponse])
def list_benchmarks(db: Session = Depends(get_db)):
    benchmarks = (
        db.query(Benchmark)
        .order_by(Benchmark.is_default.desc(), Benchmark.name.asc())
        .all()
    )
    return [
        BenchmarkResponse.model_validate(benchmark_to_dict(db, b)) for b in benchmarks
    ]


@router.get(
    "/benchmarks/available-from-datamanager",
    response_model=list[BenchmarkRemoteDatabaseResponse],
)
def list_benchmarks_from_datamanager():
    return [
        BenchmarkRemoteDatabaseResponse.model_validate(row)
        for row in list_remote_databases()
    ]


@router.post("/benchmarks", response_model=BenchmarkResponse, status_code=201)
def create_benchmark(payload: BenchmarkCreate, db: Session = Depends(get_db)):
    source = payload.source.strip().upper()
    asset = payload.asset.strip().upper()
    timeframe = payload.timeframe.strip().upper()
    existing = (
        db.query(Benchmark)
        .filter(
            Benchmark.source == source,
            Benchmark.asset == asset,
            Benchmark.timeframe == timeframe,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Benchmark already exists")

    benchmark = Benchmark(
        name=payload.name.strip(),
        source=source,
        asset=asset,
        timeframe=timeframe,
        description=payload.description,
        enabled=payload.enabled,
        is_default=False,
    )
    db.add(benchmark)
    try:
        db.flush()
        if payload.is_default:
            set_default_benchmark(db, benchmark.id)
        db.commit()
        db.refresh(benchmark)
        return BenchmarkResponse.model_validate(benchmark_to_dict(db, benchmark))
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Benchmark already exists") from exc


@router.patch("/benchmarks/{benchmark_id}", response_model=BenchmarkResponse)
def update_benchmark(
    benchmark_id: int,
    payload: BenchmarkUpdate,
    db: Session = Depends(get_db),
):
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    data = payload.model_dump(exclude_unset=True)
    is_default = data.pop("is_default", None)
    candidate_source = benchmark.source
    candidate_asset = benchmark.asset
    candidate_timeframe = benchmark.timeframe
    for field, value in data.items():
        if field in {"source", "asset", "timeframe"} and isinstance(value, str):
            value = value.strip().upper()
        if field == "source":
            candidate_source = value
        elif field == "asset":
            candidate_asset = value
        elif field == "timeframe":
            candidate_timeframe = value
        setattr(benchmark, field, value)

    with db.no_autoflush:
        duplicate = (
            db.query(Benchmark)
            .filter(
                Benchmark.id != benchmark_id,
                Benchmark.source == candidate_source,
                Benchmark.asset == candidate_asset,
                Benchmark.timeframe == candidate_timeframe,
            )
            .first()
        )
    if duplicate:
        raise HTTPException(status_code=409, detail="Benchmark already exists")

    if is_default is True:
        set_default_benchmark(db, benchmark.id)
    elif is_default is False:
        benchmark.is_default = False

    try:
        db.commit()
        db.refresh(benchmark)
        return BenchmarkResponse.model_validate(benchmark_to_dict(db, benchmark))
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Benchmark already exists") from exc


@router.post("/benchmarks/{benchmark_id}/set-default", response_model=BenchmarkResponse)
def set_benchmark_default(benchmark_id: int, db: Session = Depends(get_db)):
    try:
        benchmark = set_default_benchmark(db, benchmark_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    db.refresh(benchmark)
    return BenchmarkResponse.model_validate(benchmark_to_dict(db, benchmark))


@router.post("/benchmarks/{benchmark_id}/sync")
def sync_benchmark(benchmark_id: int, db: Session = Depends(get_db)):
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    try:
        result = sync_benchmark_from_datamanager(db, benchmark)
        db.commit()
        return {**result, "benchmark": benchmark_to_dict(db, benchmark)}
    except Exception as exc:
        benchmark.last_error = str(exc)
        db.commit()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── Health check (item 8) ─────────────────────────────────────────────────────


# ── Symbols ───────────────────────────────────────────────────────────────────


@router.get("/symbols", response_model=list[SymbolResponse])
def list_symbols(db: Session = Depends(get_db)):
    # Subquery to count strategies by symbol name
    strat_counts = (
        db.query(Strategy.symbol, func.count(Strategy.id).label("count"))
        .group_by(Strategy.symbol)
        .subquery()
    )

    # Join Symbol with the strategy counts subquery
    symbols_data = (
        db.query(
            Symbol, func.coalesce(strat_counts.c.count, 0).label("strategies_count")
        )
        .outerjoin(strat_counts, Symbol.name == strat_counts.c.symbol)
        .order_by(Symbol.market, Symbol.name)
        .all()
    )

    # Transform to response schema
    result = []
    for sym, count in symbols_data:
        resp = SymbolResponse.model_validate(sym)
        resp.strategies_count = count
        result.append(resp)
    return result


@router.post("/symbols", response_model=SymbolResponse, status_code=201)
def create_symbol(payload: SymbolCreate, db: Session = Depends(get_db)):
    existing = db.query(Symbol).filter(Symbol.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Symbol already exists")
    sym = Symbol(name=payload.name, market=payload.market, lot=payload.lot)
    db.add(sym)
    db.commit()
    db.refresh(sym)
    return sym


@router.patch("/symbols/{symbol_id}", response_model=SymbolResponse)
def update_symbol(symbol_id: int, payload: SymbolUpdate, db: Session = Depends(get_db)):
    sym = db.query(Symbol).filter(Symbol.id == symbol_id).first()
    if not sym:
        raise HTTPException(status_code=404, detail="Symbol not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(sym, field, value)
    db.commit()
    db.refresh(sym)
    return sym


@router.delete("/symbols/{symbol_id}", status_code=204)
def delete_symbol(symbol_id: int, db: Session = Depends(get_db)):
    sym = db.query(Symbol).filter(Symbol.id == symbol_id).first()
    if not sym:
        raise HTTPException(status_code=404, detail="Symbol not found")
    db.delete(sym)
    db.commit()


# ── Floating P&L ──────────────────────────────────────────────────────────────


@router.get("/floating-pnl")
def get_floating_pnl(db: Session = Depends(get_db)):
    """Return per-strategy latest equity/balance and their floating P&L."""
    # Subquery: latest timestamp per strategy
    latest_ts = (
        db.query(
            EquityCurve.strategy_id, func.max(EquityCurve.timestamp).label("max_ts")
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


@router.get("/health")
def health_check(db: Session = Depends(get_db)):
    db_ok = False
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    from trademachine.tradingmonitor.ingestion.tcp_server import (
        get_ingestion_status,
        get_server_uptime_seconds,
    )

    ingestion = get_ingestion_status()
    return {
        "status": "ok" if db_ok else "degraded",
        "db_ok": db_ok,
        "heartbeat": ingestion.get("heartbeat"),
        "heartbeat_age_seconds": _heartbeat_age(ingestion.get("heartbeat")),
        "uptime_seconds": get_server_uptime_seconds(),
    }


def _heartbeat_age(heartbeat_ts: str | None) -> float | None:
    if not heartbeat_ts:
        return None
    try:
        hb_dt = datetime.fromisoformat(heartbeat_ts)
        if hb_dt.tzinfo is None:
            hb_dt = hb_dt.replace(tzinfo=UTC)
        return round((datetime.now(UTC) - hb_dt).total_seconds(), 1)
    except Exception:
        return None


# ── Ingestion status (item 7) ─────────────────────────────────────────────────


@router.get("/ingestion/status")
def ingestion_status():
    from trademachine.tradingmonitor.ingestion.tcp_server import get_ingestion_status

    return get_ingestion_status()


# ── CSV export (item 13) ──────────────────────────────────────────────────────

_DEAL_FIELDS = [
    "timestamp",
    "ticket",
    "strategy_id",
    "symbol",
    "type",
    "volume",
    "price",
    "profit",
    "commission",
    "swap",
]


def _deals_generator(query):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(_DEAL_FIELDS)
    yield output.getvalue()
    output.truncate(0)
    output.seek(0)

    for d in query.yield_per(1000):
        writer.writerow(
            [
                to_iso(d.timestamp) or "",
                d.ticket,
                d.strategy_id,
                d.symbol or "",
                d.type.value if d.type else "",
                d.volume,
                d.price,
                d.profit,
                d.commission,
                d.swap,
            ]
        )
        yield output.getvalue()
        output.truncate(0)
        output.seek(0)


@router.get("/strategies/{strategy_id}/deals/export")
def export_strategy_deals(strategy_id: str, db: Session = Depends(get_db)):
    strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    query = (
        db.query(Deal).filter(Deal.strategy_id == strategy_id).order_by(Deal.timestamp)
    )
    filename = f"deals_{strategy_id}_{datetime.now(UTC).strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        _deals_generator(query),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/portfolios/{portfolio_id}/export")
def export_portfolio_deals(portfolio_id: int, db: Session = Depends(get_db)):
    p = _get_portfolio_or_404(db, portfolio_id)
    strategy_ids = _get_portfolio_strategy_ids(
        p,
        required_count=1,
        detail="No strategies in portfolio",
        status_code=404,
    )
    query = (
        db.query(Deal)
        .filter(Deal.strategy_id.in_(strategy_ids))
        .order_by(Deal.timestamp)
    )
    filename = f"portfolio_{portfolio_id}_{datetime.now(UTC).strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        _deals_generator(query),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── MT5 Backtest HTML Upload ───────────────────────────────────────────────────


def _soup_from_bytes(content: bytes) -> BeautifulSoup:
    for encoding in ("utf-16", "utf-8", "latin-1"):
        try:
            return BeautifulSoup(content.decode(encoding), "lxml")
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ValueError(
        "Não foi possível decodificar o arquivo HTML (tentativas: utf-16, utf-8, latin-1)"
    )


def _parse_mt5_date(date_str: str | None) -> datetime | None:
    """Parse 'YYYY.MM.DD' string to UTC datetime."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y.%m.%d").replace(tzinfo=UTC)
    except ValueError:
        return None


def _parse_mt5_timestamp(ts_str: str) -> datetime | None:
    """Parse 'YYYY.MM.DD HH:MM:SS' to UTC datetime."""
    for fmt in ("%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M"):
        try:
            return datetime.strptime(ts_str.strip(), fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _first_col(df: pd.DataFrame, *names: str) -> str | None:
    for name in names:
        if name in df.columns:
            return name
    return None


def _to_float(val: str, default: float = 0.0) -> float:
    try:
        return float(str(val).replace(" ", "").replace(",", "."))
    except (ValueError, TypeError):
        return default


def _to_int(val: str, default: int = 0) -> int:
    try:
        return int(str(val).strip())
    except (ValueError, TypeError):
        return default


_DEAL_TYPE_MAP = {
    "buy": DealType.BUY,
    "sell": DealType.SELL,
    "balance": DealType.BALANCE,
}


def _parse_deal_type(raw: str) -> DealType | None:
    return _DEAL_TYPE_MAP.get(raw.strip().lower())


async def _process_single_html_upload(
    upload_file: UploadFile,
    magic_number_override: str | None,
    db: Session,
    parser: MT5ReportParser,
) -> dict:
    result: dict = {
        "filename": upload_file.filename,
        "status": "ok",
        "backtest_id": None,
        "deals_imported": 0,
        "error": None,
    }
    try:
        content = await upload_file.read()
        soup = _soup_from_bytes(content)
        metadata = parser.extract_metadata(soup)

        magic_number = magic_number_override or metadata.get("Magic_Number")
        if not magic_number:
            raise ValueError("Magic Number não encontrado no relatório")

        strategy = db.query(Strategy).filter(Strategy.id == magic_number).first()
        if not strategy:
            raise ValueError(
                f"Estratégia com Magic Number {magic_number} não cadastrada"
            )

        report_name = metadata.get("Expert_Advisor")
        if report_name:
            strategy.name = report_name
        if not strategy.timeframe:
            report_tf = metadata.get("Timeframe")
            if report_tf:
                strategy.timeframe = report_tf
        db.flush()

        client_run_id = int(hashlib.md5(content).hexdigest()[:15], 16)  # noqa: S324

        existing = (
            db.query(Backtest)
            .filter(
                Backtest.strategy_id == magic_number,
                Backtest.client_run_id == client_run_id,
            )
            .first()
        )
        if existing:
            db.commit()
            result["status"] = "skipped"
            result["backtest_id"] = existing.id
            result["error"] = "Relatório já importado anteriormente"
            return result

        deals_df = parser.extract_table_by_header(soup, "Transações")
        if deals_df.empty:
            deals_df = parser.extract_table_by_header(soup, "Deals")
            if not deals_df.empty:
                deals_df = deals_df.rename(columns=_EN_TO_PT_COLUMNS)
        if deals_df.empty:
            raise ValueError("Tabela de transações não encontrada no relatório")

        deals_df = parser._clean_deals_df(deals_df)

        col_ts = _first_col(deals_df, "Horário", "Time")
        col_ticket = _first_col(deals_df, "Posição", "Position", "Ticket", "#")
        col_symbol = _first_col(deals_df, "Símbolo", "Symbol")
        col_tipo = _first_col(deals_df, "Tipo", "Type")
        col_vol = _first_col(deals_df, "Volume")
        col_price = _first_col(deals_df, "Preço", "Price")
        col_comm = _first_col(deals_df, "Comissão", "Commission")
        col_swap = _first_col(deals_df, "Swap")
        col_profit = _first_col(deals_df, "Lucro", "Profit")
        col_balance = _first_col(deals_df, "Saldo", "Balance")

        if not col_ts or not col_tipo:
            raise ValueError("Colunas obrigatórias (Horário, Tipo) não encontradas")

        initial_balance: float | None = None
        if col_balance is not None:
            balance_rows = deals_df[
                deals_df[col_tipo].str.strip().str.lower() == "balance"
            ]
            if not balance_rows.empty:
                initial_balance = _to_float(balance_rows.iloc[0][col_balance])

        start_dt = _parse_mt5_date(metadata.get("Periodo_Inicial"))
        end_dt = _parse_mt5_date(metadata.get("Periodo_Final"))
        symbol = metadata.get("Ativo")

        backtest = Backtest(
            strategy_id=magic_number,
            client_run_id=client_run_id,
            name=metadata.get("Expert_Advisor") or upload_file.filename,
            symbol=symbol,
            start_date=start_dt,
            end_date=end_dt,
            initial_balance=initial_balance,
            status="complete",
        )
        db.add(backtest)
        db.flush()

        deals_imported = _import_deals_from_dataframe(
            db,
            backtest.id,
            deals_df,
            symbol,
            col_ts,
            col_ticket,
            col_symbol,
            col_tipo,
            col_vol,
            col_price,
            col_comm,
            col_swap,
            col_profit,
            col_balance,
        )

        db.commit()
        result["backtest_id"] = backtest.id
        result["deals_imported"] = deals_imported

    except Exception as exc:
        db.rollback()
        logger.exception("Erro ao processar upload: %s", upload_file.filename)
        result["status"] = "error"
        result["error"] = str(exc)

    return result


def _import_deals_from_dataframe(
    db: Session,
    backtest_id: int,
    deals_df: pd.DataFrame,
    symbol: str | None,
    col_ts: str | None,
    col_ticket: str | None,
    col_symbol: str | None,
    col_tipo: str | None,
    col_vol: str | None,
    col_price: str | None,
    col_comm: str | None,
    col_swap: str | None,
    col_profit: str | None,
    col_balance: str | None,
) -> int:
    deals_imported = 0
    for _, row in deals_df.iterrows():
        ts_raw = row[col_ts] if col_ts else ""
        ts = _parse_mt5_timestamp(str(ts_raw))
        if ts is None:
            continue

        tipo_raw = str(row[col_tipo]) if col_tipo else ""
        deal_type = _parse_deal_type(tipo_raw)
        if deal_type is None:
            continue

        ticket = _to_int(row[col_ticket]) if col_ticket else 0
        row_symbol = (
            str(row[col_symbol]).strip()
            if col_symbol and row[col_symbol]
            else (symbol or "")
        )
        volume = _to_float(row[col_vol]) if col_vol else 0.0
        price = _to_float(row[col_price]) if col_price else 0.0
        commission = _to_float(row[col_comm]) if col_comm else 0.0
        swap = _to_float(row[col_swap]) if col_swap else 0.0
        profit = _to_float(row[col_profit]) if col_profit else 0.0
        balance = _to_float(row[col_balance]) if col_balance else 0.0

        db.add(
            BacktestDeal(
                backtest_id=backtest_id,
                timestamp=ts,
                ticket=ticket,
                symbol=row_symbol,
                type=deal_type,
                volume=volume,
                price=price,
                profit=profit,
                commission=commission,
                swap=swap,
            )
        )
        if col_balance:
            db.add(
                BacktestEquity(
                    backtest_id=backtest_id,
                    timestamp=ts,
                    balance=balance,
                    equity=balance,
                )
            )
        deals_imported += 1
    return deals_imported


@router.post("/backtests/upload-html")
async def upload_backtest_html(
    files: list[UploadFile] = File(...),
    magic_number_override: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    """
    Upload one or more MT5 HTML backtest reports.

    Returns a per-file result list with status, backtest_id, and any errors.
    """
    parser = MT5ReportParser()
    results = []

    for upload_file in files:
        result = await _process_single_html_upload(
            upload_file, magic_number_override, db, parser
        )
        results.append(result)

    return results
