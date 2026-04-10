import csv
import hashlib
import io
import logging
import math
from datetime import UTC, datetime
from typing import Any, Literal

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
from sqlalchemy import cast, func, or_, text
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.types import Date
from trademachine.mt5.parser import (
    _EN_TO_PT_COLUMNS,
    MT5ReportParser,
)
from trademachine.tradingmonitor_analytics.public import (
    BenchmarkConflictError,
    BenchmarkNotFoundError,
    DashboardAnalysisNotFoundError,
    DashboardAnalysisValidationError,
    DashboardHistoryNotFoundError,
    DashboardMetricsNotFoundError,
    DashboardStrategiesNotFoundError,
    create_benchmark_record,
    delete_benchmark_record,
    get_advanced_analysis_payload,
    get_backtest_daily_payload,
    get_backtest_deals_payload,
    get_backtest_equity_payload,
    get_backtest_metrics_payload,
    get_backtest_payload,
    get_backtest_trade_stats_payload,
    get_portfolio_equity_breakdown_payload,
    get_portfolio_equity_payload,
    get_portfolio_metrics_payload,
    get_portfolio_strategies_payload,
    get_real_daily_payload,
    get_real_overview_payload,
    get_real_recent_deals_payload,
    get_strategy_daily_payload,
    get_strategy_deals_payload,
    get_strategy_equity_payload,
    get_strategy_metrics_payload,
    get_strategy_trade_stats_payload,
    get_summary_payload,
    list_benchmark_payloads,
    list_portfolios_payload,
    list_remote_databases,
    list_strategies_payload,
    list_strategy_backtests_payload,
    load_benchmark_curve,
    set_default_benchmark_record,
    sync_benchmark_record,
    update_benchmark_record,
)
from trademachine.tradingmonitor_analytics.public import (
    compute_max_drawdown as _compute_max_drawdown,
)
from trademachine.tradingmonitor_ingestion.public import (
    invalidate_cache,
    send_kill_command,
    test_datamanager_connection,
)
from trademachine.tradingmonitor_storage.public import (
    Account,
    AccountResponse,
    AccountUpdate,
    Backtest,
    BacktestDeal,
    BacktestEquity,
    BacktestEquityPointResponse,
    BacktestResponse,
    BenchmarkCreate,
    BenchmarkRemoteDatabaseResponse,
    BenchmarkResponse,
    BenchmarkUpdate,
    DataManagerSettings,
    Deal,
    DealType,
    EquityCurve,
    EquityPointResponse,
    IngestionError,
    PaginatedBacktestDeals,
    PaginatedDeals,
    Portfolio,
    PortfolioCreate,
    PortfolioResponse,
    PortfolioUpdate,
    Setting,
    Strategy,
    StrategyResponse,
    StrategyUpdate,
    SummaryResponse,
    Symbol,
    SymbolCreate,
    SymbolResponse,
    SymbolUpdate,
    TelegramSettings,
    get_db,
    settings,
    to_iso,
)
from trademachine.tradingmonitor_storage.public import (
    get_datamanager_settings as load_datamanager_settings,
)
from trademachine.tradingmonitor_storage.public import (
    update_datamanager_settings as save_datamanager_settings,
)

logger = logging.getLogger(__name__)
REAL_OVERVIEW_MAX_POINTS_PER_STRATEGY = 2_000


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
    return get_summary_payload(db)


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


@router.get("/real")
def get_real_overview(
    max_points_per_strategy: int = Query(
        default=REAL_OVERVIEW_MAX_POINTS_PER_STRATEGY, ge=100, le=10_000
    ),
    db: Session = Depends(get_db),
):
    return get_real_overview_payload(
        db,
        max_points_per_strategy=max_points_per_strategy,
    )


@router.get("/real/daily")
def get_real_daily(
    db: Session = Depends(get_db),
):
    return get_real_daily_payload(db)


