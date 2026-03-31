"""add_benchmarks_tables

Revision ID: c1d2e3f4a5b6
Revises: 42abc1234
Create Date: 2026-03-29 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: str | None = "42abc1234"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "benchmarks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("asset", sa.String(), nullable=False),
        sa.Column("timeframe", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column(
            "is_default", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source",
            "asset",
            "timeframe",
            name="uq_benchmark_source_asset_tf",
        ),
    )
    op.create_table(
        "benchmark_prices",
        sa.Column("benchmark_id", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("close", sa.Numeric(18, 8), nullable=False),
        sa.ForeignKeyConstraint(["benchmark_id"], ["benchmarks.id"]),
        sa.PrimaryKeyConstraint("benchmark_id", "timestamp"),
    )
    op.create_index(
        "ix_benchmark_prices_benchmark_timestamp",
        "benchmark_prices",
        ["benchmark_id", "timestamp"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_benchmark_prices_benchmark_timestamp", table_name="benchmark_prices"
    )
    op.drop_table("benchmark_prices")
    op.drop_table("benchmarks")
