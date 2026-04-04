"""add_strategy_pnl_continuous_aggregates

Create TimescaleDB continuous aggregates for per-strategy P&L on hourly and
daily buckets. These views are intended to accelerate long-range dashboard
queries that currently aggregate raw deals rows in Python or ad-hoc SQL.

Revision ID: d6e7f8a9b0c1
Revises: c1d2e3f4a5b6
Create Date: 2026-04-02 22:30:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d6e7f8a9b0c1"
down_revision: str | Sequence[str] | None = "c1d2e3f4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE MATERIALIZED VIEW strategy_pnl_hourly
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket('1 hour', timestamp) AS bucket,
            strategy_id,
            SUM(profit + commission + swap) AS net_profit,
            COUNT(*) AS trades_count
        FROM deals
        WHERE type IN ('BUY', 'SELL')
        GROUP BY time_bucket('1 hour', timestamp), strategy_id
        WITH NO DATA;
        """
    )
    op.execute(
        """
        ALTER MATERIALIZED VIEW strategy_pnl_hourly
        SET (timescaledb.materialized_only = false);
        """
    )
    op.execute(
        """
        SELECT add_continuous_aggregate_policy(
            'strategy_pnl_hourly',
            start_offset => INTERVAL '30 days',
            end_offset => INTERVAL '5 minutes',
            schedule_interval => INTERVAL '5 minutes'
        );
        """
    )

    op.execute(
        """
        CREATE MATERIALIZED VIEW strategy_pnl_daily
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket('1 day', timestamp) AS bucket,
            strategy_id,
            SUM(profit + commission + swap) AS net_profit,
            COUNT(*) AS trades_count
        FROM deals
        WHERE type IN ('BUY', 'SELL')
        GROUP BY time_bucket('1 day', timestamp), strategy_id
        WITH NO DATA;
        """
    )
    op.execute(
        """
        ALTER MATERIALIZED VIEW strategy_pnl_daily
        SET (timescaledb.materialized_only = false);
        """
    )
    op.execute(
        """
        SELECT add_continuous_aggregate_policy(
            'strategy_pnl_daily',
            start_offset => INTERVAL '365 days',
            end_offset => INTERVAL '5 minutes',
            schedule_interval => INTERVAL '15 minutes'
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS strategy_pnl_daily CASCADE;")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS strategy_pnl_hourly CASCADE;")
