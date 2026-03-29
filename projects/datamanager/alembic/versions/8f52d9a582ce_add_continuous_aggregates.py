"""Add continuous aggregates

Revision ID: 8f52d9a582ce
Revises: ab1af04ad4c3
Create Date: 2026-03-25 22:05:57.728681

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8f52d9a582ce"
down_revision: str | Sequence[str] | None = "ab1af04ad4c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    timeframes = [
        ("m5", "5 minutes"),
        ("m15", "15 minutes"),
        ("h1", "1 hour"),
        ("h4", "4 hours"),
        ("d1", "1 day"),
    ]

    for tf_name, interval in timeframes:
        # Create continuous aggregate for each timeframe
        query = f"""
            CREATE MATERIALIZED VIEW ohlcv_{tf_name}
            WITH (timescaledb.continuous) AS
            SELECT
                time_bucket('{interval}', timestamp) AS timestamp,
                asset_id,
                first(open, timestamp) AS open,
                max(high) AS high,
                min(low) AS low,
                last(close, timestamp) AS close,
                sum(volume) AS volume
            FROM ohlcv_m1
            GROUP BY time_bucket('{interval}', timestamp), asset_id
            WITH NO DATA;
        """  # noqa: S608
        op.execute(query)


def downgrade() -> None:
    timeframes = ["d1", "h4", "h1", "m15", "m5"]
    for tf_name in timeframes:
        op.execute(f"DROP MATERIALIZED VIEW IF EXISTS ohlcv_{tf_name};")
