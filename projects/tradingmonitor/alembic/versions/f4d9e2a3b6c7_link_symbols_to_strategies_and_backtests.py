"""link_symbols_to_strategies_and_backtests

Revision ID: f4d9e2a3b6c7
Revises: f3c8d1e2a4b5
Create Date: 2026-04-10 00:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4d9e2a3b6c7"
down_revision: str | None = "f3c8d1e2a4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO symbols (name)
        SELECT DISTINCT symbol
        FROM strategies
        WHERE symbol IS NOT NULL AND btrim(symbol) <> ''
        ON CONFLICT (name) DO NOTHING;
        """
    )
    op.execute(
        """
        INSERT INTO symbols (name)
        SELECT DISTINCT symbol
        FROM backtests
        WHERE symbol IS NOT NULL AND btrim(symbol) <> ''
        ON CONFLICT (name) DO NOTHING;
        """
    )

    op.add_column("strategies", sa.Column("symbol_id", sa.Integer(), nullable=True))
    op.add_column("backtests", sa.Column("symbol_id", sa.Integer(), nullable=True))

    op.execute(
        """
        UPDATE strategies
        SET symbol_id = symbols.id
        FROM symbols
        WHERE strategies.symbol = symbols.name
          AND strategies.symbol_id IS NULL;
        """
    )
    op.execute(
        """
        UPDATE backtests
        SET symbol_id = symbols.id
        FROM symbols
        WHERE backtests.symbol = symbols.name
          AND backtests.symbol_id IS NULL;
        """
    )

    op.create_foreign_key(
        "fk_strategies_symbol_id",
        "strategies",
        "symbols",
        ["symbol_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_backtests_symbol_id",
        "backtests",
        "symbols",
        ["symbol_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("fk_backtests_symbol_id", "backtests", type_="foreignkey")
    op.drop_constraint("fk_strategies_symbol_id", "strategies", type_="foreignkey")
    op.drop_column("backtests", "symbol_id")
    op.drop_column("strategies", "symbol_id")
