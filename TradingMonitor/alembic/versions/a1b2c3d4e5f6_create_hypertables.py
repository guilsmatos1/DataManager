"""create_hypertables

Ensures that the deals and equity_curve tables are TimescaleDB hypertables.
Uses IF NOT EXISTS so this migration is safe to run on a database that was
already initialised via init_db() (imperative path).

Revision ID: a1b2c3d4e5f6
Revises: 0dff7b8ac201
Create Date: 2026-03-20 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "0dff7b8ac201"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # create_hypertable() is idempotent when if_not_exists => TRUE, so this
    # migration is safe to apply even if the hypertables already exist (e.g.
    # when the database was previously initialised via init_db()).
    op.execute(
        "SELECT create_hypertable('deals', 'timestamp', if_not_exists => TRUE, migrate_data => TRUE);"
    )
    op.execute(
        "SELECT create_hypertable('equity_curve', 'timestamp', if_not_exists => TRUE, migrate_data => TRUE);"
    )


def downgrade() -> None:
    # TimescaleDB does not provide a simple way to convert a hypertable back to
    # a regular table without data loss, so downgrade is intentionally a no-op.
    pass
