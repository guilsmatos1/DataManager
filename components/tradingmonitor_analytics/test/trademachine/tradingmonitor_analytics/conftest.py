"""
Shared fixtures for the TradingMonitor test suite.

Hierarchy:
  Unit tests   — no fixtures needed (pure functions / Pydantic models)
  Service tests — use `db_session` (SQLite in-memory) + `test_client` (FastAPI)
  E2E tests     — use `pg_session` (real PostgreSQL, skipped if unavailable)
"""

import os

# Set required env vars before any app module is imported (Settings is module-level).
os.environ["API_KEY"] = "test-api-key-pytest"
os.environ["DATABASE_URL"] = (
    "postgresql://postgres:password@localhost:5433/trademachine.tradingmonitor_test"
)

# Protection: never run tests against the main database
_db_url = os.environ.get("DATABASE_URL", "")
if "trademachine.tradingmonitor_test" not in _db_url and ":memory:" not in _db_url:
    raise RuntimeError(
        f"CRITICAL: Tests are attempting to run against a potentially production database: {_db_url}. "
        "Please set DATABASE_URL to a test database (e.g. containing 'trademachine.tradingmonitor_test') "
        "or use the default pytest configuration."
    )

from datetime import UTC, datetime  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from trademachine.tradingmonitor_storage.db.models import (  # noqa: E402
    Account,
    Base,
    Deal,
    DealType,
    Strategy,
)


# ── SQLite compat: JSONB → JSON ───────────────────────────────────────────────
# PostgreSQL's JSONB type is not understood by SQLite's DDL compiler.
# This patch makes SQLite treat it identically to JSON (test-only shim).
def _patch_sqlite_jsonb():
    from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler

    if not hasattr(SQLiteTypeCompiler, "visit_JSONB"):
        SQLiteTypeCompiler.visit_JSONB = SQLiteTypeCompiler.visit_JSON  # type: ignore[attr-defined]


# ── SQLite compat: BigInteger → INTEGER ───────────────────────────────────────
# SQLite only auto-increments columns whose DDL type is exactly INTEGER (its
# ROWID alias).  BigInteger compiles to BIGINT which SQLite does not treat as
# a ROWID, so primary-key autoincrement silently breaks.  This shim makes
# BigInteger compile to INTEGER in SQLite — safe for testing because SQLite
# stores all integers as up to 8-byte signed values regardless of type name.
def _patch_sqlite_biginteger():
    from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler

    if not hasattr(SQLiteTypeCompiler, "_orig_visit_BIGINT"):
        SQLiteTypeCompiler._orig_visit_BIGINT = SQLiteTypeCompiler.visit_BIGINT  # type: ignore[attr-defined]
        SQLiteTypeCompiler.visit_BIGINT = lambda self, *_, **__: "INTEGER"  # type: ignore[method-assign]


# ── SQLite compat: Composite PK with Autoincrement ────────────────────────────
# TimescaleDB requires the partition column (timestamp) to be part of the PK.
# SQLite does not support autoincrement on a composite PK. For in-memory tests,
# we strip the timestamp from the PrimaryKeyConstraint on tables that have an
# autoincrement integer ID.
def _patch_sqlite_composite_pk():
    from sqlalchemy.schema import PrimaryKeyConstraint

    for table_name in ["deals"]:
        if table_name in Base.metadata.tables:
            table = Base.metadata.tables[table_name]

            # Remove timestamp from the column's own primary_key flag
            if "timestamp" in table.columns:
                table.columns["timestamp"].primary_key = False

            # Rebuild the table's PrimaryKeyConstraint to only include 'id'
            pk_constraint = None
            for constraint in table.constraints:
                if isinstance(constraint, PrimaryKeyConstraint):
                    pk_constraint = constraint
                    break

            if pk_constraint is not None:
                table.constraints.remove(pk_constraint)
                new_pk = PrimaryKeyConstraint(table.columns["id"])
                table.append_constraint(new_pk)


_patch_sqlite_jsonb()
_patch_sqlite_biginteger()
_patch_sqlite_composite_pk()


