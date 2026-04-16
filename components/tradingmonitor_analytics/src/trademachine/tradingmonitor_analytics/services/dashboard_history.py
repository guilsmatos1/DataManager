from __future__ import annotations

from sqlalchemy import Integer, case, cast, extract, func
from sqlalchemy.orm import Session
from sqlalchemy.types import Date
from trademachine.tradingmonitor_storage.api_schemas import (
    BacktestDealResponse,
    DealResponse,
    PaginatedBacktestDeals,
    PaginatedDeals,
)
from trademachine.tradingmonitor_storage.public import (
    Backtest,
    BacktestDeal,
    Deal,
    DealType,
    Strategy,
    apply_deal_search_filter,
    get_strategy_daily_profit_rows,
)


class DashboardHistoryNotFoundError(LookupError):
    """Raised when a requested strategy or backtest history resource is missing."""


def _side_types_for_pnl(side: str | None) -> list[DealType]:
    if side == "buy":
        return [DealType.BUY]
    if side == "sell":
        return [DealType.SELL]
    return [DealType.BUY, DealType.SELL]


def _side_types_for_table(side: str | None) -> list[DealType]:
    """Return deal types matching the execution direction for table filtering."""
    if side == "buy":
        return [DealType.BUY]
    if side == "sell":
        return [DealType.SELL]
    return [DealType.BUY, DealType.SELL]


def _ensure_strategy_exists(db: Session, strategy_id: str) -> None:
    strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if strategy is None:
        raise DashboardHistoryNotFoundError("Strategy not found")


def _ensure_backtest_exists(db: Session, backtest_id: int) -> None:
    backtest = db.query(Backtest).filter(Backtest.id == backtest_id).first()
    if backtest is None:
        raise DashboardHistoryNotFoundError("Backtest not found")


def _empty_trade_stats() -> dict[str, list[dict[str, int | float | str]]]:
    dow_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return {
        "by_hour": [
            {"hour": hour, "count": 0, "net_profit": 0.0} for hour in range(24)
        ],
        "by_dow": [
            {
                "dow": index + 1,
                "label": dow_labels[index],
                "count": 0,
                "net_profit": 0.0,
            }
            for index in range(7)
        ],
    }


def _iso_weekday_expr(db: Session, column):
    dialect_name = db.bind.dialect.name if db.bind is not None else ""
    if dialect_name == "sqlite":
        weekday = cast(func.strftime("%w", column), Integer)
        return case((weekday == 0, 7), else_=weekday)
    return extract("isodow", column)


def get_strategy_trade_stats_payload(
    db: Session,
    strategy_id: str,
    side: str | None = None,
) -> dict[str, list[dict[str, int | float | str]]]:
    _ensure_strategy_exists(db, strategy_id)
    payload = _empty_trade_stats()
    types = _side_types_for_pnl(side)

    def _query(group_expr):
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

    for row in _query(extract("hour", Deal.timestamp)):
        hour = int(row.key)
        payload["by_hour"][hour] = {
            "hour": hour,
            "count": int(row.count),
            "net_profit": round(float(row.net_profit or 0), 2),
        }

    for row in _query(_iso_weekday_expr(db, Deal.timestamp)):
        day = int(row.key) - 1
        payload["by_dow"][day] = {
            "dow": day + 1,
            "label": payload["by_dow"][day]["label"],
            "count": int(row.count),
            "net_profit": round(float(row.net_profit or 0), 2),
        }

    return payload


def get_strategy_daily_payload(
    db: Session,
    strategy_id: str,
    side: str | None = None,
) -> list[dict[str, object]]:
    _ensure_strategy_exists(db, strategy_id)
    if side is None:
        return get_strategy_daily_profit_rows(db, [strategy_id])

    rows = (
        db.query(
            func.date(Deal.timestamp).label("date"),
            func.sum(Deal.profit + Deal.commission + Deal.swap).label("net_profit"),
        )
        .filter(Deal.strategy_id == strategy_id)
        .filter(Deal.type.in_(_side_types_for_pnl(side)))
        .group_by(func.date(Deal.timestamp))
        .order_by(func.date(Deal.timestamp))
        .all()
    )
    return [
        {"date": str(row.date), "net_profit": float(row.net_profit)} for row in rows
    ]


