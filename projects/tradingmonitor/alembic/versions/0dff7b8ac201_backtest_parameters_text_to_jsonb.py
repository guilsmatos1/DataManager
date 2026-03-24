"""backtest_parameters_text_to_jsonb

Revision ID: 0dff7b8ac201
Revises: 4bddbcefddce
Create Date: 2026-03-17 11:44:49.028087

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0dff7b8ac201"
down_revision: str | None = "4bddbcefddce"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # TEXT values that are valid JSON are cast; NULL remains NULL.
    op.alter_column(
        "backtests",
        "parameters",
        existing_type=sa.TEXT(),
        type_=postgresql.JSONB(astext_type=sa.Text()),
        existing_nullable=True,
        postgresql_using="CASE WHEN parameters IS NULL THEN NULL ELSE parameters::jsonb END",
    )


def downgrade() -> None:
    op.alter_column(
        "backtests",
        "parameters",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        type_=sa.TEXT(),
        existing_nullable=True,
        postgresql_using="parameters::text",
    )
