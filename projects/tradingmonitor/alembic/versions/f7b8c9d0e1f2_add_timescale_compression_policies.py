"""add_timescale_compression_policies

Enable TimescaleDB compression on the high-volume hypertables and retain raw
equity telemetry for a bounded window. `deals` remain indefinitely available,
while `equity_curve` is compressed aggressively and retained for two years to
control storage growth.

Revision ID: f7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-04-10 02:05:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f7b8c9d0e1f2"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE deals
        SET (
            timescaledb.compress = true,
            timescaledb.compress_segmentby = 'strategy_id',
            timescaledb.compress_orderby = 'timestamp DESC'
        );
        """
    )
    op.execute(
        """
        ALTER TABLE equity_curve
        SET (
            timescaledb.compress = true,
            timescaledb.compress_segmentby = 'strategy_id',
            timescaledb.compress_orderby = 'timestamp DESC'
        );
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            PERFORM add_compression_policy('deals', INTERVAL '7 days');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            PERFORM add_compression_policy('equity_curve', INTERVAL '3 days');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            PERFORM add_retention_policy('equity_curve', INTERVAL '2 years');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("SELECT remove_retention_policy('equity_curve', if_exists => TRUE);")
    op.execute("SELECT remove_compression_policy('equity_curve', if_exists => TRUE);")
    op.execute("SELECT remove_compression_policy('deals', if_exists => TRUE);")
    op.execute("ALTER TABLE equity_curve SET (timescaledb.compress = false);")
    op.execute("ALTER TABLE deals SET (timescaledb.compress = false);")
