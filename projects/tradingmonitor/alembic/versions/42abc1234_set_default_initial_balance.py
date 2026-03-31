"""set_default_initial_balance

Revision ID: 42abc1234
Revises: a7b8c9d0e1f2
Create Date: 2026-03-29 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "42abc1234"
down_revision: str | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE strategies SET initial_balance = 100000.0 WHERE initial_balance IS NULL"
        )
    )


def downgrade() -> None:
    pass
