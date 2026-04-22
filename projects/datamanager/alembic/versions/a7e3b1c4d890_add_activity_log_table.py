"""Add activity_log table

Revision ID: a7e3b1c4d890
Revises: c3f1a8b2d5e0
Create Date: 2026-04-21 23:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7e3b1c4d890"
down_revision: str | Sequence[str] | None = "c3f1a8b2d5e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "activity_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "timestamp", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("action", sa.String, nullable=False),
        sa.Column("target", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("message", sa.String, nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_table("activity_log")
