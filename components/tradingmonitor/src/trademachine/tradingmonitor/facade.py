"""TradingMonitor Facade - Clean API for base consumers.

This module provides a unified interface to TradingMonitor core functionality,
decoupling bases (entry points) from internal implementation details.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from .db.repository import (
        AccountRepository,
        BacktestDealRepository,
        BacktestEquityRepository,
        BacktestRepository,
        DealRepository,
        EquityCurveRepository,
        PortfolioRepository,
        StrategyRepository,
        SymbolRepository,
    )


class TradingMonitorFacade:
    """Unified interface to TradingMonitor core functionality.

    This facade aggregates all repository access and high-level operations
    behind a single entry point, reducing import coupling in bases.
    """

    def __init__(self) -> None:
        from .db.repository import (
            AccountRepository,
            BacktestDealRepository,
            BacktestEquityRepository,
            BacktestRepository,
            DealRepository,
            EquityCurveRepository,
            PortfolioRepository,
            StrategyRepository,
            SymbolRepository,
        )

        self.accounts: AccountRepository = AccountRepository()
        self.backtest_deals: BacktestDealRepository = BacktestDealRepository()
        self.backtest_equity: BacktestEquityRepository = BacktestEquityRepository()
        self.backtests: BacktestRepository = BacktestRepository()
        self.deals: DealRepository = DealRepository()
        self.equity: EquityCurveRepository = EquityCurveRepository()
        self.portfolios: PortfolioRepository = PortfolioRepository()
        self.strategies: StrategyRepository = StrategyRepository()
        self.symbols: SymbolRepository = SymbolRepository()

    # ── Strategy operations ────────────────────────────────────────────────────

    def get_strategy(
        self, strategy_id: str, include_account: bool = False
    ) -> dict | None:
        """Get a strategy by ID."""
        return self.strategies.get_by_id(strategy_id, include_account=include_account)

    def get_all_strategies(self, include_account: bool = False) -> list[dict]:
        """Get all strategies."""
        return self.strategies.get_all(include_account=include_account)

    def get_real_strategies(self) -> list[dict]:
        """Get all strategies with real_account=True."""
        return self.strategies.get_real_strategies()

    def get_strategy_deals_df(
        self, strategy_id: str, since: datetime | None = None
    ) -> pd.DataFrame:
        """Get deals DataFrame for a strategy (for metrics calculations)."""
        from .metrics.repository import get_strategy_deals

        return get_strategy_deals(strategy_id, since=since)

    def get_strategy_equity_df(self, strategy_id: str) -> pd.DataFrame:
        """Get equity curve DataFrame for a strategy."""
        from .metrics.repository import get_strategy_equity_curve

        return get_strategy_equity_curve(strategy_id)

    def get_strategy_metrics(self, strategy_id: str) -> dict:
        """Calculate metrics for a strategy."""
        from .metrics.calculator import calculate_metrics

        return calculate_metrics(strategy_id)

    def get_strategy_metrics_from_df(
        self, deals_df: pd.DataFrame, equity_df: pd.DataFrame, advanced: bool = False
    ) -> dict:
        """Calculate metrics from DataFrames."""
        from .metrics.calculator import calculate_metrics_from_df

        return calculate_metrics_from_df(deals_df, equity_df, advanced=advanced)

    @staticmethod
    def _build_trade_stats(by_hour_data: list[dict], by_dow_data: list[dict]) -> dict:
        """Build by_hour and by_dow statistics from raw DB data."""
        by_hour = [{"hour": h, "count": 0, "net_profit": 0.0} for h in range(24)]
        for r in by_hour_data:
            h = r["hour"]
            by_hour[h] = {
                "hour": h,
                "count": int(r["count"]),
                "net_profit": round(float(r["net_profit"] or 0), 2),
            }

        DOW_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        by_dow = [
            {"dow": i + 1, "label": DOW_LABELS[i], "count": 0, "net_profit": 0.0}
            for i in range(7)
        ]
        for r in by_dow_data:
            d = r["dow"] - 1
            by_dow[d] = {
                "dow": r["dow"],
                "label": DOW_LABELS[d],
                "count": int(r["count"]),
                "net_profit": round(float(r["net_profit"] or 0), 2),
            }

        return {"by_hour": by_hour, "by_dow": by_dow}

    def get_strategy_trade_stats(self, strategy_id: str) -> dict:
        """Get trade statistics (by hour and by day of week) for a strategy."""
        by_hour_data = self.deals.get_trade_stats_by_hour(strategy_id)
        by_dow_data = self.deals.get_trade_stats_by_dow(strategy_id)
        return self._build_trade_stats(by_hour_data, by_dow_data)

    def get_strategy_daily_profit(self, strategy_id: str) -> list[dict]:
        """Get daily profit for a strategy."""
        return self.deals.get_daily_profit(strategy_id=strategy_id)

    # ── Portfolio operations ───────────────────────────────────────────────────

    def get_portfolio(
        self, portfolio_id: int, include_strategies: bool = False
    ) -> dict | None:
        """Get a portfolio by ID."""
        return self.portfolios.get_by_id(
            portfolio_id, include_strategies=include_strategies
        )

    def get_all_portfolios(self, include_strategies: bool = False) -> list[dict]:
        """Get all portfolios."""
        return self.portfolios.get_all(include_strategies=include_strategies)

    def get_portfolio_strategies(self, portfolio_id: int) -> list[dict]:
        """Get strategies belonging to a portfolio."""
        portfolio = self.portfolios.get_by_id(portfolio_id, include_strategies=True)
        if not portfolio:
            return []
        return list(portfolio.get("strategies", []))

    def get_portfolio_strategy_ids(self, portfolio_id: int) -> list[str]:
        """Get strategy IDs belonging to a portfolio."""
        return self.portfolios.get_strategy_ids(portfolio_id)

    def get_portfolio_daily_profit(self, portfolio_id: int) -> list[dict]:
        """Get combined daily profit for all strategies in a portfolio."""
        strategy_ids = self.get_portfolio_strategy_ids(portfolio_id)
        if not strategy_ids:
            return []
        return self.deals.get_daily_profit(strategy_ids=strategy_ids)

    def get_portfolio_metrics(self, strategy_ids: list[str]) -> dict:
        """Calculate aggregated metrics for a portfolio's strategies."""
        from .metrics.calculator import calculate_portfolio_metrics

        return calculate_portfolio_metrics(strategy_ids)

    def get_portfolio_correlation(
        self,
        strategy_ids: list[str],
        period: str = "daily",
        since: datetime | None = None,
    ) -> dict:
        """Calculate correlation matrix for portfolio strategies."""
        from .metrics.calculator import calculate_correlation_matrix

        return calculate_correlation_matrix(strategy_ids, period, since=since)

    def get_portfolio_dynamic_correlation(
        self, strategy_ids: list[str], window_days: int = 30
    ) -> dict:
        """Calculate rolling correlation for portfolio strategies."""
        from .metrics.calculator import calculate_dynamic_correlation

        return calculate_dynamic_correlation(strategy_ids, window_days)

    def get_portfolio_concurrency(
        self, strategy_ids: list[str], since: datetime | None = None
    ) -> dict:
        """Calculate concurrency metrics for portfolio strategies."""
        from .metrics.calculator import calculate_concurrency

        return calculate_concurrency(strategy_ids, since=since)

    # ── Account operations ─────────────────────────────────────────────────────

    def get_all_accounts(self) -> list[dict]:
        """Get all accounts."""
        return self.accounts.get_all()

    def get_account(self, account_id: str) -> dict | None:
        """Get an account by ID."""
        return self.accounts.get_by_id(account_id)

    # ── Backtest operations ────────────────────────────────────────────────────

    def get_backtest(self, backtest_id: int) -> dict | None:
        """Get a backtest by ID."""
        return self.backtests.get_by_id(backtest_id)

    def get_backtests_by_strategy(self, strategy_id: str) -> list[dict]:
        """Get all backtests for a strategy."""
        return self.backtests.get_by_strategy(strategy_id)

    def get_backtest_metrics(self, backtest_id: int) -> dict:
        """Calculate metrics for a backtest."""
        from .metrics.calculator import calculate_metrics_from_df
        from .metrics.repository import get_backtest_deals, get_backtest_equity

        deals_df = get_backtest_deals(backtest_id)
        equity_df = get_backtest_equity(backtest_id)
        return calculate_metrics_from_df(deals_df, equity_df)

    def get_backtest_trade_stats(self, backtest_id: int) -> dict:
        """Get trade statistics for a backtest."""
        by_hour_data = self.backtest_deals.get_trade_stats_by_hour(backtest_id)
        by_dow_data = self.backtest_deals.get_trade_stats_by_dow(backtest_id)
        return self._build_trade_stats(by_hour_data, by_dow_data)

    def get_backtest_daily_profit(self, backtest_id: int) -> list[dict]:
        """Get daily profit for a backtest."""
        return self.backtest_deals.get_daily_profit(backtest_id)

    def get_backtest_deals(
        self, backtest_id: int, page: int = 1, page_size: int = 50
    ) -> tuple[list[dict], int]:
        """Get paginated deals for a backtest."""
        return self.backtest_deals.get_by_backtest(
            backtest_id, page=page, page_size=page_size
        )

    def get_backtest_equity(self, backtest_id: int) -> list[dict]:
        """Get equity curve for a backtest."""
        return self.backtest_equity.get_by_backtest(backtest_id)

    # ── Symbol operations ──────────────────────────────────────────────────────

    def get_all_symbols(self) -> list[dict]:
        """Get all symbols."""
        return self.symbols.get_all()

    # ── Ingestion operations ───────────────────────────────────────────────────

    def get_ingestion_status(self) -> dict:
        """Get current ingestion server status."""
        from .ingestion.tcp_server import get_ingestion_status

        return get_ingestion_status()

    def get_server_uptime_seconds(self) -> float | None:
        """Get TCP server uptime in seconds."""
        from .ingestion.tcp_server import get_server_uptime_seconds

        return get_server_uptime_seconds()

    def invalidate_cache(
        self, strategy_id: str | None = None, account_id: str | None = None
    ) -> None:
        """Invalidate in-memory caches for strategy/account."""
        from .ingestion.tcp_server import invalidate_cache

        invalidate_cache(strategy_id=strategy_id, account_id=account_id)

    def send_kill_command(self, strategy_id: str) -> bool:
        """Send a kill command to an active strategy connection."""
        from .ingestion.tcp_server import send_kill_command

        return send_kill_command(strategy_id)

    # ── MT5 Report parsing ────────────────────────────────────────────────────

    def parse_mt5_report(self, filepath: str) -> tuple[str, pd.DataFrame]:
        """Parse MT5 HTML report and return expert name and deals DataFrame.

        Returns:
            Tuple of (expert_name, deals_df)
        """
        from ..mt5.parser import MT5ReportParser

        parser = MT5ReportParser()
        parser.parse_report(filepath)
        # Get the first expert's deals (single report = single expert)
        expert_names = list(parser.deals_by_expert.keys())
        if not expert_names:
            return "", pd.DataFrame()
        expert_name = expert_names[0]
        return expert_name, parser.deals_by_expert[expert_name]
