from __future__ import annotations

from sqlalchemy import String, cast, or_
from sqlalchemy.orm import Query
from trademachine.tradingmonitor_storage.db.models import Deal, DealType


def _parse_deal_type_search(search_text: str) -> DealType | None:
    try:
        return DealType(search_text.upper())
    except ValueError:
        return None


def apply_deal_search_filter(
    query: Query,
    search_text: str | None,
    *,
    include_strategy_id: bool = False,
) -> Query:
    """Apply TradingMonitor deal search rules to a SQLAlchemy query."""
    if not search_text:
        return query

    term = f"%{search_text}%"
    conditions = [
        Deal.symbol.ilike(term),
        cast(Deal.ticket, String).ilike(term),
    ]
    if include_strategy_id:
        conditions.append(Deal.strategy_id.ilike(term))

    deal_type = _parse_deal_type_search(search_text)
    if deal_type is not None:
        conditions.append(Deal.type == deal_type)

    return query.filter(or_(*conditions))