def get_strategy_deals_payload(
    db: Session,
    strategy_id: str,
    *,
    page: int,
    page_size: int,
    q: str | None = None,
    side: str | None = None,
) -> PaginatedDeals:
    _ensure_strategy_exists(db, strategy_id)

    base = db.query(Deal).filter(Deal.strategy_id == strategy_id)
    if side in {"buy", "sell"}:
        base = base.filter(Deal.type.in_(_side_types_for_table(side)))
    base = apply_deal_search_filter(base, q)

    total = base.count()
    deals = (
        base.order_by(Deal.timestamp.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PaginatedDeals(
        items=[DealResponse.from_orm_deal(deal) for deal in deals],
        total=total,
        page=page,
        page_size=page_size,
    )


def get_portfolio_deals_payload(
    db: Session,
    strategy_ids: list[str],
    *,
    page: int,
    page_size: int,
    q: str | None = None,
) -> PaginatedDeals:
    base = db.query(Deal).filter(Deal.strategy_id.in_(strategy_ids))
    base = apply_deal_search_filter(base, q, include_strategy_id=True)

    total = base.count()
    deals = (
        base.order_by(Deal.timestamp.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PaginatedDeals(
        items=[DealResponse.from_orm_deal(deal) for deal in deals],
        total=total,
        page=page,
        page_size=page_size,
    )


def get_backtest_trade_stats_payload(
    db: Session,
    backtest_id: int,
    side: str | None = None,
) -> dict[str, list[dict[str, int | float | str]]]:
    _ensure_backtest_exists(db, backtest_id)
    payload = _empty_trade_stats()
    types = _side_types_for_pnl(side)

    def _query(group_expr):
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

    for row in _query(extract("hour", BacktestDeal.timestamp)):
        hour = int(row.key)
        payload["by_hour"][hour] = {
            "hour": hour,
            "count": int(row.count),
            "net_profit": round(float(row.net_profit or 0), 2),
        }

    for row in _query(_iso_weekday_expr(db, BacktestDeal.timestamp)):
        day = int(row.key) - 1
        payload["by_dow"][day] = {
            "dow": day + 1,
            "label": payload["by_dow"][day]["label"],
            "count": int(row.count),
            "net_profit": round(float(row.net_profit or 0), 2),
        }

    return payload


def get_backtest_daily_payload(
    db: Session,
    backtest_id: int,
    side: str | None = None,
) -> list[dict[str, object]]:
    _ensure_backtest_exists(db, backtest_id)
    rows = (
        db.query(
            func.date(BacktestDeal.timestamp).label("date"),
            func.sum(
                BacktestDeal.profit + BacktestDeal.commission + BacktestDeal.swap
            ).label("net_profit"),
        )
        .filter(BacktestDeal.backtest_id == backtest_id)
        .filter(BacktestDeal.type.in_(_side_types_for_pnl(side)))
        .group_by(func.date(BacktestDeal.timestamp))
        .order_by(func.date(BacktestDeal.timestamp))
        .all()
    )
    return [
        {"date": str(row.date), "net_profit": float(row.net_profit)} for row in rows
    ]


def get_backtest_deals_payload(
    db: Session,
    backtest_id: int,
    *,
    page: int,
    page_size: int,
    side: str | None = None,
) -> PaginatedBacktestDeals:
    _ensure_backtest_exists(db, backtest_id)

    base = db.query(BacktestDeal).filter(BacktestDeal.backtest_id == backtest_id)
    if side in {"buy", "sell"}:
        base = base.filter(BacktestDeal.type.in_(_side_types_for_table(side)))

    total = base.count()
    deals = (
        base.order_by(BacktestDeal.timestamp.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PaginatedBacktestDeals(
        items=[BacktestDealResponse.from_orm(deal) for deal in deals],
        total=total,
        page=page,
        page_size=page_size,
    )


def get_portfolio_daily_payload(
    db: Session,
    strategy_ids: list[str],
) -> list[dict[str, object]]:
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


def get_portfolio_trade_stats_payload(
    db: Session,
    strategy_ids: list[str],
) -> dict[str, list[dict[str, int | float | str]]]:
    if not strategy_ids:
        return _empty_trade_stats()
    payload = _empty_trade_stats()
    types = [DealType.BUY, DealType.SELL]

    def _query(group_expr):
        return (
            db.query(
                group_expr.label("key"),
                func.count().label("count"),
                func.sum(Deal.profit + Deal.commission + Deal.swap).label("net_profit"),
            )
            .filter(Deal.strategy_id.in_(strategy_ids))
            .filter(Deal.type.in_(types))
            .group_by(group_expr)
            .order_by(group_expr)
            .all()
        )

    for row in _query(extract("hour", Deal.timestamp)):
        hour = int(row.key)
        payload["by_hour"][hour] = {
            "hour": hour,
            "count": int(row.count),
            "net_profit": round(float(row.net_profit or 0), 2),
        }

    for row in _query(_iso_weekday_expr(db, Deal.timestamp)):
        day = int(row.key) - 1
        payload["by_dow"][day] = {
            "dow": day + 1,
            "label": payload["by_dow"][day]["label"],
            "count": int(row.count),
            "net_profit": round(float(row.net_profit or 0), 2),
        }

    return payload