@router.get("/real/recent-deals")
def get_real_recent_deals(
    limit: int = Query(default=20, ge=1, le=250),
    db: Session = Depends(get_db),
):
    return get_real_recent_deals_payload(db, limit=limit)


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
        .all()
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
def list_strategies(
    history_type: Literal["backtest", "demo", "real"] | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return list_strategies_payload(db, history_type)


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


@router.get("/portfolios/nav", response_model=list[dict[str, Any]])
def list_portfolios_nav(db: Session = Depends(get_db)):
    rows = (
        db.query(Portfolio.id, Portfolio.name)
        .order_by(Portfolio.name.asc().nullslast(), Portfolio.id.asc())
        .all()
    )
    return [{"id": row.id, "name": row.name} for row in rows]


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
    try:
        return _sanitize_metrics(get_strategy_metrics_payload(db, strategy_id, side))
    except DashboardMetricsNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Metrics calculation failed: {e}")


@router.get("/strategies/{strategy_id}/trade-stats")
def get_strategy_trade_stats(
    strategy_id: str,
    side: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    try:
        return get_strategy_trade_stats_payload(db, strategy_id, side)
    except DashboardHistoryNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/strategies/{strategy_id}/daily")
def get_strategy_daily(
    strategy_id: str,
    side: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    try:
        return get_strategy_daily_payload(db, strategy_id, side)
    except DashboardHistoryNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get(
    "/strategies/{strategy_id}/equity", response_model=list[EquityPointResponse]
)
def get_strategy_equity(
    strategy_id: str,
    side: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    try:
        return get_strategy_equity_payload(db, strategy_id, side)
    except DashboardMetricsNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/strategies/{strategy_id}/deals", response_model=PaginatedDeals)
def get_strategy_deals(
    strategy_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    q: str | None = Query(default=None),
    side: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    try:
        return get_strategy_deals_payload(
            db,
            strategy_id,
            page=page,
            page_size=page_size,
            q=q,
            side=side,
        )
    except DashboardHistoryNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/portfolios", response_model=list[PortfolioResponse])
def list_portfolios(
    mode: Literal["backtest", "demo", "real"] = Query(default="demo"),
    db: Session = Depends(get_db),
):
    return list_portfolios_payload(db, mode)


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
    try:
        return get_portfolio_strategies_payload(db, portfolio_id)
    except DashboardStrategiesNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


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
    try:
        payload = get_portfolio_equity_payload(db, portfolio_id)
        return [
            {"timestamp": to_iso(point["timestamp"]), "equity": point["equity"]}
            for point in payload
        ]
    except DashboardMetricsNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


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
    from trademachine.tradingmonitor_analytics.metrics.calculator import (
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
    from trademachine.tradingmonitor_analytics.metrics.calculator import (
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
    from trademachine.tradingmonitor_analytics.metrics.calculator import (
        calculate_concurrency,
    )

    return calculate_concurrency(strategy_ids, since=_ensure_utc(since))


@router.get("/portfolios/{portfolio_id}/metrics")
def get_portfolio_metrics(portfolio_id: int, db: Session = Depends(get_db)):
    try:
        return _sanitize_metrics(get_portfolio_metrics_payload(db, portfolio_id))
    except DashboardMetricsNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Metrics calculation failed: {e}")


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

    from trademachine.tradingmonitor_analytics.metrics.repository import (
        get_strategy_deals,
    )

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


def _build_comparison_curve(
    db: Session,
    chart_series: pd.Series,
    selected_benchmark,
    dt_from: datetime | None,
    dt_to: datetime | None,
    metrics: dict[str, object],
) -> list[dict[str, object]]:
    if not selected_benchmark:
        return [
            {
                "timestamp": to_iso(ts),
                "portfolio": float(v),
                "benchmark": None,
            }
            for ts, v in chart_series.items()
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
                "timestamp": to_iso(ts),
                "portfolio": float(v),
                "benchmark": None,
            }
            for ts, v in chart_series.items()
        ]

    first_equity = float(chart_series.iloc[0])
    scaled_benchmark = _normalize_series_to_base(
        benchmark_df["close"].astype(float),
        first_equity,
    )
    joined = (
        pd.concat(
            [
                chart_series.rename("portfolio"),
                scaled_benchmark.rename("benchmark"),
            ],
            axis=1,
            join="outer",
        )
        .sort_index()
        .ffill()
        .dropna(how="all")
    )

    benchmark_return = _series_return_pct(benchmark_df["close"].astype(float))
    benchmark_drawdown = _series_max_drawdown_pct(benchmark_df["close"].astype(float))
    portfolio_return = _series_return_pct(chart_series)
    correlation = _series_correlation(chart_series, benchmark_df["close"].astype(float))

    metrics["Benchmark Return"] = benchmark_return
    metrics["Benchmark Drawdown"] = benchmark_drawdown
    metrics["Portfolio Return (%)"] = portfolio_return
    metrics["Excess Return vs Benchmark (%)"] = (
        portfolio_return - benchmark_return
        if portfolio_return is not None and benchmark_return is not None
        else None
    )
    metrics["Correlation vs Benchmark"] = correlation

    return [
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


def _collect_deal_and_equity_frames(
    db: Session,
    history_type: str,
    selected_strategies,
    dt_from: datetime | None,
    dt_to: datetime | None,
) -> tuple[list[pd.DataFrame], list[pd.DataFrame]]:
    from trademachine.tradingmonitor_analytics.metrics.repository import (
        get_backtest_deals,
        get_backtest_equity,
        get_strategy_deals,
        get_strategy_equity_curve,
    )

    deal_frames: list[pd.DataFrame] = []
    equity_frames: list[pd.DataFrame] = []

    if history_type == "backtest":
        backtests = (
            db.query(Backtest)
            .filter(Backtest.strategy_id.in_([s.id for s in selected_strategies]))
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

    return deal_frames, equity_frames


@router.get("/advanced-analysis")
def get_advanced_analysis(
    strategy_ids: list[str] = Query(default=[]),
    history_type: str = Query(default="real"),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    initial_balance: float | None = Query(default=None),
    benchmark_id: int | None = Query(default=None),
    side: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    try:
        payload = get_advanced_analysis_payload(
            db,
            strategy_ids=strategy_ids,
            history_type=history_type,
            date_from=date_from,
            date_to=date_to,
            initial_balance=initial_balance,
            benchmark_id=benchmark_id,
            side=side,
        )
        payload["metrics"] = _sanitize_metrics(payload["metrics"])
        return payload
    except DashboardAnalysisNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except DashboardAnalysisValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


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
    try:
        return list_strategy_backtests_payload(db, strategy_id)
    except DashboardAnalysisNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/backtests/{backtest_id}", response_model=BacktestResponse)
def get_backtest(backtest_id: int, db: Session = Depends(get_db)):
    try:
        return get_backtest_payload(db, backtest_id)
    except DashboardAnalysisNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


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
    try:
        return _sanitize_metrics(get_backtest_metrics_payload(db, backtest_id, side))
    except DashboardMetricsNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Metrics calculation failed: {e}")


@router.get(
    "/backtests/{backtest_id}/equity", response_model=list[BacktestEquityPointResponse]
)
def get_backtest_equity_endpoint(
    backtest_id: int,
    side: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    try:
        return get_backtest_equity_payload(db, backtest_id, side)
    except DashboardMetricsNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/backtests/{backtest_id}/deals", response_model=PaginatedBacktestDeals)
def get_backtest_deals_endpoint(
    backtest_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    side: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    try:
        return get_backtest_deals_payload(
            db,
            backtest_id,
            page=page,
            page_size=page_size,
            side=side,
        )
    except DashboardHistoryNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


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
    try:
        return get_backtest_daily_payload(db, backtest_id, side)
    except DashboardHistoryNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/backtests/{backtest_id}/trade-stats")
def get_backtest_trade_stats(
    backtest_id: int,
    side: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    try:
        return get_backtest_trade_stats_payload(db, backtest_id, side)
    except DashboardHistoryNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


# ── Settings ──────────────────────────────────────────────────────────────────


@router.get("/settings/telegram", response_model=TelegramSettings)
def get_telegram_settings(db: Session = Depends(get_db)):
    bot_token = db.query(Setting).filter(Setting.key == "telegram_bot_token").first()
    chat_id = db.query(Setting).filter(Setting.key == "telegram_chat_id").first()
    notify_closed_trades = _setting_bool(
        db, "telegram_notify_closed_trades", default=False
    )
    notify_system_errors = _setting_bool(
        db, "telegram_notify_system_errors", default=False
    )
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
        notify_closed_trades=notify_closed_trades,
        notify_system_errors=notify_system_errors,
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
    _set("telegram_notify_closed_trades", payload.notify_closed_trades)
    _set("telegram_notify_system_errors", payload.notify_system_errors)
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
    except httpx.Timeout:  # type: ignore[misc]
        raise HTTPException(status_code=504, detail="Timeout ao enviar mensagem")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── DataManager Settings ──────────────────────────────────────────────────────


@router.get("/settings/datamanager", response_model=DataManagerSettings)
def get_datamanager_settings(db: Session = Depends(get_db)):
    return load_datamanager_settings(db)


@router.post("/settings/datamanager", status_code=204)
def update_datamanager_settings(
    payload: DataManagerSettings, db: Session = Depends(get_db)
):
    save_datamanager_settings(db, payload)


@router.post("/settings/datamanager/test")
def test_datamanager_settings(db: Session = Depends(get_db)):
    try:
        return test_datamanager_connection(db)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ── Ingestion Errors (Dead Letters) ──────────────────────────────────────────


@router.get("/ingestion-errors")
def list_ingestion_errors(
    limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db)
):
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
    db.query(IngestionError).delete()
    db.commit()


# ── Portfolio Equity Breakdown ────────────────────────────────────────────────


@router.get("/portfolios/{portfolio_id}/equity/breakdown")
def get_portfolio_equity_breakdown(portfolio_id: int, db: Session = Depends(get_db)):
    try:
        payload = get_portfolio_equity_breakdown_payload(db, portfolio_id)
        return {
            "total": [
                {"timestamp": to_iso(point["timestamp"]), "equity": point["equity"]}
                for point in payload["total"]
            ],
            "strategies": {
                strategy_id: {
                    "name": strategy_payload["name"],
                    "points": [
                        {
                            "timestamp": to_iso(point["timestamp"]),
                            "equity": point["equity"],
                        }
                        for point in strategy_payload["points"]
                    ],
                }
                for strategy_id, strategy_payload in payload["strategies"].items()
            },
        }
    except DashboardMetricsNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


# ── Benchmarks ────────────────────────────────────────────────────────────────


@router.get("/benchmarks", response_model=list[BenchmarkResponse])
def list_benchmarks(db: Session = Depends(get_db)):
    return [
        BenchmarkResponse.model_validate(payload)
        for payload in list_benchmark_payloads(db)
    ]


@router.get(
    "/benchmarks/available-from-datamanager",
    response_model=list[BenchmarkRemoteDatabaseResponse],
)
def list_benchmarks_from_datamanager(db: Session = Depends(get_db)):
    try:
        rows = list_remote_databases(db)
    except Exception:
        raise HTTPException(
            status_code=503, detail="DataManager service is unavailable"
        )
    return [BenchmarkRemoteDatabaseResponse.model_validate(row) for row in rows]


@router.post("/benchmarks", response_model=BenchmarkResponse, status_code=201)
def create_benchmark(payload: BenchmarkCreate, db: Session = Depends(get_db)):
    try:
        return BenchmarkResponse.model_validate(
            create_benchmark_record(
                db,
                name=payload.name,
                source=payload.source,
                asset=payload.asset,
                timeframe=payload.timeframe,
                description=payload.description,
                enabled=payload.enabled,
                is_default=payload.is_default,
            )
        )
    except BenchmarkConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.patch("/benchmarks/{benchmark_id}", response_model=BenchmarkResponse)
def update_benchmark(
    benchmark_id: int,
    payload: BenchmarkUpdate,
    db: Session = Depends(get_db),
):
    try:
        return BenchmarkResponse.model_validate(
            update_benchmark_record(
                db, benchmark_id, payload.model_dump(exclude_unset=True)
            )
        )
    except BenchmarkNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BenchmarkConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/benchmarks/{benchmark_id}/set-default", response_model=BenchmarkResponse)
def set_benchmark_default(benchmark_id: int, db: Session = Depends(get_db)):
    try:
        return BenchmarkResponse.model_validate(
            set_default_benchmark_record(db, benchmark_id)
        )
    except BenchmarkNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/benchmarks/{benchmark_id}/sync")
def sync_benchmark(benchmark_id: int, db: Session = Depends(get_db)):
    try:
        return sync_benchmark_record(db, benchmark_id)
    except BenchmarkNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/benchmarks/{benchmark_id}", status_code=204)
def delete_benchmark(benchmark_id: int, db: Session = Depends(get_db)):
    try:
        delete_benchmark_record(db, benchmark_id)
    except BenchmarkNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ── Health check (item 8) ─────────────────────────────────────────────────────


# ── Symbols ───────────────────────────────────────────────────────────────────


@router.get("/symbols", response_model=list[SymbolResponse])
def list_symbols(db: Session = Depends(get_db)):
    # Subquery to count strategies by symbol FK
    strat_counts = (
        db.query(Strategy.symbol_id, func.count(Strategy.id).label("count"))
        .group_by(Strategy.symbol_id)
        .subquery()
    )

    # Join Symbol with the strategy counts subquery
    symbols_data = (
        db.query(
            Symbol, func.coalesce(strat_counts.c.count, 0).label("strategies_count")
        )
        .outerjoin(strat_counts, Symbol.id == strat_counts.c.symbol_id)
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
    changes = payload.model_dump(exclude_unset=True)
    new_name = changes.get("name")
    if new_name is not None:
        existing = (
            db.query(Symbol)
            .filter(Symbol.name == new_name, Symbol.id != symbol_id)
            .first()
        )
        if existing:
            raise HTTPException(status_code=409, detail="Symbol already exists")
    for field, value in changes.items():
        setattr(sym, field, value)
    if new_name is not None:
        db.query(Strategy).filter(Strategy.symbol_id == symbol_id).update(
            {"symbol": new_name},
            synchronize_session=False,
        )
        db.query(Backtest).filter(Backtest.symbol_id == symbol_id).update(
            {"symbol": new_name},
            synchronize_session=False,
        )
    db.commit()
    db.refresh(sym)
    return sym


@router.delete("/symbols/{symbol_id}", status_code=204)
def delete_symbol(symbol_id: int, db: Session = Depends(get_db)):
    sym = db.query(Symbol).filter(Symbol.id == symbol_id).first()
    if not sym:
        raise HTTPException(status_code=404, detail="Symbol not found")
    if db.query(Strategy.id).filter(Strategy.symbol_id == symbol_id).first():
        raise HTTPException(
            status_code=409,
            detail="Symbol is still referenced by strategies",
        )
    if db.query(Backtest.id).filter(Backtest.symbol_id == symbol_id).first():
        raise HTTPException(
            status_code=409,
            detail="Symbol is still referenced by backtests",
        )
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

    from trademachine.tradingmonitor_ingestion.public import (
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
    from trademachine.tradingmonitor_ingestion.public import (
        get_ingestion_status,
    )

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
        symbol_id = None
        if symbol:
            symbol_row = db.query(Symbol).filter(Symbol.name == symbol).first()
            if symbol_row is None:
                symbol_row = Symbol(name=symbol)
                db.add(symbol_row)
                db.flush()
            symbol_id = symbol_row.id

        backtest = Backtest(
            strategy_id=magic_number,
            client_run_id=client_run_id,
            name=metadata.get("Expert_Advisor") or upload_file.filename,
            symbol=symbol,
            symbol_id=symbol_id,
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
