"""
Service-layer tests for components/tradingmonitor/src/trademachine/tradingmonitor/ingestion/tcp_server.py processors.

These tests isolate the processor functions from PostgreSQL by using
MagicMock for the DB session.  `pg_insert` (PostgreSQL dialect) is
never executed — instead we verify that `db.execute()` is called with
an object whose type reflects the intent, or we verify side effects
like cache population and ensure_strategy_exists calls.

For `ensure_strategy_exists`, we use the real function with a SQLite
session (provided by the shared `db_session` fixture) to verify ORM
behaviour.
"""

from unittest.mock import MagicMock, patch

import pytest
import trademachine.tradingmonitor.ingestion.tcp_server as server_module
from trademachine.tradingmonitor.db.models import Account, Strategy
from trademachine.tradingmonitor.ingestion.schemas import (
    AccountSchema,
    DealSchema,
    EquitySchema,
    StrategyRuntimeSchema,
)
from trademachine.tradingmonitor.ingestion.tcp_server import (
    EXISTING_ACCOUNTS,
    EXISTING_STRATEGIES,
    EXISTING_SYMBOLS,
    ensure_strategy_exists,
    process_account,
    process_deal,
    process_equity,
    process_strategy_runtime,
)

_VALID_TS = 1_700_000_000


@pytest.fixture(autouse=True)
def reset_caches():
    """Clear in-memory strategy/account caches before and after each test."""
    EXISTING_STRATEGIES.clear()
    EXISTING_ACCOUNTS.clear()
    EXISTING_SYMBOLS.clear()
    yield
    EXISTING_STRATEGIES.clear()
    EXISTING_ACCOUNTS.clear()
    EXISTING_SYMBOLS.clear()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _mock_db():
    """Return a MagicMock that mimics a SQLAlchemy session."""
    db = MagicMock()
    # query().filter().first() → None by default (strategy not found)
    db.query.return_value.filter.return_value.first.return_value = None
    return db


def _deal_schema(**overrides) -> DealSchema:
    base = dict(
        time=_VALID_TS,
        ticket=1,
        magic=42,
        symbol="EURUSD",
        type="buy",
        volume=0.1,
        price=1.08,
        profit=50.0,
    )
    base.update(overrides)
    return DealSchema(**base)


def _equity_schema(**overrides) -> EquitySchema:
    base = dict(time=_VALID_TS, magic=42, balance=10000.0, equity=10050.0)
    base.update(overrides)
    return EquitySchema(**base)


def _runtime_schema(**overrides) -> StrategyRuntimeSchema:
    base = dict(
        time=_VALID_TS,
        magic=42,
        open_profit=37.5,
        open_trades_count=2,
        pending_orders_count=1,
    )
    base.update(overrides)
    return StrategyRuntimeSchema(**base)


# ── process_equity: magic=0 guard ─────────────────────────────────────────────


class TestProcessEquityMagicZeroGuard:
    def test_magic_zero_returns_immediately_without_touching_db(self):
        # Arrange
        db = _mock_db()
        data = _equity_schema(magic=0)
        # Act
        process_equity(db, data)
        # Assert — no DB interaction at all
        db.execute.assert_not_called()
        db.query.assert_not_called()

    def test_magic_zero_does_not_add_to_strategy_cache(self):
        db = _mock_db()
        data = _equity_schema(magic=0)
        process_equity(db, data)
        assert "0" not in EXISTING_STRATEGIES

    def test_nonzero_magic_proceeds_to_db_execute(self):
        # Arrange
        db = _mock_db()
        data = _equity_schema(magic=42)
        # Act — pg_insert is PostgreSQL-specific; just verify execute is called
        process_equity(db, data)
        # Assert
        db.execute.assert_called_once()


# ── process_deal ──────────────────────────────────────────────────────────────


