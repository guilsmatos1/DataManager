import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

# This test requires a real PostgreSQL/TimescaleDB instance.
# It creates a temporary database, runs all migrations, and then drops it.


@pytest.mark.integration
def test_migrations_run_successfully():
    """
    Test that all alembic migrations can be applied to a clean database.
    """
    # 1. Setup temporary database URL
    base_url = os.environ.get("DATABASE_URL")
    if not base_url or ":memory:" in base_url or "sqlite" in base_url:
        pytest.skip("Skipping migration test for sqlite / no real DB")

    # Split the URL to get the base without the DB name
    if "/" in base_url.split("://")[1]:
        root_url, _ = base_url.rsplit("/", 1)
    else:
        root_url = base_url

    test_db_name = "tradingmonitor_migrations_test"
    test_db_url = f"{root_url}/{test_db_name}"

    # 2. Create the test database
    # Connect to 'postgres' default DB to create the new one
    admin_engine = create_engine(f"{root_url}/postgres", isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        # Drop if exists (clean start)
        conn.execute(
            __import__("sqlalchemy").text(f"DROP DATABASE IF EXISTS {test_db_name}")
        )
        conn.execute(__import__("sqlalchemy").text(f"CREATE DATABASE {test_db_name}"))

    try:
        # 3. Create extension before Alembic runs
        engine = create_engine(test_db_url)
        with engine.connect() as conn:
            conn.execute(
                __import__("sqlalchemy").text(
                    "CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;"
                )
            )
            conn.commit()

        # 4. Configure Alembic to use the test database
        root_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..")
        )
        alembic_ini_path = os.path.join(
            root_dir, "projects", "tradingmonitor", "alembic.ini"
        )
        alembic_cfg = Config(alembic_ini_path)
        alembic_cfg.set_main_option("sqlalchemy.url", test_db_url)
        # Also need to point script_location to correct path
        script_loc = os.path.join(root_dir, "projects", "tradingmonitor", "alembic")
        alembic_cfg.set_main_option("script_location", script_loc)

        # 5. Run 'alembic upgrade head'
        # This will fail if any migration is broken
        command.upgrade(alembic_cfg, "head")

        # 6. Verify the schema (optional but good)
        # Check if the 'alembic_version' table exists and has a record
        with engine.connect() as conn:
            result = conn.execute(
                __import__("sqlalchemy").text("SELECT COUNT(*) FROM alembic_version")
            )
            count = result.scalar()
            assert count == 1, (
                "Alembic version table should have exactly one record after upgrade"
            )

            # Also verify one of our core tables exists
            check_table_sql = "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'deals')"
            result = conn.execute(__import__("sqlalchemy").text(check_table_sql))
            assert result.scalar() is True, (
                "Table 'deals' should exist after migrations"
            )

            result = conn.execute(
                __import__("sqlalchemy").text(
                    "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'settings')"
                )
            )
            assert result.scalar() is True, (
                "Table 'settings' should exist after migrations"
            )

            result = conn.execute(
                __import__("sqlalchemy").text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_name = 'strategies'
                          AND column_name = 'max_allowed_drawdown'
                    )
                    """
                )
            )
            assert result.scalar() is True, (
                "Column 'strategies.max_allowed_drawdown' should exist after migrations"
            )

            result = conn.execute(
                __import__("sqlalchemy").text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM information_schema.table_constraints
                        WHERE table_name = 'backtests'
                          AND constraint_name = 'ck_backtests_status_allowed'
                    )
                    """
                )
            )
            assert result.scalar() is True, (
                "Constraint 'ck_backtests_status_allowed' should exist after migrations"
            )

            result = conn.execute(
                __import__("sqlalchemy").text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM pg_indexes
                        WHERE tablename = 'strategies'
                          AND indexname = 'ix_strategies_account_id'
                    )
                    """
                )
            )
            assert result.scalar() is True, (
                "Index 'ix_strategies_account_id' should exist after migrations"
            )

            result = conn.execute(
                __import__("sqlalchemy").text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM pg_indexes
                        WHERE tablename = 'portfolio_strategy'
                          AND indexname = 'ix_portfolio_strategy_strategy_id'
                    )
                    """
                )
            )
            assert result.scalar() is True, (
                "Index 'ix_portfolio_strategy_strategy_id' should exist after migrations"
            )

            result = conn.execute(
                __import__("sqlalchemy").text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM pg_indexes
                        WHERE tablename = 'backtests'
                          AND indexname = 'ix_backtests_strategy_created_at'
                    )
                    """
                )
            )
            assert result.scalar() is True, (
                "Index 'ix_backtests_strategy_created_at' should exist after migrations"
            )

    finally:
        # 6. Cleanup: Drop the test database
        with admin_engine.connect() as conn:
            # We need to terminate connections to the test DB before dropping
            conn.execute(
                __import__("sqlalchemy").text(
                    f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{test_db_name}' AND pid <> pg_backend_pid();"  # noqa: S608
                )
            )
            conn.execute(__import__("sqlalchemy").text(f"DROP DATABASE {test_db_name}"))  # noqa: S608
