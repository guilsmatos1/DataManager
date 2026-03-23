"""
Extended service-layer tests for src/ingestion/tcp_server.py.

Covers cases not already handled by test_processors.py:
  - process_deal: on_conflict_do_nothing (duplicate ticket), strategy FK missing
  - process_equity: magic=0 skipped vs valid magic inserts
  - process_account: existing account updated, new account triggers ensure_account_exists
  - ensure_strategy_exists: cache hit, DB hit, neither (creates row)
  - invalidate_cache: removes entries from in-memory caches
"""

from unittest.mock import MagicMock, patch

import pytest
import tradingmonitor.ingestion.tcp_server as server_module
from tradingmonitor.db.models import Account, Strategy
from tradingmonitor.ingestion.schemas import AccountSchema, DealSchema, EquitySchema
from tradingmonitor.ingestion.tcp_server import (
    EXISTING_ACCOUNTS,
    EXISTING_STRATEGIES,
    EXISTING_SYMBOLS,
    ensure_strategy_exists,
    invalidate_cache,
    process_account,
    process_deal,
    process_equity,
)

_VALID_TS = 1_700_000_000


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_caches():
    """Ensure in-memory caches are clean before and after every test."""
    EXISTING_STRATEGIES.clear()
    EXISTING_ACCOUNTS.clear()
    EXISTING_SYMBOLS.clear()
    yield
    EXISTING_STRATEGIES.clear()
    EXISTING_ACCOUNTS.clear()
    EXISTING_SYMBOLS.clear()


def _mock_db():
    db = MagicMock()
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
    base = dict(time=_VALID_TS, magic=42, balance=10_000.0, equity=10_050.0)
    base.update(overrides)
    return EquitySchema(**base)


def _account_schema(**overrides) -> AccountSchema:
    base = dict(login=123, broker="Broker", balance=5_000.0, free_margin=4_500.0)
    base.update(overrides)
    return AccountSchema(**base)


# ── process_deal ─────────────────────────────────────────────────────────────


class TestProcessDealExtended:
    def test_normal_insertion_calls_db_execute(self):
        """process_deal must call db.execute() to run the INSERT statement."""
        db = _mock_db()
        data = _deal_schema()
        EXISTING_SYMBOLS.add(data.symbol)
        process_deal(db, data)
        db.execute.assert_called_once()

    def test_no_explicit_commit_inside_process_deal(self):
        """Commit must NOT be called inside process_deal; the caller owns it."""
        db = _mock_db()
        data = _deal_schema()
        EXISTING_SYMBOLS.add(data.symbol)
        process_deal(db, data)
        db.commit.assert_not_called()

    def test_strategy_added_to_cache_after_deal(self):
        """After processing, the strategy_id must appear in EXISTING_STRATEGIES."""
        db = _mock_db()
        data = _deal_schema(magic=77)
        EXISTING_SYMBOLS.add(data.symbol)
        process_deal(db, data)
        assert "77" in EXISTING_STRATEGIES

    def test_cached_strategy_skips_db_query(self):
        """When strategy_id is already cached, no DB query should be issued."""
        db = _mock_db()
        EXISTING_STRATEGIES.add("42")
        data = _deal_schema(magic=42)
        EXISTING_SYMBOLS.add(data.symbol)
        process_deal(db, data)
        db.query.assert_not_called()

    def test_on_conflict_do_nothing_does_not_raise_on_duplicate(self):
        """pg_insert with on_conflict_do_nothing must not raise on duplicate.

        We simulate the real behaviour by checking that db.execute() is still
        called (the statement is built and handed to the session) — the
        conflict is handled by PostgreSQL, not by Python code.
        """
        db = _mock_db()
        data = _deal_schema(ticket=999)
        EXISTING_SYMBOLS.add(data.symbol)
        # First insert
        process_deal(db, data)
        assert db.execute.call_count == 1
        # Second insert with same ticket — still calls execute; DB silently ignores it
        process_deal(db, data)
        assert db.execute.call_count == 2

    def test_missing_strategy_in_db_creates_new_strategy(self, db_session):
        """When strategy does not exist in DB, ensure_strategy_exists creates it."""
        assert db_session.get(Strategy, "101") is None
        data = _deal_schema(magic=101)
        # process_deal calls ensure_strategy_exists internally
        process_deal(db_session, data)
        db_session.flush()
        s = db_session.get(Strategy, "101")
        assert s is not None


# ── process_equity ────────────────────────────────────────────────────────────


class TestProcessEquityExtended:
    def test_magic_zero_skipped_no_db_interaction(self):
        """magic=0 is account-level; must not touch DB at all."""
        db = _mock_db()
        process_equity(db, _equity_schema(magic=0))
        db.execute.assert_not_called()
        db.query.assert_not_called()

    def test_magic_zero_not_added_to_cache(self):
        db = _mock_db()
        process_equity(db, _equity_schema(magic=0))
        assert "0" not in EXISTING_STRATEGIES

    def test_valid_magic_calls_db_execute(self):
        db = _mock_db()
        process_equity(db, _equity_schema(magic=55))
        db.execute.assert_called_once()

    def test_no_commit_inside_process_equity(self):
        """Commit responsibility belongs to handle_client, not process_equity."""
        db = _mock_db()
        process_equity(db, _equity_schema(magic=55))
        db.commit.assert_not_called()

    def test_valid_magic_adds_strategy_to_cache(self):
        db = _mock_db()
        process_equity(db, _equity_schema(magic=88))
        assert "88" in EXISTING_STRATEGIES


