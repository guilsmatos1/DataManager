"""add_strategy_equity_continuous_aggregates

Create TimescaleDB continuous aggregates for per-strategy equity on hourly and
daily buckets. These views are intended to accelerate portfolio equity queries
that currently load raw equity_curve rows and align them in Python.

Revision ID: e4f5a6b7c8d9
Revises: d6e7f8a9b0c1
Create Date: 2026-04-03 09:30:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e4f5a6b7c8d9"
down_revision: str | Sequence[str] | None = "d6e7f8a9b0c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE MATERIALIZED VIEW strategy_equity_hourly_last
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket('1 hour', timestamp) AS bucket,
            strategy_id,
            last(equity, timestamp) AS equity
        FROM equity_curve
        GROUP BY time_bucket('1 hour', timestamp), strategy_id
        WITH NO DATA;
        """
    )
    op.execute(
        """
        ALTER MATERIALIZED VIEW strategy_equity_hourly_last
        SET (timescaledb.materialized_only = false);
        """
    )
    op.execute(
        """
        SELECT add_continuous_aggregate_policy(
            'strategy_equity_hourly_last',
            start_offset => INTERVAL '30 days',
            end_offset => INTERVAL '5 minutes',
            schedule_interval => INTERVAL '5 minutes'
        );
        """
    )

    op.execute(
        """
        CREATE MATERIALIZED VIEW strategy_equity_daily_last
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket('1 day', timestamp) AS bucket,
            strategy_id,
            last(equity, timestamp) AS equity
        FROM equity_curve
        GROUP BY time_bucket('1 day', timestamp), strategy_id
        WITH NO DATA;
        """
    )
    op.execute(
        """
        ALTER MATERIALIZED VIEW strategy_equity_daily_last
        SET (timescaledb.materialized_only = false);
        """
    )
    op.execute(
        """
        SELECT add_continuous_aggregate_policy(
            'strategy_equity_daily_last',
            start_offset => INTERVAL '365 days',
            end_offset => INTERVAL '5 minutes',
            schedule_interval => INTERVAL '15 minutes'
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS strategy_equity_daily_last CASCADE;")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS strategy_equity_hourly_last CASCADE;")
