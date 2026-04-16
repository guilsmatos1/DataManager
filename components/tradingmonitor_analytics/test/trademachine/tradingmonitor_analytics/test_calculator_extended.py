from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pandas as pd
import pytest
from trademachine.tradingmonitor_analytics.metrics.calculator import (
    calculate_concurrency,
    calculate_correlation_matrix,
    calculate_metrics,
    calculate_portfolio_metrics,
)


@pytest.fixture
def mock_deals_df():
    base_time = datetime(2024, 1, 1, tzinfo=UTC)
    data = {
        "profit": [10.0, -5.0, 15.0],
        "commission": [-1.0, -1.0, -1.0],
        "swap": [0.0, 0.0, 0.0],
        "type": ["BUY", "BUY", "SELL"],
    }
    index = [base_time + timedelta(days=i) for i in range(3)]
    return pd.DataFrame(data, index=pd.DatetimeIndex(index, tz="UTC"))


@pytest.fixture
def mock_equity_df():
    base_time = datetime(2024, 1, 1, tzinfo=UTC)
    data = {"equity": [1000.0, 1010.0, 1005.0, 1020.0]}
    index = [base_time + timedelta(days=i) for i in range(4)]
    return pd.DataFrame(data, index=pd.DatetimeIndex(index, tz="UTC"))


class TestCalculateMetricsWrapper:
    """Tests for calculate_metrics wrapper function (lines 155-157)."""

    def test_calculate_metrics_wrapper_returns_metrics(
        self, mock_deals_df, mock_equity_df
    ):
        """Test that wrapper correctly calls repository and returns metrics."""
        with patch(
            "trademachine.tradingmonitor_analytics.metrics.calculator.get_strategy_deals"
        ) as mock_get_deals:
            with patch(
                "trademachine.tradingmonitor_analytics.metrics.calculator.get_strategy_equity_curve"
            ) as mock_get_equity:
                mock_get_deals.return_value = mock_deals_df
                mock_get_equity.return_value = mock_equity_df
                result = calculate_metrics("test_strategy")
                assert "Total Trades" in result
                assert result["Total Trades"] == 3


class TestCorrelationMatrixEdgeCases:
    """Tests for correlation matrix edge cases."""

    def test_correlation_matrix_only_one_strategy(self):
        """Test with only 1 strategy returns error (covers early return path)."""
        with patch(
            "trademachine.tradingmonitor_analytics.metrics.calculator.get_strategy_deals"
        ) as mock_get_deals:
            mock_get_deals.return_value = pd.DataFrame()
            result = calculate_correlation_matrix(["s1"])
            assert "error" in result
            assert "Need at least 2 strategies" in result["error"]

    def test_correlation_matrix_insufficient_overlap(self):
        """Test correlation with less than 3 overlapping periods (line 184).

        The correlation function requires at least 3 overlapping data points.
        Here we create two strategies with only 2 non-zero aligned data points.
        """
        base_time = datetime(2024, 1, 1, tzinfo=UTC)

        # Create two strategies with same dates so they align perfectly
        # but only 2 points total - below the 3 point minimum
        dates = pd.DatetimeIndex([base_time, base_time + timedelta(days=1)], tz="UTC")

        df1 = pd.DataFrame(
            {
                "profit": [10.0, 20.0],
                "commission": [0.0, 0.0],
                "swap": [0.0, 0.0],
                "type": ["BUY", "SELL"],
            },
            index=dates,
        )
        df2 = pd.DataFrame(
            {
                "profit": [5.0, 10.0],
                "commission": [0.0, 0.0],
                "swap": [0.0, 0.0],
                "type": ["BUY", "SELL"],
            },
            index=dates,
        )

        with patch(
            "trademachine.tradingmonitor_analytics.metrics.calculator.get_strategy_deals"
        ) as mock_get_deals:
            mock_get_deals.side_effect = [df1, df2]
            result = calculate_correlation_matrix(["s1", "s2"])
            assert "error" in result
            assert "Not enough overlapping" in result["error"]

    def test_correlation_matrix_weekly_period(self):
        """Test correlation with weekly period."""
        base_time = datetime(2024, 1, 1, tzinfo=UTC)
        # Need enough data points for weekly resampling
        dates = [base_time + timedelta(days=i) for i in range(30)]
        data = {
            "profit": [10.0 + i for i in range(30)],
            "commission": [0.0] * 30,
            "swap": [0.0] * 30,
            "type": ["BUY"] * 30,
        }

        df1 = pd.DataFrame(data, index=pd.DatetimeIndex(dates, tz="UTC"))
        df2 = df1.copy()
        df2["profit"] = [20.0 + i for i in range(30)]

        with patch(
            "trademachine.tradingmonitor_analytics.metrics.calculator.get_strategy_deals"
        ) as mock_get_deals:
            mock_get_deals.side_effect = [df1, df2]
            result = calculate_correlation_matrix(["s1", "s2"], period="weekly")
            assert "matrix" in result
            assert result["period"] == "weekly"

    def test_correlation_matrix_monthly_period(self):
        """Test correlation with monthly period."""
        base_time = datetime(2024, 1, 1, tzinfo=UTC)
        # Need enough data points for monthly resampling
        dates = [base_time + timedelta(days=i) for i in range(90)]
        data = {
            "profit": [10.0 + i for i in range(90)],
            "commission": [0.0] * 90,
            "swap": [0.0] * 90,
            "type": ["BUY"] * 90,
        }

        df1 = pd.DataFrame(data, index=pd.DatetimeIndex(dates, tz="UTC"))
        df2 = df1.copy()
        df2["profit"] = [20.0 + i for i in range(90)]

        with patch(
            "trademachine.tradingmonitor_analytics.metrics.calculator.get_strategy_deals"
        ) as mock_get_deals:
            mock_get_deals.side_effect = [df1, df2]
            result = calculate_correlation_matrix(["s1", "s2"], period="monthly")
            assert "matrix" in result
            assert result["period"] == "monthly"


