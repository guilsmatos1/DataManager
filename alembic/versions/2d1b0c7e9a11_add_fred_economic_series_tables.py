"""Add FRED economic series tables

Revision ID: 2d1b0c7e9a11
Revises: 8f52d9a582ce
Create Date: 2026-04-02

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2d1b0c7e9a11"
down_revision: str | Sequence[str] | None = "8f52d9a582ce"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "economic_series",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("series_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("native_frequency", sa.String(), nullable=True),
        sa.Column("units", sa.String(), nullable=True),
        sa.Column("seasonal_adjustment", sa.String(), nullable=True),
        sa.Column("observation_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observation_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id", "series_id", name="uq_economic_series_source_series"
        ),
    )
    op.create_index(
        "ix_economic_series_source_series",
        "economic_series",
        ["source_id", "series_id"],
        unique=False,
    )

    op.create_table(
        "economic_observations",
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("series_ref_id", sa.Integer(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["series_ref_id"],
            ["economic_series.id"],
        ),
        sa.PrimaryKeyConstraint("timestamp", "series_ref_id"),
        sa.UniqueConstraint(
            "timestamp", "series_ref_id", name="uq_economic_observation_timestamp"
        ),
    )
    op.create_index(
        op.f("ix_economic_observations_series_ref_id"),
        "economic_observations",
        ["series_ref_id"],
        unique=False,
    )
    op.execute(
        "SELECT create_hypertable('economic_observations', by_range('timestamp'));"
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_economic_observations_series_ref_id"),
        table_name="economic_observations",
    )
    op.drop_table("economic_observations")
    op.drop_index("ix_economic_series_source_series", table_name="economic_series")
    op.drop_table("economic_series")
