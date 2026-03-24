import csv
import hashlib
import io
import logging
import math
from datetime import UTC, datetime

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
from pydantic import BaseModel
from sqlalchemy import cast, extract, func, or_, text
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.types import Date, String
from trademachine.mt5.parser import (
    _EN_TO_PT_COLUMNS,
    MT5ReportParser,
)
from trademachine.trading_monitor_dashboard.serializers import (
    AccountResponse,
    BacktestDealResponse,
    BacktestEquityPointResponse,
    BacktestResponse,
    DealResponse,
    EquityPointResponse,
    PaginatedBacktestDeals,
    PaginatedDeals,
    PortfolioResponse,
    StrategyResponse,
    SummaryResponse,
    SymbolResponse,
)
from trademachine.tradingmonitor.config import settings
from trademachine.tradingmonitor.db.database import get_db
from trademachine.tradingmonitor.db.models import (
    Account,
    Backtest,
    BacktestDeal,
    BacktestEquity,
    Deal,
    DealType,
    EquityCurve,
    Portfolio,
    Setting,
    Strategy,
    Symbol,
)
from trademachine.tradingmonitor.ingestion.tcp_server import invalidate_cache

logger = logging.getLogger(__name__)

# ── Authentication ────────────────────────────────────────────────────────────

API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=True)


def get_api_key(api_key: str = Security(api_key_header)):
    if api_key != settings.api_key:
        raise HTTPException(status_code=403, detail="Invalid or missing API Key")
    return api_key


def _sanitize_metrics(metrics: dict) -> dict:
    """Replace NaN/Inf float values with None so JSON serialization doesn't fail."""
    result = {}
    for k, v in metrics.items():
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            result[k] = None
        else:
            result[k] = v
    return result


class AccountUpdate(BaseModel):
    name: str | None = None
    account_type: str | None = None
    currency: str | None = None


class StrategyUpdate(BaseModel):
    name: str | None = None
    symbol: str | None = None
    timeframe: str | None = None
    operational_style: str | None = None
    trade_duration: str | None = None
    description: str | None = None
    live: bool | None = None
    real_account: bool | None = None


class PortfolioCreate(BaseModel):
    name: str
    description: str | None = None
    live: bool = False
    real_account: bool = False
    strategy_ids: list[str] = []
    initial_balance: float | None = None


class PortfolioUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    live: bool | None = None
    real_account: bool | None = None
    strategy_ids: list[str] | None = None
    initial_balance: float | None = None


class SymbolCreate(BaseModel):
    name: str
    market: str | None = None
    lot: float | None = None


class SymbolUpdate(BaseModel):
    name: str | None = None
    market: str | None = None
    lot: float | None = None


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


