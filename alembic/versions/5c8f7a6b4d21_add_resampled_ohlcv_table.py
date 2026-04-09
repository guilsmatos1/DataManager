"""Add persisted resampled OHLCV table

Revision ID: 5c8f7a6b4d21
Revises: 2d1b0c7e9a11
Create Date: 2026-04-08

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "5c8f7a6b4d21"
down_revision: str | Sequence[str] | None = "2d1b0c7e9a11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ohlcv_resampled replaced by on-demand TimescaleDB continuous aggregates.
    pass


def downgrade() -> None:
    pass
