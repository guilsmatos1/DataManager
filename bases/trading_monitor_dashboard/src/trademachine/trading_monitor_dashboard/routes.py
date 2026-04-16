import csv
import io
import logging
import math
from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Security,
    UploadFile,
)
from fastapi.responses import StreamingResponse
from fastapi.security import APIKeyHeader
from sqlalchemy import text
from sqlalchemy.orm import Session, joinedload
from trademachine.mt5.parser import (
    MT5ReportParser,
)
from trademachine.tradingmonitor_analytics.public import (
    BenchmarkConflictError,
    BenchmarkNotFoundError,
    DashboardAnalysisNotFoundError,
    DashboardAnalysisValidationError,
    DashboardHistoryNotFoundError,
    DashboardMetricsNotFoundError,
    DashboardMetricsValidationError,
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
    get_floating_pnl_payload,
    get_portfolio_contributions_payload,
    get_portfolio_daily_payload,
    get_portfolio_deals_payload,
    get_portfolio_equity_breakdown_payload,
    get_portfolio_equity_payload,
    get_portfolio_metrics_payload,
    get_portfolio_strategies_payload,
    get_portfolio_trade_stats_payload,
    get_real_daily_payload,
    get_real_overview_payload,
    get_real_recent_deals_payload,
    get_strategy_daily_payload,
    get_strategy_deals_payload,
    get_strategy_equity_payload,
    get_strategy_metrics_payload,
    get_strategy_trade_stats_payload,
    get_summary_payload,
    list_accounts_payload,
    list_benchmark_payloads,
    list_portfolios_payload,
    list_remote_databases,
    list_strategies_payload,
    list_strategy_backtests_payload,
    list_symbols_payload,
    run_benchmark_auto_sync,
    set_default_benchmark_record,
    sync_benchmark_record,
    update_benchmark_record,
)
from trademachine.tradingmonitor_ingestion.public import (
    invalidate_cache,
    send_kill_command,
    test_datamanager_connection,
)
from trademachine.tradingmonitor_storage.public import (  # noqa: F401
    Account,
    AccountResponse,
    AccountUpdate,
    AdvancedAnalysisResponse,
    Backtest,
    BacktestDeal,
    BacktestEquity,
    BacktestEquityPointResponse,
    BacktestResponse,
    BenchmarkCreate,
    BenchmarkRemoteDatabaseResponse,
    BenchmarkResponse,
    BenchmarkSchedulerSettings,
    BenchmarkUpdate,
    ConcurrencyResponse,
    ContributionsResponse,
    CorrelationResponse,
    DailyProfitRow,
    DataManagerSettings,
    Deal,
    DynamicCorrelationResponse,
    EquityBreakdownResponse,
    EquityPointResponse,
    EquityTimestampPoint,
    FloatingPnlResponse,
    HealthResponse,
    IngestionError,
    IngestionErrorResponse,
    IngestionStatusResponse,
    MetricsResponse,
    PaginatedBacktestDeals,
    PaginatedDeals,
    Portfolio,
    PortfolioCreate,
    PortfolioResponse,
    PortfolioUpdate,
    RealOverviewResponse,
    RecentDeal,
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
    get_telegram_settings_payload,
    notifier,
    settings,
    to_iso,
    update_telegram_settings_payload,
)
from trademachine.tradingmonitor_storage.public import (
    get_benchmark_scheduler_settings as load_benchmark_scheduler_settings,
)
from trademachine.tradingmonitor_storage.public import (
    get_datamanager_settings as load_datamanager_settings,
)
from trademachine.tradingmonitor_storage.public import (
    update_benchmark_scheduler_settings as save_benchmark_scheduler_settings,
)
from trademachine.tradingmonitor_storage.public import (
    update_datamanager_settings as save_datamanager_settings,
)

logger = logging.getLogger(__name__)
REAL_OVERVIEW_MAX_POINTS_PER_STRATEGY = 2_000


