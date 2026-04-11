"""rebalance_query_indexes

Revision ID: f6a7b8c9d0e1
Revises: f5e1a2b3c4d5
Create Date: 2026-04-10 01:10:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "f5e1a2b3c4d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(
        "ix_benchmark_prices_benchmark_timestamp",
        table_name="benchmark_prices",
    )
    op.drop_index("ix_backtest_deals_id_ts", table_name="backtest_deals")
    op.drop_index("ix_backtest_equity_id_ts", table_name="backtest_equity")

    op.create_index(
        "ix_portfolio_strategy_strategy_id",
        "portfolio_strategy",
        ["strategy_id"],
        unique=False,
    )
    op.create_index(
        "ix_strategies_account_id",
        "strategies",
        ["account_id"],
        unique=False,
    )
    op.create_index(
        "ix_strategies_symbol_id",
        "strategies",
        ["symbol_id"],
        unique=False,
    )
    op.create_index(
        "ix_backtests_strategy_created_at",
        "backtests",
        ["strategy_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_backtests_symbol_id",
        "backtests",
        ["symbol_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_backtests_symbol_id", table_name="backtests")
    op.drop_index("ix_backtests_strategy_created_at", table_name="backtests")
    op.drop_index("ix_strategies_symbol_id", table_name="strategies")
    op.drop_index("ix_strategies_account_id", table_name="strategies")
    op.drop_index(
        "ix_portfolio_strategy_strategy_id",
        table_name="portfolio_strategy",
    )

    op.create_index(
        "ix_backtest_equity_id_ts",
        "backtest_equity",
        ["backtest_id", "timestamp"],
        unique=False,
    )
    op.create_index(
        "ix_backtest_deals_id_ts",
        "backtest_deals",
        ["backtest_id", "timestamp"],
        unique=False,
    )
    op.create_index(
        "ix_benchmark_prices_benchmark_timestamp",
        "benchmark_prices",
        ["benchmark_id", "timestamp"],
        unique=False,
    )
