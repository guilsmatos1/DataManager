"""Initial schema and hypertable

Revision ID: ab1af04ad4c3
Revises:
Create Date: 2026-03-25

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ab1af04ad4c3"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create sources table
    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sources_name"), "sources", ["name"], unique=True)

    # 2. Create assets table
    op.create_table(
        "assets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("min_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker", "source_id", name="uq_asset_ticker_source"),
    )
    op.create_index(op.f("ix_assets_ticker"), "assets", ["ticker"], unique=False)

    # 3. Create ohlcv_m1 table
    op.create_table(
        "ohlcv_m1",
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["assets.id"],
        ),
        sa.PrimaryKeyConstraint("timestamp", "asset_id"),
    )

    # 4. Convert ohlcv_m1 to TimescaleDB Hypertable
    op.execute("SELECT create_hypertable('ohlcv_m1', by_range('timestamp'));")


def downgrade() -> None:
    # Drop tables in reverse order
    op.drop_table("ohlcv_m1")
    op.drop_index(op.f("ix_assets_ticker"), table_name="assets")
    op.drop_table("assets")
    op.drop_index(op.f("ix_sources_name"), table_name="sources")
    op.drop_table("sources")