class TestProcessDeal:
    def test_process_deal_calls_db_execute(self):
        # Arrange
        db = _mock_db()
        data = _deal_schema()
        EXISTING_SYMBOLS.add(
            data.symbol
        )  # Skip symbol insertion to isolate deal execute
        # Act
        process_deal(db, data)
        # Assert — INSERT statement executed
        db.execute.assert_called_once()

    def test_process_deal_adds_strategy_to_cache(self):
        db = _mock_db()
        data = _deal_schema(magic=999)
        process_deal(db, data)
        assert "999" in EXISTING_STRATEGIES

    def test_process_deal_with_cached_strategy_skips_db_query(self):
        # Arrange — pre-populate cache so ensure_strategy_exists short-circuits
        db = _mock_db()
        EXISTING_STRATEGIES.add("42")
        data = _deal_schema(magic=42)
        # Act
        process_deal(db, data)
        # Assert — query() not called because cache hit prevented the lookup
        db.query.assert_not_called()


# ── process_account ───────────────────────────────────────────────────────────


class TestProcessAccount:
    def test_existing_account_updates_balance_and_margin(self):
        # Arrange — simulate existing account found in DB
        db = _mock_db()
        fake_account = MagicMock(spec=Account)
        db.query.return_value.filter.return_value.first.return_value = fake_account
        data = AccountSchema(login=123, broker="B", balance=9000.0, free_margin=7000.0)
        # Act
        process_account(db, data)
        # Assert — account attributes updated
        assert fake_account.balance == 9000.0
        assert fake_account.free_margin == 7000.0

    def test_unknown_account_triggers_ensure_account_exists(self):
        # Arrange — no existing account
        db = _mock_db()
        data = AccountSchema(
            login=456, broker="NewBroker", balance=5000.0, free_margin=4000.0
        )
        # Act
        with patch.object(server_module, "ensure_account_exists") as mock_ensure:
            process_account(db, data)
        # Assert
        mock_ensure.assert_called_once_with(db, "456", "NewBroker")


class TestProcessStrategyRuntime:
    def test_magic_zero_returns_without_touching_db(self):
        db = _mock_db()
        process_strategy_runtime(db, _runtime_schema(magic=0))
        db.execute.assert_not_called()
        db.query.assert_not_called()

    def test_valid_runtime_snapshot_calls_db_execute(self):
        db = _mock_db()
        process_strategy_runtime(db, _runtime_schema())
        db.execute.assert_called_once()

    def test_valid_runtime_snapshot_adds_strategy_to_cache(self):
        db = _mock_db()
        process_strategy_runtime(db, _runtime_schema(magic=314))
        assert "314" in EXISTING_STRATEGIES


# ── ensure_strategy_exists ────────────────────────────────────────────────────


class TestEnsureStrategyExists:
    """
    These tests use the real SQLite session (from conftest) so ORM behavior
    (db.add, db.begin_nested, etc.) is exercised against a real database.
    """

    def test_creates_strategy_when_not_in_db(self, db_session):
        # Arrange — strategy "555" does not exist
        assert db_session.get(Strategy, "555") is None
        # Act
        ensure_strategy_exists(db_session, "555", symbol="USDJPY")
        db_session.flush()
        # Assert — strategy row created
        s = db_session.get(Strategy, "555")
        assert s is not None
        assert s.symbol == "USDJPY"

    def test_created_strategy_added_to_cache(self, db_session):
        ensure_strategy_exists(db_session, "556")
        assert "556" in EXISTING_STRATEGIES

    def test_existing_strategy_not_duplicated(self, db_session):
        # Arrange — insert strategy first
        s = Strategy(id="777", name="Pre-existing")
        db_session.add(s)
        db_session.flush()
        # Act — call again
        ensure_strategy_exists(db_session, "777")
        db_session.flush()
        # Assert — still only one row
        count = db_session.query(Strategy).filter(Strategy.id == "777").count()
        assert count == 1

    def test_cache_hit_skips_all_db_interaction(self):
        # Arrange — strategy already in cache
        EXISTING_STRATEGIES.add("888")
        db = _mock_db()
        # Act
        ensure_strategy_exists(db, "888")
        # Assert — no DB query made
        db.query.assert_not_called()

    def test_new_strategy_has_live_false_and_real_account_false(self, db_session):
        # Business rule: auto-discovered strategies start in incubation mode
        ensure_strategy_exists(db_session, "999")
        db_session.flush()
        s = db_session.get(Strategy, "999")
        assert s.live is False
        assert s.real_account is False
