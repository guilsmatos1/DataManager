"""Add continuous aggregates

Revision ID: 8f52d9a582ce
Revises: ab1af04ad4c3
Create Date: 2026-03-25 22:05:57.728681

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "8f52d9a582ce"
down_revision: str | Sequence[str] | None = "ab1af04ad4c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Continuous aggregates are now created on demand via the resample command.
    pass


def downgrade() -> None:
    pass