# ── Cache isolation ───────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clear_ingestion_caches():
    """Clear processor in-memory caches before/after each test to prevent cross-test pollution."""
    import trademachine.tradingmonitor_ingestion.ingestion.processors as _proc

    _proc.EXISTING_STRATEGIES.clear()
    _proc.EXISTING_ACCOUNTS.clear()
    _proc.EXISTING_SYMBOLS.clear()
    _proc._active_backtests.clear()
    yield
    _proc.EXISTING_STRATEGIES.clear()
    _proc.EXISTING_ACCOUNTS.clear()
    _proc.EXISTING_SYMBOLS.clear()
    _proc._active_backtests.clear()


# ── SQLite fixtures ───────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def sqlite_engine():
    """Create all ORM tables in an in-memory SQLite DB once per test session."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if (
                column.primary_key
                and getattr(column, "autoincrement", False) is True
                and len(table.primary_key.columns) > 1
            ):
                column.autoincrement = False
                column.info["was_autoincrement"] = True

    Base.metadata.create_all(bind=engine)

    for table in Base.metadata.tables.values():
        for column in table.columns:
            if column.info.get("was_autoincrement"):
                column.autoincrement = True
                del column.info["was_autoincrement"]

    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db_session(sqlite_engine):
    """
    Yield a transactional DB session that is rolled back after each test.
    This ensures complete isolation between tests without recreating the schema.
    """
    connection = sqlite_engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


# ── Seed helpers ──────────────────────────────────────────────────────────────


@pytest.fixture()
def seed_strategy(db_session):
    """
    Factory fixture: returns a callable that inserts a Strategy row.
    Usage: strategy = seed_strategy(id="100", name="Alpha")
    """

    def _make(
        id: str = "100",
        name: str = "Test Strategy",
        symbol: str = "EURUSD",
        live: bool = False,
        real_account: bool = False,
    ):
        s = Strategy(
            id=id, name=name, symbol=symbol, live=live, real_account=real_account
        )
        db_session.add(s)
        db_session.flush()
        return s

    return _make


@pytest.fixture()
def seed_account(db_session):
    """Factory fixture: inserts an Account row."""

    def _make(id: str = "999", name: str = "Test Account", broker: str = "Test Broker"):
        a = Account(id=id, name=name, broker=broker)
        db_session.add(a)
        db_session.flush()
        return a

    return _make


@pytest.fixture()
def seed_deal(db_session, seed_strategy):
    """Factory fixture: inserts a Deal row for an existing strategy."""

    def _make(
        strategy_id: str = "100",
        ticket: int = 1,
        profit: float = 100.0,
        commission: float = -1.0,
        swap: float = 0.0,
        deal_type: DealType = DealType.BUY,
    ):
        # Ensure strategy exists
        if not db_session.get(Strategy, strategy_id):
            seed_strategy(id=strategy_id)
        d = Deal(
            timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            ticket=ticket,
            strategy_id=strategy_id,
            symbol="EURUSD",
            type=deal_type,
            volume=0.1,
            price=1.0800,
            profit=profit,
            commission=commission,
            swap=swap,
        )
        db_session.add(d)
        db_session.flush()
        return d

    return _make


# ── PostgreSQL E2E fixture ────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def pg_engine():
    """
    Connect to the real PostgreSQL/TimescaleDB instance.
    Tests using this fixture are skipped if the DB is unavailable.
    """
    import os

    from sqlalchemy.exc import OperationalError

    url = os.environ.get(
        "DATABASE_URL",
        "postgresql://postgres:password@localhost:5432/trademachine.tradingmonitor_test",
    )
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            conn.execute(__import__("sqlalchemy").text("SELECT 1"))
    except OperationalError:
        pytest.skip("PostgreSQL not available — skipping integration test")

    Base.metadata.create_all(bind=engine)
    yield engine
    # Do NOT drop tables — leave data for inspection; use a dedicated test DB.


@pytest.fixture()
def pg_session(pg_engine):
    """Session against the real PostgreSQL DB. Allows actual commits so E2E clients can see the data."""
    Session = sessionmaker(bind=pg_engine)
    session = Session()

    # Clean up all tables before the test runs
    session.execute(
        __import__("sqlalchemy").text("""
        TRUNCATE TABLE deals, equity_curve, portfolio_strategy, portfolios, strategies, accounts, backtests, backtest_deals, backtest_equity, ingestion_errors CASCADE;
    """)
    )
    session.commit()

    yield session

    session.close()
