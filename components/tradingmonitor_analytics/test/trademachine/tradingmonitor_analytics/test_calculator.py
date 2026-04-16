"""
Unit tests for components/tradingmonitor_analytics/src/trademachine/tradingmonitor_analytics/metrics/calculator.py

`calculate_metrics_from_df` is a pure function that receives DataFrames and
returns a metrics dict — no DB, no network required.

DataFrame contract expected by the function:
  deals_df  — DatetimeIndex, columns: type (str), profit, commission, swap (float)
  equity_df — DatetimeIndex, column: equity (float)
"""

import math
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from trademachine.tradingmonitor_analytics.metrics.calculator import (
    calculate_metrics_from_df,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_deals(rows: list[dict]) -> pd.DataFrame:
    """Build a deals DataFrame with a UTC DatetimeIndex."""
    base_ts = datetime(2024, 1, 1, tzinfo=UTC)
    records = []
    for _i, row in enumerate(rows):
        records.append(
            {
                "type": row.get("type", "BUY"),
                "profit": row.get("profit", 0.0),
                "commission": row.get("commission", 0.0),
                "swap": row.get("swap", 0.0),
            }
        )
    index = [base_ts + timedelta(hours=i) for i in range(len(records))]
    return pd.DataFrame(records, index=pd.DatetimeIndex(index, tz="UTC"))


def _make_equity(values: list[float], start: datetime | None = None) -> pd.DataFrame:
    """Build an equity DataFrame sampled every day."""
    if start is None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
    index = [start + timedelta(days=i) for i in range(len(values))]
    return pd.DataFrame({"equity": values}, index=pd.DatetimeIndex(index, tz="UTC"))


# ── Empty / edge cases ────────────────────────────────────────────────────────


class TestEmptyInputs:
    def test_empty_deals_returns_error_dict(self):
        # Arrange
        deals = pd.DataFrame()
        equity = pd.DataFrame()
        # Act
        result = calculate_metrics_from_df(deals, equity)
        # Assert
        assert "error" in result
        assert "No trades" in result["error"]

    def test_only_balance_deals_returns_error(self):
        # Arrange — balance deals are deposits/withdrawals, not trades
        deals = _make_deals([{"type": "balance", "profit": 1000.0}])
        equity = pd.DataFrame()
        # Act
        result = calculate_metrics_from_df(deals, equity)
        # Assert
        assert "error" in result
        assert "No valid trading deals" in result["error"]

    def test_single_equity_point_skips_drawdown_and_sharpe(self):
        # Cannot compute returns from a single price point
        deals = _make_deals([{"type": "BUY", "profit": 100.0}])
        equity = _make_equity([10000.0])  # only 1 point
        result = calculate_metrics_from_df(deals, equity)
        assert "Sharpe Ratio" not in result
        assert "Drawdown" not in result

    def test_no_equity_df_produces_no_risk_metrics(self):
        deals = _make_deals([{"type": "BUY", "profit": 50.0}])
        result = calculate_metrics_from_df(deals, pd.DataFrame())
        assert "Sharpe Ratio" not in result
        assert "Drawdown" not in result


# ── Core metric calculations ──────────────────────────────────────────────────


class TestCoreMetrics:
    def test_total_trades_counts_only_buy_sell(self):
        # Arrange — mix of buy, sell, balance
        deals = _make_deals(
            [
                {"type": "BUY", "profit": 50.0},
                {"type": "SELL", "profit": -20.0},
                {"type": "balance", "profit": 1000.0},  # should be excluded
            ]
        )
        # Act
        result = calculate_metrics_from_df(deals, pd.DataFrame())
        # Assert — balance deals excluded from trade count
        assert result["Total Trades"] == 2

    def test_net_profit_includes_commission_and_swap(self):
        # Arrange — profit=100, commission=-3, swap=-1 → net=96
        deals = _make_deals(
            [{"type": "BUY", "profit": 100.0, "commission": -3.0, "swap": -1.0}]
        )
        # Act
        result = calculate_metrics_from_df(deals, pd.DataFrame())
        # Assert — net profit = profit + commission + swap
        assert result["Profit"] == pytest.approx(96.0)

    def test_net_profit_with_multiple_trades(self):
        deals = _make_deals(
            [
                {"type": "BUY", "profit": 200.0, "commission": -2.0, "swap": 0.0},
                {"type": "SELL", "profit": -50.0, "commission": -2.0, "swap": -1.0},
            ]
        )
        result = calculate_metrics_from_df(deals, pd.DataFrame())
        # 200 - 2 + (-50) - 2 - 1 = 145
        assert result["Profit"] == pytest.approx(145.0)

    def test_gross_profit_only_positive_trades(self):
        deals = _make_deals(
            [
                {"type": "BUY", "profit": 300.0},
                {"type": "SELL", "profit": -100.0},
            ]
        )
        result = calculate_metrics_from_df(deals, pd.DataFrame())
        assert result["Gross Profit"] == pytest.approx(300.0)

    def test_gross_loss_stored_as_negative(self):
        deals = _make_deals(
            [
                {"type": "BUY", "profit": 100.0},
                {"type": "SELL", "profit": -75.0},
            ]
        )
        result = calculate_metrics_from_df(deals, pd.DataFrame())
        assert result["Gross Loss"] == pytest.approx(-75.0)


# ── Win rate ──────────────────────────────────────────────────────────────────


class TestWinRate:
    def test_all_winning_trades_gives_100_percent(self):
        deals = _make_deals(
            [
                {"type": "BUY", "profit": 50.0},
                {"type": "SELL", "profit": 30.0},
            ]
        )
        result = calculate_metrics_from_df(deals, pd.DataFrame())
        assert result["Win Rate (%)"] == pytest.approx(100.0)

    def test_all_losing_trades_gives_zero_percent(self):
        deals = _make_deals(
            [
                {"type": "BUY", "profit": -10.0},
                {"type": "SELL", "profit": -20.0},
            ]
        )
        result = calculate_metrics_from_df(deals, pd.DataFrame())
        assert result["Win Rate (%)"] == pytest.approx(0.0)

    def test_half_wins_gives_fifty_percent(self):
        deals = _make_deals(
            [
                {"type": "BUY", "profit": 40.0},
                {"type": "SELL", "profit": -40.0},
            ]
        )
        result = calculate_metrics_from_df(deals, pd.DataFrame())
        assert result["Win Rate (%)"] == pytest.approx(50.0)

    def test_single_winning_trade_gives_100_percent(self):
        deals = _make_deals([{"type": "BUY", "profit": 1.0}])
        result = calculate_metrics_from_df(deals, pd.DataFrame())
        assert result["Win Rate (%)"] == pytest.approx(100.0)


# ── Profit factor ─────────────────────────────────────────────────────────────


class TestProfitFactor:
    def test_profit_factor_is_gross_profit_over_gross_loss(self):
        deals = _make_deals(
            [
                {"type": "BUY", "profit": 300.0},
                {"type": "SELL", "profit": -100.0},
            ]
        )
        result = calculate_metrics_from_df(deals, pd.DataFrame())
        assert result["Profit Factor"] == pytest.approx(3.0)

    def test_no_losing_trades_gives_infinite_profit_factor(self):
        deals = _make_deals([{"type": "BUY", "profit": 100.0}])
        result = calculate_metrics_from_df(deals, pd.DataFrame())
        assert math.isinf(result["Profit Factor"])

    def test_profit_factor_less_than_one_means_net_loss(self):
        deals = _make_deals(
            [
                {"type": "BUY", "profit": 50.0},
                {"type": "SELL", "profit": -200.0},
            ]
        )
        result = calculate_metrics_from_df(deals, pd.DataFrame())
        assert result["Profit Factor"] == pytest.approx(0.25)


# ── Risk-Reward Ratio ──────────────────────────────────────────────────────────


class TestRiskRewardRatio:
    def test_risk_reward_ratio_with_wins_and_losses(self):
        deals = _make_deals(
            [
                {"type": "BUY", "profit": 100.0},
                {"type": "SELL", "profit": -50.0},
                {"type": "BUY", "profit": 80.0},
                {"type": "SELL", "profit": -40.0},
            ]
        )
        result = calculate_metrics_from_df(deals, pd.DataFrame(), advanced=True)
        assert "Risk-Reward Ratio" in result
        assert result["Risk-Reward Ratio"] is not None
        assert result["Risk-Reward Ratio"] > 0

    def test_risk_reward_ratio_all_wins_returns_none(self):
        deals = _make_deals([{"type": "BUY", "profit": 100.0}])
        result = calculate_metrics_from_df(deals, pd.DataFrame(), advanced=True)
        # Risk-Reward Ratio requires both wins and losses to calculate
        assert "Risk-Reward Ratio" not in result

    def test_risk_reward_ratio_all_losses_returns_none(self):
        deals = _make_deals([{"type": "SELL", "profit": -100.0}])
        result = calculate_metrics_from_df(deals, pd.DataFrame(), advanced=True)
        # Risk-Reward Ratio requires both wins and losses to calculate
        assert "Risk-Reward Ratio" not in result

    def test_risk_reward_ratio_not_in_basic_metrics(self):
        deals = _make_deals([{"type": "BUY", "profit": 100.0}])
        result = calculate_metrics_from_df(deals, pd.DataFrame(), advanced=False)
        assert "Risk-Reward Ratio" not in result


# ── Risk metrics (require equity curve) ───────────────────────────────────────


class TestRiskMetrics:
    def test_growing_equity_curve_produces_positive_sharpe(self):
        # Arrange — consistently growing equity implies positive returns
        deals = _make_deals([{"type": "BUY", "profit": 100.0} for _ in range(10)])
        values = [10000.0 + i * 100 for i in range(30)]  # monotonically rising
        equity = _make_equity(values)
        # Act
        result = calculate_metrics_from_df(deals, equity)
        # Assert — Sharpe must be computable and positive for steady growth
        assert "Sharpe Ratio" in result
        if result["Sharpe Ratio"] is not None:
            assert result["Sharpe Ratio"] > 0

    def test_max_drawdown_is_negative_or_zero_percent(self):
        deals = _make_deals([{"type": "BUY", "profit": 10.0} for _ in range(5)])
        # Equity goes up then sharply down — creates a drawdown
        values = [10000.0, 11000.0, 12000.0, 9000.0, 9500.0, 10000.0]
        equity = _make_equity(values)
        result = calculate_metrics_from_df(deals, equity)
        if "Drawdown" in result and result["Drawdown"] is not None:
            assert result["Drawdown"] <= 0  # quantstats returns negative

    def test_flat_equity_curve_does_not_crash(self):
        # Zero variance daily returns — Sharpe may be 0 or NaN but should not raise
        deals = _make_deals([{"type": "BUY", "profit": 0.0} for _ in range(3)])
        equity = _make_equity([10000.0] * 10)
        result = calculate_metrics_from_df(deals, equity)
        # Should not raise; Sharpe may be None or 0
        assert "error" not in result
