from datetime import UTC, datetime

from sqlalchemy.orm import sessionmaker
from trademachine.tradingmonitor_storage.db import repository as repo_module
from trademachine.tradingmonitor_storage.db.models import (
    Deal,
    DealIngestionKey,
    Strategy,
    Symbol,
)
from trademachine.tradingmonitor_storage.db.repository import (
    DealRepository,
    StrategyRepository,
)


def test_strategy_create_or_update_preserves_live_when_omitted(
    sqlite_engine, monkeypatch
):
    session_factory = sessionmaker(bind=sqlite_engine)
    monkeypatch.setattr(repo_module, "SessionLocal", session_factory)

    db = session_factory()
    try:
        db.add(Strategy(id="s-live", name="Original", live=True, real_account=True))
        db.commit()
    finally:
        db.close()

    StrategyRepository().create_or_update("s-live", name="Updated")

    db = session_factory()
    try:
        strategy = db.get(Strategy, "s-live")
        assert strategy is not None
        assert strategy.name == "Updated"
        assert strategy.live is True
        assert strategy.real_account is True
    finally:
        db.close()


def test_deal_repository_deduplicates_same_ticket_across_timestamps(
    sqlite_engine, monkeypatch
):
    session_factory = sessionmaker(bind=sqlite_engine)
    monkeypatch.setattr(repo_module, "SessionLocal", session_factory)

    db = session_factory()
    try:
        db.add(Strategy(id="s-100", name="Alpha"))
        db.commit()
    finally:
        db.close()

    repo = DealRepository()
    repo.save(
        {
            "timestamp": datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
            "ticket": 42,
            "strategy_id": "s-100",
            "symbol": "EURUSD",
            "type": "BUY",
            "volume": 0.1,
            "price": 1.1,
            "profit": 10.0,
            "commission": -1.0,
            "swap": 0.0,
        }
    )
    repo.save(
        {
            "timestamp": datetime(2024, 1, 1, 12, 1, tzinfo=UTC),
            "ticket": 42,
            "strategy_id": "s-100",
            "symbol": "EURUSD",
            "type": "BUY",
            "volume": 0.1,
            "price": 1.1,
            "profit": 10.0,
            "commission": -1.0,
            "swap": 0.0,
        }
    )

    db = session_factory()
    try:
        assert db.query(Deal).count() == 1
        key = (
            db.query(DealIngestionKey)
            .filter(DealIngestionKey.strategy_id == "s-100")
            .one()
        )
        assert key.ticket == 42
    finally:
        db.close()


def test_strategy_create_or_update_links_symbol_fk(sqlite_engine, monkeypatch):
    session_factory = sessionmaker(bind=sqlite_engine)
    monkeypatch.setattr(repo_module, "SessionLocal", session_factory)

    db = session_factory()
    try:
        db.add(Symbol(name="EURUSD"))
        db.commit()
    finally:
        db.close()

    StrategyRepository().create_or_update(
        "s-symbol",
        name="With Symbol",
        symbol="EURUSD",
    )

    db = session_factory()
    try:
        strategy = db.get(Strategy, "s-symbol")
        assert strategy is not None
        assert strategy.symbol == "EURUSD"
        assert strategy.symbol_id is not None
    finally:
        db.close()
