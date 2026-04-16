from unittest.mock import MagicMock

from sqlalchemy import select
from trademachine.tradingmonitor_ingestion.ingestion.schemas import (
    AccountSchema,
    DealSchema,
    EquitySchema,
)
from trademachine.tradingmonitor_ingestion.ingestion.tcp_server import (
    _build_runtime_schema_from_payload,
    _process_message,
    process_account,
    process_deal,
)
from trademachine.tradingmonitor_storage.db.models import Account, Strategy
from trademachine.tradingmonitor_storage.db.models import Deal as PersistedDeal


def test_process_deal_logic():
    # Mock database session
    db = MagicMock()

    # Mock query: return MagicMock so both subscript access (row[0] in _get_symbol_id)
    # and attribute access (strategy.id in ensure_strategy_exists) work transparently.
    db.query.return_value.filter.return_value.first.return_value = MagicMock()

    # Valid data according to DealSchema
    deal_data = DealSchema(
        time=1704067200,
        ticket=123456,
        magic=123,
        symbol="EURUSD",
        type="buy",
        volume=0.1,
        price=1.10,
        profit=10.0,
        commission=-1.0,
        swap=0.0,
    )

    process_deal(db, deal_data)

    # process_deal now uses db.execute() with pg_insert for on_conflict semantics
    assert db.execute.called
    # We can't easily inspect the SQLAlchemy statement object in a simple mock,
    # but verifying it was called is the first step.


def test_process_account_logic():
    db = MagicMock()

    # Mock query for ensure_account_exists
    db.query.return_value.filter.return_value.first.return_value = Account(id="999")

    acc_data = AccountSchema(
        login=999,
        broker="IC Markets",
        balance=10000.0,
        free_margin=9500.0,
        deposits=10000.0,
        withdrawals=0.0,
    )

    process_account(db, acc_data)

    # Verify account properties were updated
    acc = db.query.return_value.filter.return_value.first.return_value
    assert acc.balance == 10000.0
    assert acc.free_margin == 9500.0


def test_runtime_context_is_extracted_from_equity_payload():
    payload = EquitySchema(
        time=1704067200,
        magic=123,
        balance=10000.0,
        equity=10050.0,
        open_profit=50.0,
        open_trades_count=2,
        pending_orders_count=1,
    )

    runtime = _build_runtime_schema_from_payload(payload)

    assert runtime is not None
    assert runtime.magic == 123
    assert runtime.time == 1704067200
    assert runtime.open_profit == 50.0
    assert runtime.open_trades_count == 2
    assert runtime.pending_orders_count == 1


def test_runtime_context_is_ignored_when_missing_fields():
    payload = DealSchema(
        time=1704067200,
        ticket=123456,
        magic=123,
        symbol="EURUSD",
        type="buy",
        volume=0.1,
        price=1.10,
        profit=10.0,
    )

    assert _build_runtime_schema_from_payload(payload) is None


def test_process_deal_is_idempotent_across_timestamp_changes(db_session):
    db_session.add(Strategy(id="123", name="Test Strategy", symbol="EURUSD"))
    db_session.commit()

    first = DealSchema(
        time=1704067200,
        ticket=123456,
        magic=123,
        symbol="EURUSD",
        type="buy",
        volume=0.1,
        price=1.10,
        profit=10.0,
        commission=-1.0,
        swap=0.0,
    )
    second = first.model_copy(update={"time": 1704067260})

    process_deal(db_session, first)
    process_deal(db_session, second)
    db_session.commit()

    rows = db_session.execute(select(PersistedDeal)).scalars().all()
    assert len(rows) == 1
    assert rows[0].ticket == 123456


def test_process_message_dispatches_deal_handler(monkeypatch):
    db = MagicMock()
    seen_strategies: set[str] = set()
    payload = {
        "time": 1704067200,
        "ticket": 123456,
        "magic": 123,
        "symbol": "EURUSD",
        "type": "buy",
        "volume": 0.1,
        "price": 1.10,
        "profit": 10.0,
        "commission": -1.0,
        "swap": 0.0,
    }

    process_deal_mock = MagicMock()
    runtime_mock = MagicMock()
    monkeypatch.setattr(
        "trademachine.tradingmonitor_ingestion.ingestion.processors.process_deal",
        process_deal_mock,
    )
    monkeypatch.setattr(
        "trademachine.tradingmonitor_ingestion.ingestion.processors.maybe_process_runtime_context",
        runtime_mock,
    )

    account_id = _process_message(db, "DEAL", payload, "acc-1", seen_strategies)

    assert account_id == "acc-1"
    assert seen_strategies == {"123"}
    process_deal_mock.assert_called_once()
    runtime_mock.assert_called_once()


def test_process_message_dispatches_account_handler(monkeypatch):
    db = MagicMock()
    seen_strategies = {"123", "456"}
    payload = {
        "login": 999,
        "broker": "IC Markets",
        "balance": 10000.0,
        "free_margin": 9500.0,
        "deposits": 10000.0,
        "withdrawals": 0.0,
    }

    process_account_mock = MagicMock()
    link_mock = MagicMock()
    runtime_mock = MagicMock()
    monkeypatch.setattr(
        "trademachine.tradingmonitor_ingestion.ingestion.processors.process_account",
        process_account_mock,
    )
    monkeypatch.setattr(
        "trademachine.tradingmonitor_ingestion.ingestion.processors.link_strategies_to_account",
        link_mock,
    )
    monkeypatch.setattr(
        "trademachine.tradingmonitor_ingestion.ingestion.processors.maybe_process_runtime_context",
        runtime_mock,
    )

    account_id = _process_message(db, "ACCOUNT", payload, None, seen_strategies)

    assert account_id == "999"
    process_account_mock.assert_called_once()
    link_mock.assert_called_once_with(db, seen_strategies, "999")
    runtime_mock.assert_called_once()


def test_process_message_returns_existing_account_for_unknown_topic(monkeypatch):
    db = MagicMock()
    warning_mock = MagicMock()
    monkeypatch.setattr(
        "trademachine.tradingmonitor_ingestion.ingestion.tcp_server.logger.warning",
        warning_mock,
    )

    account_id = _process_message(db, "UNKNOWN", {"foo": "bar"}, "acc-1", set())

    assert account_id == "acc-1"
    warning_mock.assert_called_once()