@router.get("/real")
def get_real_overview(db: Session = Depends(get_db)):
    """Aggregated view of all real-account strategies: metrics, equity curve, floating P&L."""
    real_strategies = (
        db.query(Strategy).filter(Strategy.real_account.is_(True)).all()  # noqa: E712
    )
    if not real_strategies:
        return {"strategies": [], "totals": {"net_profit": 0.0, "floating_pnl": 0.0}}

    sids = [s.id for s in real_strategies]

    # Net profit per strategy (BUY/SELL only)
    np_map: dict[str, float] = dict(
        db.query(Deal.strategy_id, func.sum(Deal.profit + Deal.commission + Deal.swap))
        .filter(
            Deal.strategy_id.in_(sids), Deal.type.in_([DealType.BUY, DealType.SELL])
        )
        .group_by(Deal.strategy_id)
        .all()
    )

    # Latest equity point per strategy
    subq = (
        db.query(
            EquityCurve.strategy_id,
            func.max(EquityCurve.timestamp).label("latest_ts"),
        )
        .filter(EquityCurve.strategy_id.in_(sids))
        .group_by(EquityCurve.strategy_id)
        .subquery()
    )
    latest_eq_rows = (
        db.query(EquityCurve)
        .join(
            subq,
            (EquityCurve.strategy_id == subq.c.strategy_id)
            & (EquityCurve.timestamp == subq.c.latest_ts),
        )
        .all()
    )
    latest_eq_map: dict[str, EquityCurve] = {r.strategy_id: r for r in latest_eq_rows}

    # Equity curves for the chart (all points, balance+equity per strategy)
    equity_rows = (
        db.query(EquityCurve)
        .filter(EquityCurve.strategy_id.in_(sids))
        .order_by(EquityCurve.timestamp)
        .all()
    )
    equity_by_sid: dict[str, list] = {sid: [] for sid in sids}
    for row in equity_rows:
        equity_by_sid[row.strategy_id].append(
            {
                "ts": row.timestamp.isoformat(),
                "balance": float(row.balance),
                "equity": float(row.equity),
            }
        )

    result = []
    total_np = 0.0
    total_floating = 0.0

    for s in real_strategies:
        np_val = float(np_map.get(s.id) or 0)
        eq = latest_eq_map.get(s.id)
        balance = float(eq.balance) if eq else None
        equity = float(eq.equity) if eq else None
        floating = (
            (equity - balance) if (equity is not None and balance is not None) else 0.0
        )

        # Max drawdown from equity series
        equity_series = [p["equity"] for p in equity_by_sid[s.id]]
        max_dd = _compute_max_drawdown(equity_series)

        ret_dd = None
        ib = float(s.initial_balance) if s.initial_balance else None
        if max_dd and max_dd > 0 and ib and ib > 0:
            ret_dd = round(np_val / (max_dd * ib), 3)

        result.append(
            {
                "id": s.id,
                "name": s.name,
                "symbol": s.symbol,
                "net_profit": round(np_val, 2),
                "max_drawdown_pct": round(max_dd * 100, 2)
                if max_dd is not None
                else None,
                "ret_dd": ret_dd,
                "floating_pnl": round(floating, 2),
                "balance": round(balance, 2) if balance is not None else None,
                "equity": round(equity, 2) if equity is not None else None,
                "initial_balance": ib,
                "equity_curve": equity_by_sid[s.id],
            }
        )
        total_np += np_val
        total_floating += floating

    return {
        "strategies": result,
        "totals": {
            "net_profit": round(total_np, 2),
            "floating_pnl": round(total_floating, 2),
        },
    }


