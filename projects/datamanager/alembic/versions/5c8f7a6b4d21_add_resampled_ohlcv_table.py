"""Add persisted resampled OHLCV table

Revision ID: 5c8f7a6b4d21
Revises: 2d1b0c7e9a11
Create Date: 2026-04-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5c8f7a6b4d21"
down_revision: str | Sequence[str] | None = "2d1b0c7e9a11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ohlcv_resampled",
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("timeframe", sa.String(), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["assets.id"],
        ),
        sa.PrimaryKeyConstraint("timestamp", "asset_id", "timeframe"),
    )
    op.create_index(
        "ix_ohlcv_resampled_asset_timeframe_timestamp",
        "ohlcv_resampled",
        ["asset_id", "timeframe", "timestamp"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ohlcv_resampled_asset_timeframe_timestamp",
        table_name="ohlcv_resampled",
    )
    op.drop_table("ohlcv_resampled")