# ── Authentication ────────────────────────────────────────────────────────────

API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)


def get_api_key(request: Request, api_key: str | None = Security(api_key_header)):
    if api_key != settings.api_key:
        cookie_key = request.cookies.get("tm_session_key")
        if cookie_key != settings.api_key:
            raise HTTPException(status_code=403, detail="Invalid or missing API Key")
        return cookie_key
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


def _metrics_endpoint(payload_fn, entity_label: str):
    """Run a metrics payload function with standardized error handling."""
    try:
        return _sanitize_metrics(payload_fn())
    except DashboardMetricsNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except DashboardMetricsValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as exc:
        logger.exception("Metrics calculation failed for %s", entity_label)
        raise HTTPException(
            status_code=500,
            detail="An internal error occurred during metrics calculation",
        ) from exc


def _get_portfolio_or_404(db: Session, portfolio_id: int) -> Portfolio:
    portfolio = (
        db.query(Portfolio)
        .options(joinedload(Portfolio.strategies))
        .filter(Portfolio.id == portfolio_id)
        .first()
    )
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


router = APIRouter(prefix="/api", dependencies=[Depends(get_api_key)])


@router.get("/summary", response_model=SummaryResponse)
def get_summary(db: Session = Depends(get_db)):
    return get_summary_payload(db)


@router.get("/real", response_model=RealOverviewResponse)
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


@router.get("/real/daily", response_model=list[DailyProfitRow])
def get_real_daily(
    db: Session = Depends(get_db),
):
    return get_real_daily_payload(db)


@router.get("/real/recent-deals", response_model=list[RecentDeal])
def get_real_recent_deals(
    limit: int = Query(default=20, ge=1, le=250),
    db: Session = Depends(get_db),
):
    return get_real_recent_deals_payload(db, limit=limit)


@router.get("/accounts", response_model=list[AccountResponse])
def list_accounts(db: Session = Depends(get_db)):
    return list_accounts_payload(db)


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
    s.portfolios.clear()
    db.delete(s)
    db.commit()
    invalidate_cache(strategy_id=strategy_id)