@router.get("/accounts", response_model=list[AccountResponse])
def list_accounts(db: Session = Depends(get_db)):
    accounts = db.query(Account).all()
    net_profits = dict(
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
def list_strategies(db: Session = Depends(get_db)):
    net_profits = dict(
        db.query(Deal.strategy_id, func.sum(Deal.profit + Deal.commission + Deal.swap))
        .filter(Deal.type.in_([DealType.BUY, DealType.SELL]))
        .group_by(Deal.strategy_id)
        .all()
    )
    bt_net_profits = dict(
        db.query(
            Backtest.strategy_id,
            func.sum(BacktestDeal.profit + BacktestDeal.commission + BacktestDeal.swap),
        )
        .join(BacktestDeal, BacktestDeal.backtest_id == Backtest.id)
        .filter(BacktestDeal.type.in_([DealType.BUY, DealType.SELL]))
        .group_by(Backtest.strategy_id)
        .all()
    )
    trades_counts = dict(
        db.query(Deal.strategy_id, func.count(Deal.ticket))
        .filter(Deal.type.in_([DealType.BUY, DealType.SELL]))
        .group_by(Deal.strategy_id)
        .all()
    )
    # Fetch equity data for max drawdown computation
    equity_rows = (
        db.query(EquityCurve.strategy_id, EquityCurve.equity)
        .order_by(EquityCurve.strategy_id, EquityCurve.timestamp)
        .all()
    )
    from collections import defaultdict

    equity_by_strat: dict = defaultdict(list)
    for row in equity_rows:
        equity_by_strat[row.strategy_id].append(float(row.equity))

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
def get_strategy_metrics(strategy_id: str, db: Session = Depends(get_db)):
    strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    from trademachine.tradingmonitor.metrics.calculator import calculate_metrics

    try:
        return _sanitize_metrics(calculate_metrics(strategy_id))
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

    dt_from = (
        datetime.fromisoformat(date_from).replace(tzinfo=UTC) if date_from else None
    )
    dt_to = datetime.fromisoformat(date_to).replace(tzinfo=UTC) if date_to else None

    deals_df = get_strategy_deals(strategy_id, since=dt_from)
    if not deals_df.empty and dt_to is not None:
        deals_df = deals_df[deals_df.index <= dt_to]

    equity_df = get_strategy_equity_curve(strategy_id)
    if not equity_df.empty:
        if dt_from is not None:
            equity_df = equity_df[equity_df.index >= dt_from]
        if dt_to is not None:
            equity_df = equity_df[equity_df.index <= dt_to]

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
        return {"error": str(e)}


@router.get("/strategies/{strategy_id}/trade-stats")
def get_strategy_trade_stats(strategy_id: str, db: Session = Depends(get_db)):
    strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    def _q(group_expr):
        return (
            db.query(
                group_expr.label("key"),
                func.count().label("count"),
                func.sum(Deal.profit + Deal.commission + Deal.swap).label("net_profit"),
            )
            .filter(Deal.strategy_id == strategy_id)
            .filter(Deal.type.in_([DealType.BUY, DealType.SELL]))
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
def get_strategy_daily(strategy_id: str, db: Session = Depends(get_db)):
    strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    rows = (
        db.query(
            cast(Deal.timestamp, Date).label("date"),
            func.sum(Deal.profit + Deal.commission + Deal.swap).label("net_profit"),
        )
        .filter(Deal.strategy_id == strategy_id)
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
    db: Session = Depends(get_db),
):
    strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    base = db.query(Deal).filter(Deal.strategy_id == strategy_id)
    if q:
        term = f"%{q}%"
        conditions = [
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
def list_portfolios(db: Session = Depends(get_db)):
    portfolios = db.query(Portfolio).options(joinedload(Portfolio.strategies)).all()

    # Collect all strategy IDs across portfolios for bulk equity fetch
    all_strat_ids: list[str] = list({s.id for p in portfolios for s in p.strategies})
    equity_rows = (
        db.query(EquityCurve.strategy_id, EquityCurve.timestamp, EquityCurve.equity)
        .filter(EquityCurve.strategy_id.in_(all_strat_ids))
        .order_by(EquityCurve.strategy_id, EquityCurve.timestamp)
        .all()
        if all_strat_ids
        else []
    )
    from collections import defaultdict

    equity_by_strat: dict = defaultdict(list)
    for row in equity_rows:
        equity_by_strat[row.strategy_id].append((row.timestamp, float(row.equity)))

    result = []
    for p in portfolios:
        strategy_ids = [s.id for s in p.strategies]
        r = PortfolioResponse.from_orm_portfolio(p)

        if strategy_ids:
            np_val = (
                db.query(func.sum(Deal.profit + Deal.commission + Deal.swap))
                .filter(
                    Deal.strategy_id.in_(strategy_ids),
                    Deal.type.in_([DealType.BUY, DealType.SELL]),
                )
                .scalar()
            )
            r.net_profit = float(np_val) if np_val is not None else None

            # Portfolio max drawdown from combined equity curve
            import pandas as pd

            frames = []
            for sid in strategy_ids:
                pts = equity_by_strat.get(sid, [])
                if pts:
                    frames.append(
                        pd.Series({ts: eq for ts, eq in pts}, name=sid, dtype=float)
                    )
            if frames:
                combined = pd.concat(frames, axis=1).sort_index().ffill().sum(axis=1)
                peak = combined.cummax()
                dd_series = (peak - combined) / peak.replace(0, float("nan"))
                r.max_drawdown = (
                    float(dd_series.max()) if not dd_series.isna().all() else None
                )

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


@router.get("/portfolios/{portfolio_id}/daily")
def get_portfolio_daily(portfolio_id: int, db: Session = Depends(get_db)):
    p = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    strategy_ids = [s.id for s in p.strategies]
    if not strategy_ids:
        return []
    rows = (
        db.query(
            cast(Deal.timestamp, Date).label("date"),
            func.sum(Deal.profit + Deal.commission + Deal.swap).label("net_profit"),
        )
        .filter(Deal.strategy_id.in_(strategy_ids))
        .group_by(cast(Deal.timestamp, Date))
        .order_by(cast(Deal.timestamp, Date))
        .all()
    )
    return [{"date": str(r.date), "net_profit": float(r.net_profit)} for r in rows]


@router.get("/portfolios/{portfolio_id}/equity")
def get_portfolio_equity(portfolio_id: int, db: Session = Depends(get_db)):
    p = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    strategy_ids = [s.id for s in p.strategies]
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
    return [
        {"timestamp": ts.isoformat(), "equity": float(v)} for ts, v in combined.items()
    ]


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
    p = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    strategy_ids = [s.id for s in p.strategies]
    if len(strategy_ids) < 2:
        return {"error": "Need at least 2 strategies in this portfolio."}
    from trademachine.tradingmonitor.metrics.calculator import (
        calculate_correlation_matrix,
    )

    return calculate_correlation_matrix(strategy_ids, period, since=_ensure_utc(since))


@router.get("/portfolios/{portfolio_id}/concurrency")
def get_portfolio_concurrency(
    portfolio_id: int,
    since: datetime | None = None,
    db: Session = Depends(get_db),
):
    p = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    strategy_ids = [s.id for s in p.strategies]
    if len(strategy_ids) < 2:
        return {"error": "Need at least 2 strategies in this portfolio."}
    from trademachine.tradingmonitor.metrics.calculator import calculate_concurrency

    return calculate_concurrency(strategy_ids, since=_ensure_utc(since))


@router.get("/portfolios/{portfolio_id}/metrics")
def get_portfolio_metrics(portfolio_id: int, db: Session = Depends(get_db)):
    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    strategy_ids = [s.id for s in portfolio.strategies]
    if not strategy_ids:
        return {"error": "No strategies in this portfolio"}
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
    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    strategy_ids = [s.id for s in portfolio.strategies]
    if not strategy_ids:
        return {"error": "No strategies in this portfolio"}

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
        return {"error": str(e)}


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
    net_profit_map: dict[int, object] = dict(
        db.query(
            BacktestDeal.backtest_id,
            func.sum(BacktestDeal.profit + BacktestDeal.commission + BacktestDeal.swap),
        )
        .filter(
            BacktestDeal.backtest_id.in_(bt_ids),
            BacktestDeal.type.in_([DealType.BUY, DealType.SELL]),
        )
        .group_by(BacktestDeal.backtest_id)
        .all()
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
def get_backtest_metrics(backtest_id: int, db: Session = Depends(get_db)):
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
    db: Session = Depends(get_db),
):
    bt = db.query(Backtest).filter(Backtest.id == backtest_id).first()
    if not bt:
        raise HTTPException(status_code=404, detail="Backtest not found")
    total = (
        db.query(BacktestDeal).filter(BacktestDeal.backtest_id == backtest_id).count()
    )
    deals = (
        db.query(BacktestDeal)
        .filter(BacktestDeal.backtest_id == backtest_id)
        .order_by(BacktestDeal.timestamp.desc())
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
                    d.timestamp.isoformat() if d.timestamp else "",
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
def get_backtest_daily(backtest_id: int, db: Session = Depends(get_db)):
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
        .filter(BacktestDeal.type.in_([DealType.BUY, DealType.SELL]))
        .group_by(cast(BacktestDeal.timestamp, Date))
        .order_by(cast(BacktestDeal.timestamp, Date))
        .all()
    )
    return [{"date": str(r.date), "net_profit": float(r.net_profit)} for r in rows]


@router.get("/backtests/{backtest_id}/trade-stats")
def get_backtest_trade_stats(backtest_id: int, db: Session = Depends(get_db)):
    bt = db.query(Backtest).filter(Backtest.id == backtest_id).first()
    if not bt:
        raise HTTPException(status_code=404, detail="Backtest not found")

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
            .filter(BacktestDeal.type.in_([DealType.BUY, DealType.SELL]))
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


class TelegramSettings(BaseModel):
    bot_token: str | None = None
    chat_id: str | None = None


# ── Settings ──────────────────────────────────────────────────────────────────


@router.get("/settings/telegram", response_model=TelegramSettings)
def get_telegram_settings(db: Session = Depends(get_db)):
    bot_token = db.query(Setting).filter(Setting.key == "telegram_bot_token").first()
    chat_id = db.query(Setting).filter(Setting.key == "telegram_chat_id").first()
    return TelegramSettings(
        bot_token=bot_token.value if bot_token else None,
        chat_id=chat_id.value if chat_id else None,
    )


@router.post("/settings/telegram", status_code=204)
def update_telegram_settings(payload: TelegramSettings, db: Session = Depends(get_db)):
    def _set(key, val):
        s = db.query(Setting).filter(Setting.key == key).first()
        if not s:
            s = Setting(key=key, value=val)
            db.add(s)
        else:
            s.value = val

    _set("telegram_bot_token", payload.bot_token)
    _set("telegram_chat_id", payload.chat_id)
    db.commit()


# ── Health check (item 8) ─────────────────────────────────────────────────────


# ── Symbols ───────────────────────────────────────────────────────────────────


@router.get("/symbols", response_model=list[SymbolResponse])
def list_symbols(db: Session = Depends(get_db)):
    return db.query(Symbol).order_by(Symbol.market, Symbol.name).all()


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
                d.timestamp.isoformat() if d.timestamp else "",
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
    p = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    strategy_ids = [s.id for s in p.strategies]
    if not strategy_ids:
        raise HTTPException(status_code=404, detail="No strategies in portfolio")
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

            # Always sync strategy name and timeframe from report
            report_name = metadata.get("Expert_Advisor")
            if report_name:
                strategy.name = report_name
            if not strategy.timeframe:
                report_tf = metadata.get("Timeframe")
                if report_tf:
                    strategy.timeframe = report_tf
            db.flush()  # push strategy changes into the transaction

            # Deterministic run ID based on file content
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
                db.commit()  # persist strategy name/timeframe even for skipped backtests
                result["status"] = "skipped"
                result["backtest_id"] = existing.id
                result["error"] = "Relatório já importado anteriormente"
                results.append(result)
                continue

            # Extract deals table (PT then EN fallback)
            deals_df = parser.extract_table_by_header(soup, "Transações")
            if deals_df.empty:
                deals_df = parser.extract_table_by_header(soup, "Deals")
                if not deals_df.empty:
                    deals_df = deals_df.rename(columns=_EN_TO_PT_COLUMNS)
            if deals_df.empty:
                raise ValueError("Tabela de transações não encontrada no relatório")

            deals_df = parser._clean_deals_df(deals_df)

            # Locate column names (differ between PT/EN MT5 versions)
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

            # Extract initial balance from first BALANCE row
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
                        backtest_id=backtest.id,
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
                # Equity point: use balance column value
                if col_balance:
                    db.add(
                        BacktestEquity(
                            backtest_id=backtest.id,
                            timestamp=ts,
                            balance=balance,
                            equity=balance,
                        )
                    )
                deals_imported += 1

            db.commit()
            result["backtest_id"] = backtest.id
            result["deals_imported"] = deals_imported

        except Exception as exc:
            db.rollback()
            logger.exception("Erro ao processar upload: %s", upload_file.filename)
            result["status"] = "error"
            result["error"] = str(exc)

        results.append(result)

    return results
