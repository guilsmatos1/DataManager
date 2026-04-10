"""add_defaults_and_checks

Revision ID: f5e1a2b3c4d5
Revises: f4d9e2a3b6c7
Create Date: 2026-04-10 00:35:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f5e1a2b3c4d5"
down_revision: str | None = "f4d9e2a3b6c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE accounts ALTER COLUMN balance SET DEFAULT 0;")
    op.execute("ALTER TABLE accounts ALTER COLUMN free_margin SET DEFAULT 0;")
    op.execute("ALTER TABLE accounts ALTER COLUMN total_deposits SET DEFAULT 0;")
    op.execute("ALTER TABLE accounts ALTER COLUMN total_withdrawals SET DEFAULT 0;")
    op.execute("ALTER TABLE strategies ALTER COLUMN live SET DEFAULT false;")
    op.execute("ALTER TABLE strategies ALTER COLUMN real_account SET DEFAULT false;")
    op.execute(
        "ALTER TABLE strategy_runtime_snapshots ALTER COLUMN timestamp SET DEFAULT now();"
    )
    op.execute(
        "ALTER TABLE strategy_runtime_snapshots ALTER COLUMN open_profit SET DEFAULT 0;"
    )
    op.execute(
        "ALTER TABLE strategy_runtime_snapshots ALTER COLUMN open_trades_count SET DEFAULT 0;"
    )
    op.execute(
        "ALTER TABLE strategy_runtime_snapshots ALTER COLUMN pending_orders_count SET DEFAULT 0;"
    )
    op.execute("UPDATE backtests SET status = 'pending' WHERE status IS NULL;")
    op.execute(
        """
        UPDATE backtests
        SET status = 'failed'
        WHERE status IS NOT NULL
          AND status NOT IN ('pending', 'running', 'complete', 'failed');
        """
    )
    op.execute("ALTER TABLE backtests ALTER COLUMN status SET DEFAULT 'pending';")

    op.create_check_constraint(
        "ck_backtests_status_allowed",
        "backtests",
        "status IN ('pending', 'running', 'complete', 'failed')",
    )
    op.create_check_constraint(
        "ck_strategies_max_allowed_drawdown_range",
        "strategies",
        "max_allowed_drawdown IS NULL OR max_allowed_drawdown BETWEEN 0 AND 100",
    )
    op.create_check_constraint(
        "ck_runtime_snapshot_counts_nonnegative",
        "strategy_runtime_snapshots",
        "open_trades_count >= 0 AND pending_orders_count >= 0",
    )
    op.create_check_constraint(
        "ck_accounts_cashflow_totals_nonnegative",
        "accounts",
        "total_deposits >= 0 AND total_withdrawals >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_accounts_cashflow_totals_nonnegative",
        "accounts",
        type_="check",
    )
    op.drop_constraint(
        "ck_runtime_snapshot_counts_nonnegative",
        "strategy_runtime_snapshots",
        type_="check",
    )
    op.drop_constraint(
        "ck_strategies_max_allowed_drawdown_range",
        "strategies",
        type_="check",
    )
    op.drop_constraint(
        "ck_backtests_status_allowed",
        "backtests",
        type_="check",
    )

    op.execute("ALTER TABLE backtests ALTER COLUMN status DROP DEFAULT;")
    op.execute(
        "ALTER TABLE strategy_runtime_snapshots ALTER COLUMN timestamp DROP DEFAULT;"
    )
    op.execute(
        "ALTER TABLE strategy_runtime_snapshots ALTER COLUMN open_profit DROP DEFAULT;"
    )
    op.execute(
        "ALTER TABLE strategy_runtime_snapshots ALTER COLUMN open_trades_count DROP DEFAULT;"
    )
    op.execute(
        "ALTER TABLE strategy_runtime_snapshots ALTER COLUMN pending_orders_count DROP DEFAULT;"
    )
    op.execute("ALTER TABLE strategies ALTER COLUMN live DROP DEFAULT;")
    op.execute("ALTER TABLE strategies ALTER COLUMN real_account DROP DEFAULT;")
    op.execute("ALTER TABLE accounts ALTER COLUMN balance DROP DEFAULT;")
    op.execute("ALTER TABLE accounts ALTER COLUMN free_margin DROP DEFAULT;")
    op.execute("ALTER TABLE accounts ALTER COLUMN total_deposits DROP DEFAULT;")
    op.execute("ALTER TABLE accounts ALTER COLUMN total_withdrawals DROP DEFAULT;")