# ── process_account ───────────────────────────────────────────────────────────


class TestProcessAccountExtended:
    def test_existing_account_fields_updated(self):
        """When account exists, balance/free_margin/deposits/withdrawals are updated."""
        db = _mock_db()
        fake_acc = MagicMock(spec=Account)
        db.query.return_value.filter.return_value.first.return_value = fake_acc
        data = _account_schema(
            balance=9_000.0, free_margin=7_000.0, deposits=9_000.0, withdrawals=0.0
        )
        process_account(db, data)
        assert fake_acc.balance == 9_000.0
        assert fake_acc.free_margin == 7_000.0
        assert fake_acc.total_deposits == 9_000.0
        assert fake_acc.total_withdrawals == 0.0

    def test_existing_account_does_not_call_ensure_account_exists(self):
        """If account row already exists, ensure_account_exists must NOT be called."""
        db = _mock_db()
        db.query.return_value.filter.return_value.first.return_value = MagicMock(spec=Account)
        with patch.object(server_module, "ensure_account_exists") as mock_ensure:
            process_account(db, _account_schema())
        mock_ensure.assert_not_called()

    def test_new_account_triggers_ensure_account_exists(self):
        """When account is not found in DB, ensure_account_exists must be called."""
        db = _mock_db()  # first() returns None → account not found
        data = _account_schema(login=456, broker="NewBroker")
        with patch.object(server_module, "ensure_account_exists") as mock_ensure:
            process_account(db, data)
        mock_ensure.assert_called_once_with(db, "456", "NewBroker")

    def test_no_commit_inside_process_account(self):
        """process_account must NOT call db.commit(); the caller (handle_client) owns it."""
        db = _mock_db()
        db.query.return_value.filter.return_value.first.return_value = MagicMock(spec=Account)
        process_account(db, _account_schema())
        db.commit.assert_not_called()


# ── ensure_strategy_exists ────────────────────────────────────────────────────


class TestEnsureStrategyExistsExtended:
    def test_cache_hit_no_db_query(self):
        """If strategy_id is in cache, no DB access should occur."""
        db = _mock_db()
        EXISTING_STRATEGIES.add("cached_id")
        ensure_strategy_exists(db, "cached_id")
        db.query.assert_not_called()

    def test_db_hit_adds_to_cache(self, db_session):
        """When strategy already exists in DB but not in cache, it is cached."""
        s = Strategy(id="db_only", name="Existing")
        db_session.add(s)
        db_session.flush()
        assert "db_only" not in EXISTING_STRATEGIES
        ensure_strategy_exists(db_session, "db_only")
        assert "db_only" in EXISTING_STRATEGIES

    def test_new_strategy_created_in_db(self, db_session):
        """When strategy is absent from both cache and DB, a new row is inserted."""
        assert db_session.get(Strategy, "brand_new") is None
        ensure_strategy_exists(db_session, "brand_new", symbol="GBPUSD")
        db_session.flush()
        s = db_session.get(Strategy, "brand_new")
        assert s is not None
        assert s.symbol == "GBPUSD"

    def test_new_strategy_has_live_false(self, db_session):
        ensure_strategy_exists(db_session, "new_live_check")
        db_session.flush()
        s = db_session.get(Strategy, "new_live_check")
        assert s.live is False
        assert s.real_account is False

    def test_existing_strategy_not_duplicated(self, db_session):
        s = Strategy(id="dup_check", name="Pre-existing")
        db_session.add(s)
        db_session.flush()
        # Call twice — must remain a single row
        ensure_strategy_exists(db_session, "dup_check")
        ensure_strategy_exists(db_session, "dup_check")
        count = db_session.query(Strategy).filter(Strategy.id == "dup_check").count()
        assert count == 1


# ── invalidate_cache ──────────────────────────────────────────────────────────


class TestInvalidateCache:
    def test_invalidate_strategy(self):
        EXISTING_STRATEGIES.add("stale_strategy")
        invalidate_cache(strategy_id="stale_strategy")
        assert "stale_strategy" not in EXISTING_STRATEGIES

    def test_invalidate_account(self):
        EXISTING_ACCOUNTS.add("stale_account")
        invalidate_cache(account_id="stale_account")
        assert "stale_account" not in EXISTING_ACCOUNTS

    def test_invalidate_both(self):
        EXISTING_STRATEGIES.add("s1")
        EXISTING_ACCOUNTS.add("a1")
        invalidate_cache(strategy_id="s1", account_id="a1")
        assert "s1" not in EXISTING_STRATEGIES
        assert "a1" not in EXISTING_ACCOUNTS

    def test_invalidate_nonexistent_is_safe(self):
        """Discarding a non-existent key must not raise."""
        invalidate_cache(strategy_id="does_not_exist", account_id="also_missing")

    def test_invalidate_none_args_is_noop(self):
        """Calling with both None args must not touch either cache."""
        EXISTING_STRATEGIES.add("keep_me")
        invalidate_cache()
        assert "keep_me" in EXISTING_STRATEGIES
