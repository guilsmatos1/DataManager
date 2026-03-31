"""add_strategy_runtime_snapshots

Revision ID: f1a0c9d2e3b4
Revises: e3f1a2b4c5d6
Create Date: 2026-03-29 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1a0c9d2e3b4"
down_revision: str | None = "e3f1a2b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "strategy_runtime_snapshots",
        sa.Column("strategy_id", sa.String(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open_trades_count", sa.Integer(), nullable=False),
        sa.Column("pending_orders_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["strategy_id"], ["strategies.id"]),
        sa.PrimaryKeyConstraint("strategy_id"),
    )


def downgrade() -> None:
    op.drop_table("strategy_runtime_snapshots")
