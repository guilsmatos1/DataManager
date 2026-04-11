from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import DateTime, Integer, Numeric, String, func, inspect, select, table
from sqlalchemy.orm import Session
from sqlalchemy.sql import column
from trademachine.tradingmonitor_storage.db.models import Deal, DealType

strategy_pnl_daily = table(
    "strategy_pnl_daily",
    column("bucket", DateTime(timezone=True)),
    column("strategy_id", String()),
    column("net_profit", Numeric(18, 8)),
    column("trades_count", Integer()),
)

strategy_pnl_hourly = table(
    "strategy_pnl_hourly",
    column("bucket", DateTime(timezone=True)),
    column("strategy_id", String()),
    column("net_profit", Numeric(18, 8)),
    column("trades_count", Integer()),
)


def _list_relation_names(db: Session) -> set[str]:
    bind = db.get_bind()
    inspector = inspect(bind)
    relation_names = set(inspector.get_table_names())
    relation_names.update(inspector.get_view_names())

    get_materialized_view_names = getattr(
        inspector, "get_materialized_view_names", None
    )
    if callable(get_materialized_view_names):
        try:
            relation_names.update(get_materialized_view_names())
        except NotImplementedError:
            pass

    return relation_names


def _has_relation(db: Session, relation_name: str) -> bool:
    return relation_name in _list_relation_names(db)


def get_strategy_net_profit_map(
    db: Session, strategy_ids: Sequence[str] | None = None
) -> dict[str, float]:
    if _has_relation(db, "strategy_pnl_daily"):
        query = select(
            strategy_pnl_daily.c.strategy_id,
            func.sum(strategy_pnl_daily.c.net_profit).label("net_profit"),
        )
        if strategy_ids:
            query = query.where(
                strategy_pnl_daily.c.strategy_id.in_(list(strategy_ids))
            )
        rows = db.execute(query.group_by(strategy_pnl_daily.c.strategy_id)).all()
        return {str(row.strategy_id): float(row.net_profit or 0.0) for row in rows}

    query = db.query(
        Deal.strategy_id,
        func.sum(Deal.profit + Deal.commission + Deal.swap).label("net_profit"),
    ).filter(Deal.type.in_([DealType.BUY, DealType.SELL]))
    if strategy_ids:
        query = query.filter(Deal.strategy_id.in_(list(strategy_ids)))
    rows = query.group_by(Deal.strategy_id).all()
    return {str(row.strategy_id): float(row.net_profit or 0.0) for row in rows}


def get_strategy_trade_count_map(
    db: Session, strategy_ids: Sequence[str] | None = None
) -> dict[str, int]:
    if _has_relation(db, "strategy_pnl_daily"):
        query = select(
            strategy_pnl_daily.c.strategy_id,
            func.sum(strategy_pnl_daily.c.trades_count).label("trades_count"),
        )
        if strategy_ids:
            query = query.where(
                strategy_pnl_daily.c.strategy_id.in_(list(strategy_ids))
            )
        rows = db.execute(query.group_by(strategy_pnl_daily.c.strategy_id)).all()
        return {str(row.strategy_id): int(row.trades_count or 0) for row in rows}

    query = db.query(
        Deal.strategy_id,
        func.count(Deal.ticket).label("trades_count"),
    ).filter(Deal.type.in_([DealType.BUY, DealType.SELL]))
    if strategy_ids:
        query = query.filter(Deal.strategy_id.in_(list(strategy_ids)))
    rows = query.group_by(Deal.strategy_id).all()
    return {str(row.strategy_id): int(row.trades_count or 0) for row in rows}


def get_strategy_daily_profit_rows(
    db: Session, strategy_ids: Sequence[str] | None = None
) -> list[dict[str, object]]:
    if _has_relation(db, "strategy_pnl_daily"):
        query = select(
            func.date(strategy_pnl_daily.c.bucket).label("date"),
            func.sum(strategy_pnl_daily.c.net_profit).label("net_profit"),
        )
        if strategy_ids:
            query = query.where(
                strategy_pnl_daily.c.strategy_id.in_(list(strategy_ids))
            )
        rows = db.execute(
            query.group_by(func.date(strategy_pnl_daily.c.bucket)).order_by(
                func.date(strategy_pnl_daily.c.bucket)
            )
        ).all()
        return [
            {"date": str(row.date), "net_profit": float(row.net_profit or 0.0)}
            for row in rows
        ]

    date_expr = func.date(Deal.timestamp)
    query = db.query(
        date_expr.label("date"),
        func.sum(Deal.profit + Deal.commission + Deal.swap).label("net_profit"),
    ).filter(Deal.type.in_([DealType.BUY, DealType.SELL]))
    if strategy_ids:
        query = query.filter(Deal.strategy_id.in_(list(strategy_ids)))
    rows = query.group_by(date_expr).order_by(date_expr).all()
    return [
        {"date": str(row.date), "net_profit": float(row.net_profit or 0.0)}
        for row in rows
    ]


def get_strategy_intraday_profit_map(
    db: Session,
    *,
    strategy_ids: Sequence[str],
    day_start_utc: datetime,
    now_utc: datetime,
) -> dict[str, float]:
    if not strategy_ids:
        return {}

    if _has_relation(db, "strategy_pnl_hourly"):
        rows = db.execute(
            select(
                strategy_pnl_hourly.c.strategy_id,
                func.sum(strategy_pnl_hourly.c.net_profit).label("net_profit"),
            )
            .where(strategy_pnl_hourly.c.strategy_id.in_(list(strategy_ids)))
            .where(strategy_pnl_hourly.c.bucket >= day_start_utc)
            .where(strategy_pnl_hourly.c.bucket <= now_utc)
            .group_by(strategy_pnl_hourly.c.strategy_id)
        ).all()
        return {str(row.strategy_id): float(row.net_profit or 0.0) for row in rows}

    rows = (
        db.query(
            Deal.strategy_id,
            func.sum(Deal.profit + Deal.commission + Deal.swap).label("net_profit"),
        )
        .filter(
            Deal.strategy_id.in_(list(strategy_ids)),
            Deal.type.in_([DealType.BUY, DealType.SELL]),
            Deal.timestamp >= day_start_utc,
            Deal.timestamp <= now_utc,
        )
        .group_by(Deal.strategy_id)
        .all()
    )
    return {str(row.strategy_id): float(row.net_profit or 0.0) for row in rows}
