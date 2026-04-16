"""reconcile_settings_and_strategy_drawdown

Revision ID: f2b7c4d5e6f7
Revises: e4f5a6b7c8d9
Create Date: 2026-04-10 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2b7c4d5e6f7"
down_revision: str | None = "e4f5a6b7c8d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = insp.get_table_names()
    if "settings" not in existing_tables:
        op.create_table(
            "settings",
            sa.Column("key", sa.String(length=64), nullable=False),
            sa.Column(
                "value",
                sa.Text(),
                nullable=False,
                server_default=sa.text("''"),
            ),
            sa.PrimaryKeyConstraint("key"),
        )
    existing_cols = [c["name"] for c in insp.get_columns("strategies")]
    if "max_allowed_drawdown" not in existing_cols:
        op.add_column(
            "strategies",
            sa.Column(
                "max_allowed_drawdown",
                sa.Numeric(precision=6, scale=2),
                nullable=True,
            ),
        )


def downgrade() -> None:
    op.drop_column("strategies", "max_allowed_drawdown")
    op.drop_table("settings")
