"""add_deal_ingestion_keys

Revision ID: f3c8d1e2a4b5
Revises: f2b7c4d5e6f7
Create Date: 2026-04-10 00:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3c8d1e2a4b5"
down_revision: str | None = "f2b7c4d5e6f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "deal_ingestion_keys",
        sa.Column("strategy_id", sa.String(), nullable=False),
        sa.Column("ticket", sa.BigInteger(), nullable=False),
        sa.Column("deal_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["strategies.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("strategy_id", "ticket"),
    )

    op.execute(
        """
        INSERT INTO deal_ingestion_keys (strategy_id, ticket, deal_timestamp)
        SELECT strategy_id, ticket, timestamp
        FROM (
            SELECT
                strategy_id,
                ticket,
                timestamp,
                ROW_NUMBER() OVER (
                    PARTITION BY strategy_id, ticket
                    ORDER BY timestamp DESC, id DESC
                ) AS rn
            FROM deals
        ) ranked
        WHERE rn = 1;
        """
    )

    op.execute(
        """
        DELETE FROM deals d
        USING (
            SELECT
                id,
                timestamp,
                ROW_NUMBER() OVER (
                    PARTITION BY strategy_id, ticket
                    ORDER BY timestamp DESC, id DESC
                ) AS rn
            FROM deals
        ) ranked
        WHERE d.id = ranked.id
          AND d.timestamp = ranked.timestamp
          AND ranked.rn > 1;
        """
    )

    op.drop_constraint("uq_deal_ticket_strategy", "deals", type_="unique")


def downgrade() -> None:
    op.create_unique_constraint(
        "uq_deal_ticket_strategy",
        "deals",
        ["ticket", "strategy_id", "timestamp"],
    )
    op.drop_table("deal_ingestion_keys")
