"""Drop legacy ohlcv_resampled table

Revision ID: c3f1a8b2d5e0
Revises: 5c8f7a6b4d21
Create Date: 2026-04-09

Rationale: ohlcv_resampled was superseded by TimescaleDB continuous aggregates
(ohlcv_{tf} materialized views created on demand via the resample command).
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3f1a8b2d5e0"
down_revision: str | Sequence[str] | None = "5c8f7a6b4d21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ohlcv_resampled CASCADE")


def downgrade() -> None:
    # The table is permanently discontinued; no restoration on downgrade.
    pass