@router.get("/strategies/{strategy_id}/metrics", response_model=MetricsResponse)
def get_strategy_metrics(
    strategy_id: str,
    side: Literal["buy", "sell"] | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return _metrics_endpoint(
        lambda: get_strategy_metrics_payload(db, strategy_id, side),
        f"strategy {strategy_id}",
    )


@router.get("/strategies/{strategy_id}/trade-stats")
def get_strategy_trade_stats(
    strategy_id: str,
    side: Literal["buy", "sell"] | None = Query(default=None),
    db: Session = Depends(get_db),
):
    try:
        return get_strategy_trade_stats_payload(db, strategy_id, side)
    except DashboardHistoryNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/strategies/{strategy_id}/daily", response_model=list[DailyProfitRow])
def get_strategy_daily(
    strategy_id: str,
    side: Literal["buy", "sell"] | None = Query(default=None),
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
    side: Literal["buy", "sell"] | None = Query(default=None),
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
    side: Literal["buy", "sell"] | None = Query(default=None),
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


@router.get("/portfolios/{portfolio_id}/deals", response_model=PaginatedDeals)
def get_portfolio_deals(
    portfolio_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    q: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    p = _get_portfolio_or_404(db, portfolio_id)
    strategy_ids = _get_portfolio_strategy_ids(p)
    if not strategy_ids:
        return PaginatedDeals(items=[], total=0, page=page, page_size=page_size)
    return get_portfolio_deals_payload(
        db, strategy_ids, page=page, page_size=page_size, q=q
    )


@router.get("/portfolios/{portfolio_id}/daily", response_model=list[DailyProfitRow])
def get_portfolio_daily(portfolio_id: int, db: Session = Depends(get_db)):
    p = _get_portfolio_or_404(db, portfolio_id)
    strategy_ids = _get_portfolio_strategy_ids(p)
    return get_portfolio_daily_payload(db, strategy_ids)


@router.get("/portfolios/{portfolio_id}/trade-stats")
def get_portfolio_trade_stats(portfolio_id: int, db: Session = Depends(get_db)):
    p = _get_portfolio_or_404(db, portfolio_id)
    strategy_ids = _get_portfolio_strategy_ids(p)
    return get_portfolio_trade_stats_payload(db, strategy_ids)


@router.get(
    "/portfolios/{portfolio_id}/equity", response_model=list[EquityTimestampPoint]
)
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


@router.get(
    "/portfolios/{portfolio_id}/correlation", response_model=CorrelationResponse
)
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


@router.get(
    "/portfolios/{portfolio_id}/correlation/dynamic",
    response_model=DynamicCorrelationResponse,
)
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


@router.get(
    "/portfolios/{portfolio_id}/concurrency", response_model=ConcurrencyResponse
)
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


@router.get("/portfolios/{portfolio_id}/metrics", response_model=MetricsResponse)
def get_portfolio_metrics(portfolio_id: int, db: Session = Depends(get_db)):
    return _metrics_endpoint(
        lambda: get_portfolio_metrics_payload(db, portfolio_id),
        f"portfolio {portfolio_id}",
    )


@router.get(
    "/portfolios/{portfolio_id}/strategy-contributions",
    response_model=ContributionsResponse,
)
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

    dt_from = (
        datetime.fromisoformat(date_from).replace(tzinfo=UTC) if date_from else None
    )
    dt_to = datetime.fromisoformat(date_to).replace(tzinfo=UTC) if date_to else None

    return get_portfolio_contributions_payload(
        db, strategies, date_from=dt_from, date_to=dt_to
    )


@router.get("/advanced-analysis", response_model=AdvancedAnalysisResponse)
def get_advanced_analysis(
    strategy_ids: list[str] = Query(default=[]),
    history_type: str = Query(default="real"),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    initial_balance: float | None = Query(default=None),
    benchmark_id: int | None = Query(default=None),
    side: Literal["buy", "sell"] | None = Query(default=None),
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
    except Exception as exc:
        logger.exception("Unexpected error in advanced analysis")
        raise HTTPException(
            status_code=500,
            detail=f"Analysis failed: {type(exc).__name__}: {exc}",
        ) from exc


@router.get("/correlation", response_model=CorrelationResponse)
def get_standalone_correlation(
    strategy_ids: list[str] = Query(default=[]),
    period: str = Query(default="daily"),
    since: datetime | None = Query(default=None),
):
    if len(strategy_ids) < 2:
        raise HTTPException(status_code=422, detail="Need at least 2 strategies.")
    from trademachine.tradingmonitor_analytics.metrics.calculator import (
        calculate_correlation_matrix,
    )

    return calculate_correlation_matrix(
        strategy_ids, period, since=_ensure_utc(since) if since else None
    )


# ── Backtest endpoints ────────────────────────────────────────────────────────


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
    side: Literal["buy", "sell"] | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return _metrics_endpoint(
        lambda: get_backtest_metrics_payload(db, backtest_id, side),
        f"backtest {backtest_id}",
    )


@router.get(
    "/backtests/{backtest_id}/equity", response_model=list[BacktestEquityPointResponse]
)
def get_backtest_equity_endpoint(
    backtest_id: int,
    side: Literal["buy", "sell"] | None = Query(default=None),
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
    side: Literal["buy", "sell"] | None = Query(default=None),
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
    query = (
        db.query(BacktestDeal)
        .filter(BacktestDeal.backtest_id == backtest_id)
        .order_by(BacktestDeal.timestamp)
    )
    filename = f"backtest_{backtest_id}_{datetime.now(UTC).strftime('%Y%m%d')}.csv"
    return _csv_response(
        _stream_csv(_BACKTEST_DEAL_FIELDS, query, "backtest_id"), filename
    )


@router.get("/backtests/{backtest_id}/daily")
def get_backtest_daily(
    backtest_id: int,
    side: Literal["buy", "sell"] | None = Query(default=None),
    db: Session = Depends(get_db),
):
    try:
        return get_backtest_daily_payload(db, backtest_id, side)
    except DashboardHistoryNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/backtests/{backtest_id}/trade-stats")
def get_backtest_trade_stats(
    backtest_id: int,
    side: Literal["buy", "sell"] | None = Query(default=None),
    db: Session = Depends(get_db),
):
    try:
        return get_backtest_trade_stats_payload(db, backtest_id, side)
    except DashboardHistoryNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


# ── Settings ──────────────────────────────────────────────────────────────────


@router.get("/settings/telegram", response_model=TelegramSettings)
def get_telegram_settings(db: Session = Depends(get_db)):
    return get_telegram_settings_payload(db)


@router.post("/settings/telegram", status_code=204)
def update_telegram_settings(payload: TelegramSettings, db: Session = Depends(get_db)):
    update_telegram_settings_payload(db, payload)


@router.post("/settings/telegram/test")
def test_telegram_settings(db: Session = Depends(get_db)):
    tg_settings = get_telegram_settings_payload(db)
    bot_token = (tg_settings.bot_token or "").strip()
    chat_id = (tg_settings.chat_id or "").strip()

    if not bot_token:
        raise HTTPException(status_code=400, detail="Bot Token não configurado")
    if not chat_id:
        raise HTTPException(status_code=400, detail="Chat ID não configurado")

    import httpx

    try:
        resp = httpx.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": "✅ Teste do TradingMonitor\n\nSe você está lendo esta mensagem, a integração com o Telegram está funcionando!",
            },
            timeout=10,
        )
        if resp.status_code != 200:
            raise HTTPException(
                status_code=502, detail=f"Erro do Telegram: {resp.text}"
            )
        return {"ok": True}
    except HTTPException:
        raise
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Timeout ao enviar mensagem")
    except Exception as exc:
        logger.exception("Unexpected error sending test Telegram message")
        raise HTTPException(
            status_code=500,
            detail="An internal error occurred while communicating with Telegram",
        ) from exc


# ── DataManager Settings ──────────────────────────────────────────────────────


@router.get("/settings/datamanager", response_model=DataManagerSettings)
def get_datamanager_settings(db: Session = Depends(get_db)):
    resolved = load_datamanager_settings(db)
    return DataManagerSettings(
        url=resolved.url,
        api_key=resolved.api_key,
        api_key_configured=resolved.api_key_configured,
        timeout=resolved.timeout,
    )


@router.post("/settings/datamanager", status_code=204)
def update_datamanager_settings(
    payload: DataManagerSettings, db: Session = Depends(get_db)
):
    save_datamanager_settings(db, payload)


@router.post("/settings/datamanager/test")
def test_datamanager_settings(db: Session = Depends(get_db)):
    try:
        return test_datamanager_connection(db)
    except Exception as exc:
        logger.exception("Unexpected error testing DataManager connection")
        raise HTTPException(
            status_code=502,
            detail="An internal error occurred while testing connection",
        ) from exc


# ── Ingestion Errors (Dead Letters) ──────────────────────────────────────────


@router.get("/ingestion-errors", response_model=list[IngestionErrorResponse])
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


@router.get(
    "/portfolios/{portfolio_id}/equity/breakdown",
    response_model=EquityBreakdownResponse,
)
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
        logger.exception("Unexpected error syncing benchmark %s", benchmark_id)
        raise HTTPException(
            status_code=500, detail="An internal error occurred while syncing benchmark"
        ) from exc


@router.delete("/benchmarks/{benchmark_id}", status_code=204)
def delete_benchmark(benchmark_id: int, db: Session = Depends(get_db)):
    try:
        delete_benchmark_record(db, benchmark_id)
    except BenchmarkNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/benchmarks/sync-all")
def sync_all_benchmarks(db: Session = Depends(get_db)):
    try:
        return run_benchmark_auto_sync(db)
    except Exception as exc:
        logger.exception("Unexpected error during sync-all benchmarks")
        raise HTTPException(
            status_code=500,
            detail="An internal error occurred while syncing benchmarks",
        ) from exc


@router.get("/settings/benchmark-scheduler", response_model=BenchmarkSchedulerSettings)
def get_benchmark_scheduler(db: Session = Depends(get_db)):
    return load_benchmark_scheduler_settings(db)


@router.put("/settings/benchmark-scheduler", response_model=BenchmarkSchedulerSettings)
def update_benchmark_scheduler(
    payload: BenchmarkSchedulerSettings, db: Session = Depends(get_db)
):
    save_benchmark_scheduler_settings(db, payload)
    return load_benchmark_scheduler_settings(db)


# ── Health check (item 8) ─────────────────────────────────────────────────────


# ── Symbols ───────────────────────────────────────────────────────────────────


@router.get("/symbols", response_model=list[SymbolResponse])
def list_symbols(db: Session = Depends(get_db)):
    return list_symbols_payload(db)


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


@router.get("/floating-pnl", response_model=FloatingPnlResponse)
def get_floating_pnl(db: Session = Depends(get_db)):
    return get_floating_pnl_payload(db)


@router.get("/health", response_model=HealthResponse)
def health_check(db: Session = Depends(get_db)):
    db_ok = False
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        logger.warning("Database health check failed", exc_info=True)

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
        logger.warning(
            "Failed to parse ingestion heartbeat_ts: %s", heartbeat_ts, exc_info=True
        )
        return None


# ── Ingestion status (item 7) ─────────────────────────────────────────────────


@router.get("/ingestion/status", response_model=IngestionStatusResponse)
def ingestion_status():
    from trademachine.tradingmonitor_ingestion.public import (
        get_ingestion_status,
    )

    return get_ingestion_status()


# ── CSV export (item 13) ──────────────────────────────────────────────────────


def _stream_csv(fields: list[str], query, id_field: str) -> Generator:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(fields)
    yield output.getvalue()
    output.truncate(0)
    output.seek(0)

    for d in query.yield_per(1000):
        writer.writerow(
            [
                to_iso(d.timestamp) or "",
                d.ticket,
                getattr(d, id_field),
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


def _csv_response(generator: Generator, filename: str) -> StreamingResponse:
    return StreamingResponse(
        generator,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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

_BACKTEST_DEAL_FIELDS = [
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


@router.get("/strategies/{strategy_id}/deals/export")
def export_strategy_deals(strategy_id: str, db: Session = Depends(get_db)):
    strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    query = (
        db.query(Deal).filter(Deal.strategy_id == strategy_id).order_by(Deal.timestamp)
    )
    filename = f"deals_{strategy_id}_{datetime.now(UTC).strftime('%Y%m%d')}.csv"
    return _csv_response(_stream_csv(_DEAL_FIELDS, query, "strategy_id"), filename)


@router.get("/portfolios/{portfolio_id}/deals/export")
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
    return _csv_response(_stream_csv(_DEAL_FIELDS, query, "strategy_id"), filename)


# ── MT5 Backtest HTML Upload ───────────────────────────────────────────────────


@router.post("/backtests/upload-html")
async def upload_backtest_html(
    files: list[UploadFile] = File(...),
    magic_number_override: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    """Upload one or more MT5 HTML backtest reports."""
    from trademachine.trading_monitor_dashboard.backtest_import_service import (
        process_html_upload,
    )

    parser = MT5ReportParser()
    results = []
    for upload_file in files:
        result = await process_html_upload(
            upload_file, magic_number_override, db, parser
        )
        results.append(result)
    return results
