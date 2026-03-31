"""add_open_profit_to_runtime_snapshots

Revision ID: a7b8c9d0e1f2
Revises: f1a0c9d2e3b4
Create Date: 2026-03-29 00:00:01.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: str | None = "f1a0c9d2e3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "strategy_runtime_snapshots",
        sa.Column(
            "open_profit",
            sa.Numeric(precision=18, scale=8),
            nullable=False,
            server_default="0",
        ),
    )
    op.alter_column("strategy_runtime_snapshots", "open_profit", server_default=None)


def downgrade() -> None:
    op.drop_column("strategy_runtime_snapshots", "open_profit")