class TestConcurrencyEdgeCases:
    """Tests for concurrency edge cases."""

    def test_concurrency_only_one_strategy(self):
        """Test concurrency with only 1 strategy returns error (line 248)."""
        with patch(
            "trademachine.tradingmonitor_analytics.metrics.calculator.get_strategy_deals"
        ) as mock_get_deals:
            mock_get_deals.return_value = pd.DataFrame()
            result = calculate_concurrency(["s1"])
            assert "error" in result
            assert "Need at least 2 strategies" in result["error"]

    def test_concurrency_with_datetime_tz(self):
        """Test concurrency with timezone-aware indexes."""
        base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        idx1 = pd.DatetimeIndex([base_time, base_time + timedelta(hours=1)], tz=UTC)
        idx2 = pd.DatetimeIndex([base_time, base_time + timedelta(hours=2)], tz=UTC)

        df1 = pd.DataFrame(
            {
                "profit": [10.0, 20.0],
                "commission": [0.0, 0.0],
                "swap": [0.0, 0.0],
                "type": ["BUY", "SELL"],
            },
            index=idx1,
        )
        df2 = pd.DataFrame(
            {
                "profit": [5.0, 10.0],
                "commission": [0.0, 0.0],
                "swap": [0.0, 0.0],
                "type": ["BUY", "SELL"],
            },
            index=idx2,
        )

        with patch(
            "trademachine.tradingmonitor_analytics.metrics.calculator.get_strategy_deals"
        ) as mock_get_deals:
            mock_get_deals.side_effect = [df1, df2]
            result = calculate_concurrency(["s1", "s2"])
            assert "same_hour" in result


