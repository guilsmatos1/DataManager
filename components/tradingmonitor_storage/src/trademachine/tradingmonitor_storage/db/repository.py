"""Repository layer that abstracts SQLAlchemy models from base consumers.

This module provides repository classes that return dictionaries/DataFrames
instead of SQLAlchemy model objects, decoupling bases from database schema changes.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import func, text
from sqlalchemy.orm import Session, joinedload
from trademachine.tradingmonitor_storage.db.aggregates import (
    get_strategy_daily_profit_rows,
    get_strategy_net_profit_map,
    get_strategy_trade_count_map,
)
from trademachine.tradingmonitor_storage.db.database import SessionLocal
from trademachine.tradingmonitor_storage.db.deal_filters import apply_deal_search_filter
from trademachine.tradingmonitor_storage.db.models import (
    Account,
    Backtest,
    BacktestDeal,
    BacktestEquity,
    Deal,
    DealType,
    EquityCurve,
    Portfolio,
    Strategy,
    Symbol,
)


def to_iso(dt: datetime | None) -> str | None:
    """Convert datetime or pd.Timestamp to ISO format string, handling None gracefully."""
    return dt.isoformat() if dt else None


def _model_to_dict(model: Any) -> dict:
    """Convert a SQLAlchemy model instance to a dictionary."""
    result = {}
    for column in model.__table__.columns:
        value = getattr(model, column.name)
        if isinstance(value, Enum):
            value = value.value
        elif hasattr(value, "isoformat"):
            value = to_iso(value)
        result[column.name] = value
    return result


def _model_to_dict_deals(model: Any) -> dict:
    """Convert a Deal model to dictionary with proper enum handling."""
    return {
        "id": model.id,
        "timestamp": to_iso(model.timestamp),
        "ticket": model.ticket,
        "strategy_id": model.strategy_id,
        "symbol": model.symbol,
        "type": model.type.value if isinstance(model.type, Enum) else model.type,
        "volume": float(model.volume) if model.volume is not None else None,
        "price": float(model.price) if model.price is not None else None,
        "profit": float(model.profit) if model.profit is not None else None,
        "commission": float(model.commission) if model.commission is not None else None,
        "swap": float(model.swap) if model.swap is not None else None,
    }


def _assign_if_present(obj: Any, mapping: dict[str, Any]) -> None:
    """Set attributes on *obj* for each key in *mapping* whose value is not None."""
    for attr, value in mapping.items():
        if value is not None:
            setattr(obj, attr, value)


def insert_deal_if_new(db: Session, deal_data: dict[str, Any]) -> bool:
    """Insert a deal only once, even if the same ticket is re-ingested with a new timestamp."""
    key_inserted = db.execute(
        text(
            """
            INSERT INTO deal_ingestion_keys (strategy_id, ticket, deal_timestamp)
            VALUES (:strategy_id, :ticket, :timestamp)
            ON CONFLICT (strategy_id, ticket) DO NOTHING
            RETURNING strategy_id
            """
        ),
        deal_data,
    ).scalar_one_or_none()
    if key_inserted is None:
        return False

    db.execute(
        text(
            """
            INSERT INTO deals (timestamp, ticket, strategy_id, symbol, type, volume, price, profit, commission, swap)
            VALUES (:timestamp, :ticket, :strategy_id, :symbol, :type, :volume, :price, :profit, :commission, :swap)
            """
        ),
        deal_data,
    )
    return True


def _lookup_symbol_id(db: Session, symbol_name: str | None) -> int | None:
    if symbol_name is None:
        return None
    row = db.query(Symbol.id).filter(Symbol.name == symbol_name).first()
    if row is not None:
        return int(row[0])

    symbol = Symbol(name=symbol_name)
    db.add(symbol)
    db.flush()
    return int(symbol.id)


class AccountRepository:
    """Repository for Account operations."""

    def get_by_id(self, account_id: str) -> dict | None:
        """Get account by ID."""
        db = SessionLocal()
        try:
            acc = db.query(Account).filter(Account.id == account_id).first()
            return _model_to_dict(acc) if acc else None
        finally:
            db.close()

    def get_all(self) -> list[dict]:
        """Get all accounts."""
        db = SessionLocal()
        try:
            accounts = db.query(Account).all()
            return [_model_to_dict(a) for a in accounts]
        finally:
            db.close()

    def create_or_update(
        self,
        account_id: str,
        name: str | None = None,
        broker: str | None = None,
        account_type: str | None = None,
        currency: str | None = None,
        description: str | None = None,
        balance: float = 0.0,
        free_margin: float = 0.0,
        total_deposits: float = 0.0,
        total_withdrawals: float = 0.0,
    ) -> None:
        """Create or update an account."""
        db = SessionLocal()
        try:
            acc = db.query(Account).filter(Account.id == account_id).first()
            if not acc:
                acc = Account(id=account_id)
                db.add(acc)

            _assign_if_present(
                acc,
                {
                    "name": name,
                    "broker": broker,
                    "account_type": account_type,
                    "currency": currency,
                    "description": description,
                    "balance": balance,
                    "free_margin": free_margin,
                    "total_deposits": total_deposits,
                    "total_withdrawals": total_withdrawals,
                },
            )

            db.commit()
        finally:
            db.close()

    def delete(self, account_id: str) -> bool:
        """Delete an account by ID. Returns True if deleted."""
        db = SessionLocal()
        try:
            acc = db.query(Account).filter(Account.id == account_id).first()
            if not acc:
                return False
            db.delete(acc)
            db.commit()
            return True
        finally:
            db.close()


class StrategyRepository:
    """Repository for Strategy operations."""

    def get_by_id(self, strategy_id: str, include_account: bool = False) -> dict | None:
        """Get strategy by ID."""
        db = SessionLocal()
        try:
            query = db.query(Strategy)
            if include_account:
                query = query.options(joinedload(Strategy.account))
            s = query.filter(Strategy.id == strategy_id).first()
            if not s:
                return None
            result = _model_to_dict(s)
            if include_account and s.account:
                result["account"] = _model_to_dict(s.account)
            return result
        finally:
            db.close()

    def get_all(self, include_account: bool = False) -> list[dict]:
        """Get all strategies."""
        db = SessionLocal()
        try:
            query = db.query(Strategy)
            if include_account:
                query = query.options(joinedload(Strategy.account))
            strategies = query.all()
            results = []
            for s in strategies:
                result = _model_to_dict(s)
                if include_account and s.account:
                    result["account"] = _model_to_dict(s.account)
                results.append(result)
            return results
        finally:
            db.close()

    def get_real_strategies(self) -> list[dict]:
        """Get all strategies with real_account=True."""
        db = SessionLocal()
        try:
            strategies = (
                db.query(Strategy)
                .filter(Strategy.real_account.is_(True))
                .options(joinedload(Strategy.account))
                .all()
            )
            results = []
            for s in strategies:
                result = _model_to_dict(s)
                if s.account:
                    result["account"] = _model_to_dict(s.account)
                results.append(result)
            return results
        finally:
            db.close()

    def create_or_update(
        self,
        strategy_id: str,
        name: str | None = None,
        account_id: str | None = None,
        symbol: str | None = None,
        timeframe: str | None = None,
        operational_style: str | None = None,
        trade_duration: str | None = None,
        initial_balance: float | None = None,
        base_currency: str | None = None,
        description: str | None = None,
        live: bool | None = None,
        real_account: bool | None = None,
    ) -> None:
        """Create or update a strategy."""
        db = SessionLocal()
        try:
            strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
            if not strategy:
                strategy = Strategy(id=strategy_id)
                db.add(strategy)

            _assign_if_present(
                strategy,
                {
                    "name": name,
                    "account_id": account_id,
                    "timeframe": timeframe,
                    "operational_style": operational_style,
                    "trade_duration": trade_duration,
                    "initial_balance": initial_balance,
                    "base_currency": base_currency,
                    "description": description,
                    "live": live,
                    "real_account": real_account,
                },
            )
            if symbol is not None:
                strategy.symbol = symbol
                strategy.symbol_id = _lookup_symbol_id(db, symbol)

            db.commit()
        finally:
            db.close()

    def link_to_account(self, strategy_id: str, account_id: str) -> None:
        """Link a strategy to an account."""
        db = SessionLocal()
        try:
            db.query(Strategy).filter(
                Strategy.id == strategy_id, Strategy.account_id.is_(None)
            ).update({"account_id": account_id})
            db.commit()
        finally:
            db.close()

    def delete(self, strategy_id: str) -> bool:
        """Delete a strategy and all related data. Returns True if deleted."""
        db = SessionLocal()
        try:
            strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
            if not strategy:
                return False

            # Delete related data (child tables with FK to strategy)
            db.execute(
                text("DELETE FROM deals WHERE strategy_id = :sid"), {"sid": strategy_id}
            )
            db.execute(
                text("DELETE FROM equity_curve WHERE strategy_id = :sid"),
                {"sid": strategy_id},
            )
            db.execute(
                text(
                    "DELETE FROM backtest_deals WHERE backtest_id IN (SELECT id FROM backtests WHERE strategy_id = :sid)"
                ),
                {"sid": strategy_id},
            )
            db.execute(
                text(
                    "DELETE FROM backtest_equity WHERE backtest_id IN (SELECT id FROM backtests WHERE strategy_id = :sid)"
                ),
                {"sid": strategy_id},
            )
            db.execute(
                text("DELETE FROM backtests WHERE strategy_id = :sid"),
                {"sid": strategy_id},
            )
            db.execute(
                text("DELETE FROM portfolio_strategy WHERE strategy_id = :sid"),
                {"sid": strategy_id},
            )
            db.delete(strategy)
            db.commit()
            return True
        finally:
            db.close()

    def get_by_account(self, account_id: str) -> list[dict]:
        """Get all strategies for an account."""
        db = SessionLocal()
        try:
            strategies = (
                db.query(Strategy).filter(Strategy.account_id == account_id).all()
            )
            return [_model_to_dict(s) for s in strategies]
        finally:
            db.close()


class PortfolioRepository:
    """Repository for Portfolio operations."""

    def get_by_id(
        self, portfolio_id: int, include_strategies: bool = False
    ) -> dict | None:
        """Get portfolio by ID."""
        db = SessionLocal()
        try:
            query = db.query(Portfolio)
            if include_strategies:
                query = query.options(joinedload(Portfolio.strategies))
            p = query.filter(Portfolio.id == portfolio_id).first()
            if not p:
                return None
            result = _model_to_dict(p)
            if include_strategies:
                result["strategies"] = [_model_to_dict(s) for s in p.strategies]
            return result
        finally:
            db.close()

    def get_all(self, include_strategies: bool = False) -> list[dict]:
        """Get all portfolios."""
        db = SessionLocal()
        try:
            query = db.query(Portfolio)
            if include_strategies:
                query = query.options(joinedload(Portfolio.strategies))
            portfolios = query.all()
            results = []
            for p in portfolios:
                result = _model_to_dict(p)
                if include_strategies:
                    result["strategies"] = [_model_to_dict(s) for s in p.strategies]
                results.append(result)
            return results
        finally:
            db.close()

    def create(
        self,
        name: str,
        description: str | None = None,
        live: bool = False,
        real_account: bool = False,
        initial_balance: float | None = None,
        strategy_ids: list[str] | None = None,
    ) -> int:
        """Create a new portfolio. Returns the portfolio ID."""
        db = SessionLocal()
        try:
            portfolio = Portfolio(
                name=name,
                description=description,
                live=live,
                real_account=real_account,
                initial_balance=initial_balance,
            )
            if strategy_ids:
                strategies = (
                    db.query(Strategy).filter(Strategy.id.in_(strategy_ids)).all()
                )
                portfolio.strategies = strategies
            db.add(portfolio)
            db.commit()
            db.refresh(portfolio)
            return portfolio.id  # type: ignore[no-any-return]
        finally:
            db.close()

    def update(
        self,
        portfolio_id: int,
        name: str | None = None,
        description: str | None = None,
        live: bool | None = None,
        real_account: bool | None = None,
        initial_balance: float | None = None,
        strategy_ids: list[str] | None = None,
    ) -> dict | None:
        """Update a portfolio. Returns updated portfolio or None if not found."""
        db = SessionLocal()
        try:
            p = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
            if not p:
                return None

            _assign_if_present(
                p,
                {
                    "name": name,
                    "description": description,
                    "live": live,
                    "real_account": real_account,
                    "initial_balance": initial_balance,
                },
            )
            if strategy_ids is not None:
                strategies = (
                    db.query(Strategy).filter(Strategy.id.in_(strategy_ids)).all()
                )
                p.strategies = strategies

            db.commit()
            db.refresh(p)
            return _model_to_dict(p)
        finally:
            db.close()

    def add_strategy(self, portfolio_id: int, strategy_id: str) -> bool:
        """Add a strategy to a portfolio. Returns True if successful."""
        db = SessionLocal()
        try:
            portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
            strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
            if not portfolio or not strategy:
                return False
            if strategy not in portfolio.strategies:
                portfolio.strategies.append(strategy)
                db.commit()
            return True
        finally:
            db.close()

    def get_strategy_ids(self, portfolio_id: int) -> list[str]:
        """Get all strategy IDs for a portfolio."""
        db = SessionLocal()
        try:
            p = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
            if not p:
                return []
            return [s.id for s in p.strategies]
        finally:
            db.close()

    def delete(self, portfolio_id: int) -> bool:
        """Delete a portfolio. Returns True if deleted."""
        db = SessionLocal()
        try:
            p = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
            if not p:
                return False
            db.delete(p)
            db.commit()
            return True
        finally:
            db.close()


class DealRepository:
    """Repository for Deal operations."""

    def get_by_strategy(
        self,
        strategy_id: str,
        page: int = 1,
        page_size: int = 50,
        q: str | None = None,
    ) -> tuple[list[dict], int]:
        """Get deals for a strategy with pagination.

        Returns (deals, total_count).
        """
        db = SessionLocal()
        try:
            base = db.query(Deal).filter(Deal.strategy_id == strategy_id)
            base = apply_deal_search_filter(base, q)

            total = base.count()
            deals = (
                base.order_by(Deal.timestamp.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
            return [_model_to_dict_deals(d) for d in deals], total
        finally:
            db.close()

    def get_all_by_strategy(self, strategy_id: str) -> list[dict]:
        """Get all deals for a strategy (for metrics calculations)."""
        db = SessionLocal()
        try:
            deals = (
                db.query(Deal)
                .filter(Deal.strategy_id == strategy_id)
                .order_by(Deal.timestamp)
                .all()
            )
            return [_model_to_dict_deals(d) for d in deals]
        finally:
            db.close()

    def save(self, deal_data: dict) -> None:
        """Save a single deal."""
        db = SessionLocal()
        try:
            insert_deal_if_new(db, deal_data)
            db.commit()
        finally:
            db.close()

    def bulk_save(self, deals: list[dict]) -> None:
        """Bulk save deals."""
        db = SessionLocal()
        try:
            for deal_data in deals:
                insert_deal_if_new(db, deal_data)
            db.commit()
        finally:
            db.close()

    def get_net_profit_by_strategies(self, strategy_ids: list[str]) -> dict[str, float]:
        """Get net profit sum for multiple strategies."""
        db = SessionLocal()
        try:
            return get_strategy_net_profit_map(db, strategy_ids)
        finally:
            db.close()

    def get_trades_count_by_strategies(self, strategy_ids: list[str]) -> dict[str, int]:
        """Get trades count for multiple strategies."""
        db = SessionLocal()
        try:
            return get_strategy_trade_count_map(db, strategy_ids)
        finally:
            db.close()

    def get_daily_profit(
        self, strategy_id: str | None = None, strategy_ids: list[str] | None = None
    ) -> list[dict]:
        """Get daily profit for a strategy or list of strategies."""
        db = SessionLocal()
        try:
            if strategy_id:
                return get_strategy_daily_profit_rows(db, [strategy_id])
            if strategy_ids:
                return get_strategy_daily_profit_rows(db, strategy_ids)
            return get_strategy_daily_profit_rows(db, None)
        finally:
            db.close()

    def get_trade_stats_by_hour(self, strategy_id: str) -> list[dict]:
        """Get trade statistics grouped by hour."""
        db = SessionLocal()
        try:
            from sqlalchemy import extract

            rows = (
                db.query(
                    extract("hour", Deal.timestamp).label("hour"),
                    func.count().label("count"),
                    func.sum(Deal.profit + Deal.commission + Deal.swap).label(
                        "net_profit"
                    ),
                )
                .filter(Deal.strategy_id == strategy_id)
                .filter(Deal.type.in_([DealType.BUY, DealType.SELL]))
                .group_by(extract("hour", Deal.timestamp))
                .order_by(extract("hour", Deal.timestamp))
                .all()
            )
            return [
                {
                    "hour": int(r.hour),
                    "count": int(r.count),
                    "net_profit": round(float(r.net_profit or 0), 2),
                }
                for r in rows
            ]
        finally:
            db.close()

    def get_trade_stats_by_dow(self, strategy_id: str) -> list[dict]:
        """Get trade statistics grouped by day of week."""
        db = SessionLocal()
        try:
            from sqlalchemy import extract

            rows = (
                db.query(
                    extract("isodow", Deal.timestamp).label("dow"),
                    func.count().label("count"),
                    func.sum(Deal.profit + Deal.commission + Deal.swap).label(
                        "net_profit"
                    ),
                )
                .filter(Deal.strategy_id == strategy_id)
                .filter(Deal.type.in_([DealType.BUY, DealType.SELL]))
                .group_by(extract("isodow", Deal.timestamp))
                .order_by(extract("isodow", Deal.timestamp))
                .all()
            )
            DOW_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            result = []
            for r in rows:
                dow = int(r.dow) - 1
                result.append(
                    {
                        "dow": int(r.dow),
                        "label": DOW_LABELS[dow],
                        "count": int(r.count),
                        "net_profit": round(float(r.net_profit or 0), 2),
                    }
                )
            return result
        finally:
            db.close()

    def exists(self, strategy_id: str) -> bool:
        """Check if any deals exist for a strategy."""
        db = SessionLocal()
        try:
            count = (
                db.query(func.count(Deal.id))
                .filter(Deal.strategy_id == strategy_id)
                .scalar()
            )
            return bool(count and count > 0)
        finally:
            db.close()


class EquityCurveRepository:
    """Repository for EquityCurve operations."""

    def get_latest_by_strategies(self, strategy_ids: list[str]) -> dict[str, dict]:
        """Get latest equity point for each strategy."""
        db = SessionLocal()
        try:
            subq = (
                db.query(
                    EquityCurve.strategy_id,
                    func.max(EquityCurve.timestamp).label("latest_ts"),
                )
                .filter(EquityCurve.strategy_id.in_(strategy_ids))
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
            return {str(r.strategy_id): _model_to_dict(r) for r in rows}
        finally:
            db.close()

    def get_all_by_strategy(self, strategy_id: str) -> list[dict]:
        """Get full equity curve for a strategy."""
        db = SessionLocal()
        try:
            rows = (
                db.query(EquityCurve)
                .filter(EquityCurve.strategy_id == strategy_id)
                .order_by(EquityCurve.timestamp)
                .all()
            )
            return [_model_to_dict(r) for r in rows]
        finally:
            db.close()

    def get_by_strategies(
        self, strategy_ids: list[str]
    ) -> dict[str, list[dict[str, Any]]]:
        """Get equity curves for multiple strategies."""
        db = SessionLocal()
        try:
            rows = (
                db.query(EquityCurve)
                .filter(EquityCurve.strategy_id.in_(strategy_ids))
                .order_by(EquityCurve.timestamp)
                .all()
            )
            result: dict[str, list[dict[str, Any]]] = {sid: [] for sid in strategy_ids}
            for row in rows:
                result[str(row.strategy_id)].append(
                    {
                        "ts": to_iso(row.timestamp),
                        "balance": float(row.balance),
                        "equity": float(row.equity),
                    }
                )
            return result
        finally:
            db.close()

    def save(self, equity_data: dict) -> None:
        """Save or update an equity point."""
        db = SessionLocal()
        try:
            stmt = text(
                """
                INSERT INTO equity_curve (timestamp, strategy_id, balance, equity)
                VALUES (:timestamp, :strategy_id, :balance, :equity)
                ON CONFLICT (timestamp, strategy_id) DO UPDATE SET balance = :balance, equity = :equity
                """
            )
            db.execute(stmt, equity_data)
            db.commit()
        finally:
            db.close()

    def get_latest(self, strategy_id: str) -> dict | None:
        """Get the latest equity point for a strategy."""
        db = SessionLocal()
        try:
            eq = (
                db.query(EquityCurve)
                .filter(EquityCurve.strategy_id == strategy_id)
                .order_by(EquityCurve.timestamp.desc())
                .first()
            )
            return _model_to_dict(eq) if eq else None
        finally:
            db.close()


class BacktestRepository:
    """Repository for Backtest operations."""

    def get_by_id(self, backtest_id: int) -> dict | None:
        """Get backtest by ID."""
        db = SessionLocal()
        try:
            bt = db.query(Backtest).filter(Backtest.id == backtest_id).first()
            return _model_to_dict(bt) if bt else None
        finally:
            db.close()

    def get_by_strategy_and_run(
        self, strategy_id: str, client_run_id: int
    ) -> dict | None:
        """Get backtest by strategy ID and client run ID."""
        db = SessionLocal()
        try:
            bt = (
                db.query(Backtest)
                .filter(
                    Backtest.strategy_id == strategy_id,
                    Backtest.client_run_id == client_run_id,
                )
                .first()
            )
            return _model_to_dict(bt) if bt else None
        finally:
            db.close()

    def get_by_strategy(self, strategy_id: str) -> list[dict]:
        """Get all backtests for a strategy."""
        db = SessionLocal()
        try:
            backtests = (
                db.query(Backtest)
                .filter(Backtest.strategy_id == strategy_id)
                .order_by(Backtest.created_at.desc())
                .all()
            )
            return [_model_to_dict(bt) for bt in backtests]
        finally:
            db.close()

    def create_or_update(self, backtest_data: dict) -> int:
        """Create or update a backtest. Returns backtest ID."""
        db = SessionLocal()
        try:
            payload = dict(backtest_data)
            if "symbol" in payload and "symbol_id" not in payload:
                payload["symbol_id"] = _lookup_symbol_id(db, payload.get("symbol"))
            bt = Backtest(**payload)
            db.merge(bt)
            db.commit()

            # Get the backtest ID
            result = (
                db.query(Backtest)
                .filter(
                    Backtest.strategy_id == backtest_data["strategy_id"],
                    Backtest.client_run_id == backtest_data["client_run_id"],
                )
                .first()
            )
            return result.id if result else 0
        finally:
            db.close()

    def update_status(self, backtest_id: int, status: str) -> None:
        """Update backtest status."""
        db = SessionLocal()
        try:
            bt = db.query(Backtest).filter(Backtest.id == backtest_id).first()
            if bt:
                bt.status = status
                db.commit()
        finally:
            db.close()

    def delete(self, backtest_id: int) -> bool:
        """Delete a backtest. Returns True if deleted."""
        db = SessionLocal()
        try:
            bt = db.query(Backtest).filter(Backtest.id == backtest_id).first()
            if not bt:
                return False
            db.delete(bt)
            db.commit()
            return True
        finally:
            db.close()

    def get_net_profit(self, backtest_id: int) -> float | None:
        """Get net profit for a backtest."""
        db = SessionLocal()
        try:
            net = (
                db.query(
                    func.sum(
                        BacktestDeal.profit
                        + BacktestDeal.commission
                        + BacktestDeal.swap
                    )
                )
                .filter(
                    BacktestDeal.backtest_id == backtest_id,
                    BacktestDeal.type.in_([DealType.BUY, DealType.SELL]),
                )
                .scalar()
            )
            return round(float(net), 2) if net is not None else None
        finally:
            db.close()


class BacktestDealRepository:
    """Repository for BacktestDeal operations."""

    def get_by_backtest(
        self,
        backtest_id: int,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict], int]:
        """Get deals for a backtest with pagination.

        Returns (deals, total_count).
        """
        db = SessionLocal()
        try:
            total = (
                db.query(func.count(BacktestDeal.ticket))
                .filter(BacktestDeal.backtest_id == backtest_id)
                .scalar()
            )
            deals = (
                db.query(BacktestDeal)
                .filter(BacktestDeal.backtest_id == backtest_id)
                .order_by(BacktestDeal.timestamp.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
            return [_model_to_dict_deals(d) for d in deals], total
        finally:
            db.close()

    def save(self, backtest_id: int, deal_data: dict) -> None:
        """Save a backtest deal."""
        db = SessionLocal()
        try:
            stmt = text(
                """
                INSERT INTO backtest_deals (backtest_id, timestamp, ticket, symbol, type, volume, price, profit, commission, swap)
                VALUES (:backtest_id, :timestamp, :ticket, :symbol, :type, :volume, :price, :profit, :commission, :swap)
                ON CONFLICT DO NOTHING
                """
            )
            db.execute(stmt, {**deal_data, "backtest_id": backtest_id})
            db.commit()
        finally:
            db.close()

    def bulk_save(self, backtest_id: int, deals: list[dict]) -> None:
        """Bulk save backtest deals."""
        db = SessionLocal()
        try:
            for deal_data in deals:
                stmt = text(
                    """
                    INSERT INTO backtest_deals (backtest_id, timestamp, ticket, symbol, type, volume, price, profit, commission, swap)
                    VALUES (:backtest_id, :timestamp, :ticket, :symbol, :type, :volume, :price, :profit, :commission, :swap)
                    ON CONFLICT DO NOTHING
                    """
                )
                db.execute(stmt, {**deal_data, "backtest_id": backtest_id})
            db.commit()
        finally:
            db.close()

    def get_daily_profit(self, backtest_id: int) -> list[dict]:
        """Get daily profit for a backtest."""
        db = SessionLocal()
        try:
            from sqlalchemy import cast
            from sqlalchemy.types import Date

            rows = (
                db.query(
                    cast(BacktestDeal.timestamp, Date).label("date"),
                    func.sum(
                        BacktestDeal.profit
                        + BacktestDeal.commission
                        + BacktestDeal.swap
                    ).label("net_profit"),
                )
                .filter(BacktestDeal.backtest_id == backtest_id)
                .filter(BacktestDeal.type.in_([DealType.BUY, DealType.SELL]))
                .group_by(cast(BacktestDeal.timestamp, Date))
                .order_by(cast(BacktestDeal.timestamp, Date))
                .all()
            )
            return [
                {"date": str(r.date), "net_profit": float(r.net_profit)} for r in rows
            ]
        finally:
            db.close()

    def get_trade_stats_by_hour(self, backtest_id: int) -> list[dict]:
        """Get trade statistics grouped by hour for a backtest."""
        db = SessionLocal()
        try:
            from sqlalchemy import extract

            rows = (
                db.query(
                    extract("hour", BacktestDeal.timestamp).label("hour"),
                    func.count().label("count"),
                    func.sum(
                        BacktestDeal.profit
                        + BacktestDeal.commission
                        + BacktestDeal.swap
                    ).label("net_profit"),
                )
                .filter(BacktestDeal.backtest_id == backtest_id)
                .filter(BacktestDeal.type.in_([DealType.BUY, DealType.SELL]))
                .group_by(extract("hour", BacktestDeal.timestamp))
                .order_by(extract("hour", BacktestDeal.timestamp))
                .all()
            )
            return [
                {
                    "hour": int(r.hour),
                    "count": int(r.count),
                    "net_profit": round(float(r.net_profit or 0), 2),
                }
                for r in rows
            ]
        finally:
            db.close()

    def get_trade_stats_by_dow(self, backtest_id: int) -> list[dict]:
        """Get trade statistics grouped by day of week for a backtest."""
        db = SessionLocal()
        try:
            from sqlalchemy import extract

            rows = (
                db.query(
                    extract("isodow", BacktestDeal.timestamp).label("dow"),
                    func.count().label("count"),
                    func.sum(
                        BacktestDeal.profit
                        + BacktestDeal.commission
                        + BacktestDeal.swap
                    ).label("net_profit"),
                )
                .filter(BacktestDeal.backtest_id == backtest_id)
                .filter(BacktestDeal.type.in_([DealType.BUY, DealType.SELL]))
                .group_by(extract("isodow", BacktestDeal.timestamp))
                .order_by(extract("isodow", BacktestDeal.timestamp))
                .all()
            )
            DOW_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            result = []
            for r in rows:
                dow = int(r.dow) - 1
                result.append(
                    {
                        "dow": int(r.dow),
                        "label": DOW_LABELS[dow],
                        "count": int(r.count),
                        "net_profit": round(float(r.net_profit or 0), 2),
                    }
                )
            return result
        finally:
            db.close()


class BacktestEquityRepository:
    """Repository for BacktestEquity operations."""

    def get_by_backtest(self, backtest_id: int) -> list[dict]:
        """Get equity curve for a backtest."""
        db = SessionLocal()
        try:
            rows = (
                db.query(BacktestEquity)
                .filter(BacktestEquity.backtest_id == backtest_id)
                .order_by(BacktestEquity.timestamp)
                .all()
            )
            return [_model_to_dict(r) for r in rows]
        finally:
            db.close()

    def save(self, backtest_id: int, equity_data: dict) -> None:
        """Save or update a backtest equity point."""
        db = SessionLocal()
        try:
            stmt = text(
                """
                INSERT INTO backtest_equity (backtest_id, timestamp, balance, equity)
                VALUES (:backtest_id, :timestamp, :balance, :equity)
                ON CONFLICT (backtest_id, timestamp) DO UPDATE SET balance = :balance, equity = :equity
                """
            )
            db.execute(stmt, {**equity_data, "backtest_id": backtest_id})
            db.commit()
        finally:
            db.close()

    def bulk_save(self, backtest_id: int, equity_points: list[dict]) -> None:
        """Bulk save backtest equity points."""
        db = SessionLocal()
        try:
            for eq_data in equity_points:
                stmt = text(
                    """
                    INSERT INTO backtest_equity (backtest_id, timestamp, balance, equity)
                    VALUES (:backtest_id, :timestamp, :balance, :equity)
                    ON CONFLICT (backtest_id, timestamp) DO UPDATE SET balance = :balance, equity = :equity
                    """
                )
                db.execute(stmt, {**eq_data, "backtest_id": backtest_id})
            db.commit()
        finally:
            db.close()


class SymbolRepository:
    """Repository for Symbol operations."""

    def get_all(self) -> list[dict]:
        """Get all symbols."""
        db = SessionLocal()
        try:
            symbols = db.query(Symbol).order_by(Symbol.market, Symbol.name).all()
            return [_model_to_dict(s) for s in symbols]
        finally:
            db.close()

    def get_by_name(self, name: str) -> dict | None:
        """Get symbol by name."""
        db = SessionLocal()
        try:
            sym = db.query(Symbol).filter(Symbol.name == name).first()
            return _model_to_dict(sym) if sym else None
        finally:
            db.close()

    def create(
        self, name: str, market: str | None = None, lot: float | None = None
    ) -> int:
        """Create a new symbol. Returns the symbol ID."""
        db = SessionLocal()
        try:
            sym = Symbol(name=name, market=market, lot=lot)
            db.add(sym)
            db.commit()
            db.refresh(sym)
            return sym.id  # type: ignore[no-any-return]
        finally:
            db.close()

    def update(
        self,
        symbol_id: int,
        name: str | None = None,
        market: str | None = None,
        lot: float | None = None,
    ) -> dict | None:
        """Update a symbol. Returns updated symbol or None if not found."""
        db = SessionLocal()
        try:
            sym = db.query(Symbol).filter(Symbol.id == symbol_id).first()
            if not sym:
                return None
            if name is not None:
                sym.name = name
                db.query(Strategy).filter(Strategy.symbol_id == symbol_id).update(
                    {"symbol": name},
                    synchronize_session=False,
                )
                db.query(Backtest).filter(Backtest.symbol_id == symbol_id).update(
                    {"symbol": name},
                    synchronize_session=False,
                )
            if market is not None:
                sym.market = market
            if lot is not None:
                sym.lot = lot
            db.commit()
            db.refresh(sym)
            return _model_to_dict(sym)
        finally:
            db.close()

    def delete(self, symbol_id: int) -> bool:
        """Delete a symbol. Returns True if deleted."""
        db = SessionLocal()
        try:
            sym = db.query(Symbol).filter(Symbol.id == symbol_id).first()
            if not sym:
                return False
            in_use = (
                db.query(Strategy.id).filter(Strategy.symbol_id == symbol_id).first()
            )
            if in_use is None:
                in_use = (
                    db.query(Backtest.id)
                    .filter(Backtest.symbol_id == symbol_id)
                    .first()
                )
            if in_use is not None:
                return False
            db.delete(sym)
            db.commit()
            return True
        finally:
            db.close()