class TestPortfolioMetricsEdgeCases:
    """Tests for portfolio metrics edge cases."""

    def test_portfolio_metrics_deals_only_no_equity(self, mock_deals_df):
        """Test portfolio with deals but no equity (line 252)."""
        with patch(
            "trademachine.tradingmonitor_analytics.metrics.calculator.get_strategy_deals"
        ) as mock_get_deals:
            with patch(
                "trademachine.tradingmonitor_analytics.metrics.calculator.get_strategy_equity_curve"
            ) as mock_get_equity:
                mock_get_deals.side_effect = [mock_deals_df, mock_deals_df]
                mock_get_equity.return_value = pd.DataFrame()
                result = calculate_portfolio_metrics(["s1", "s2"])
                assert result["Total Trades"] == 6
                # Should still calculate basic metrics without equity

    def test_portfolio_metrics_tolerates_duplicate_timestamps(self):
        base_time = datetime(2024, 1, 1, tzinfo=UTC)
        duplicate_index = pd.DatetimeIndex(
            [base_time, base_time, base_time + timedelta(days=1)],
            tz="UTC",
        )
        duplicate_deals_df = pd.DataFrame(
            {
                "profit": [10.0, -5.0, 15.0],
                "commission": [-1.0, -1.0, -1.0],
                "swap": [0.0, 0.0, 0.0],
                "type": ["BUY", "SELL", "BUY"],
            },
            index=duplicate_index,
        )

        with patch(
            "trademachine.tradingmonitor_analytics.metrics.calculator.get_strategy_deals"
        ) as mock_get_deals:
            mock_get_deals.side_effect = [duplicate_deals_df, duplicate_deals_df.copy()]

            result = calculate_portfolio_metrics(["s1", "s2"])

            assert result["Total Trades"] == 6
            assert result["Profit"] == pytest.approx(34.0)


class TestCalculatorExtended:
    def test_calculate_correlation_matrix_basic(self, mock_deals_df):
        df1 = mock_deals_df.copy()
        df2 = mock_deals_df.copy()
        df2["profit"] = [5.0, 10.0, -2.0]

        with patch(
            "trademachine.tradingmonitor_analytics.metrics.calculator.get_strategy_deals"
        ) as mock_get_deals:
            mock_get_deals.side_effect = [df1, df2]
            result = calculate_correlation_matrix(["s1", "s2"], period="daily")
            assert "matrix" in result
            assert len(result["strategies"]) == 2
            assert result["data_points"] == 3

    def test_calculate_correlation_matrix_not_enough_data(self):
        with patch(
            "trademachine.tradingmonitor_analytics.metrics.calculator.get_strategy_deals"
        ) as mock_get_deals:
            mock_get_deals.return_value = pd.DataFrame()
            result = calculate_correlation_matrix(["s1", "s2"])
            assert "error" in result
            assert "Need at least 2 strategies" in result["error"]

    def test_calculate_concurrency_basic(self):
        base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        idx1 = pd.DatetimeIndex([base_time, base_time + timedelta(hours=1)])
        idx2 = pd.DatetimeIndex([base_time, base_time + timedelta(hours=2)])

        df1 = pd.DataFrame(index=idx1)
        df1["dummy"] = 1
        df2 = pd.DataFrame(index=idx2)
        df2["dummy"] = 1

        with patch(
            "trademachine.tradingmonitor_analytics.metrics.calculator.get_strategy_deals"
        ) as mock_get_deals:
            # We must return non-empty DataFrames for both strategies
            mock_get_deals.side_effect = [df1, df2]

            result = calculate_concurrency(["s1", "s2"])

            # If the above fails, it will return the "Need at least 2 strategies" error
            assert "same_hour" in result, f"Result was {result}"
            assert result["same_hour"][0][1] == 50.0

    def test_calculate_portfolio_metrics_basic(self, mock_deals_df, mock_equity_df):
        with patch(
            "trademachine.tradingmonitor_analytics.metrics.calculator.get_strategy_deals"
        ) as mock_get_deals:
            with patch(
                "trademachine.tradingmonitor_analytics.metrics.calculator.get_strategy_equity_curve"
            ) as mock_get_equity:
                mock_get_deals.side_effect = [mock_deals_df, mock_deals_df]
                mock_get_equity.side_effect = [mock_equity_df, mock_equity_df]

                result = calculate_portfolio_metrics(["s1", "s2"])
                assert result["Total Trades"] == 6
                assert result["Profit"] == pytest.approx(34.0)
                assert "Sharpe Ratio" in result

    def test_calculate_portfolio_metrics_no_data(self):
        with patch(
            "trademachine.tradingmonitor_analytics.metrics.calculator.get_strategy_deals"
        ) as mock_get_deals:
            mock_get_deals.return_value = pd.DataFrame()
            result = calculate_portfolio_metrics(["s1", "s2"])
            assert "error" in result
            assert "No data found" in result["error"]
