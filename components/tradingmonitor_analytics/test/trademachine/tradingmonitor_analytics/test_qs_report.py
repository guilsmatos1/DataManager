from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from trademachine.tradingmonitor_analytics.metrics.calculator import generate_qs_report


@pytest.fixture
def mock_equity_df():
    dates = pd.date_range(start="2023-01-01", periods=10, freq="D")
    df = pd.DataFrame(
        {"equity": [1000, 1010, 1005, 1020, 1030, 1025, 1040, 1050, 1045, 1060]},
        index=dates,
    )
    return df


def test_generate_qs_report_strategy_success(mock_equity_df):
    strategy_id = "test_strat"
    output_path = "test_report.html"

    with patch(
        "trademachine.tradingmonitor_analytics.metrics.calculator.get_strategy_equity_curve"
    ) as mock_get_equity:
        mock_get_equity.return_value = mock_equity_df

        with patch("quantstats.reports.html") as mock_qs_html:
            result = generate_qs_report(
                strategy_id=strategy_id, output_path=output_path
            )

            assert result == output_path
            assert mock_qs_html.called
            args, kwargs = mock_qs_html.call_args
            # First arg is daily returns series
            assert isinstance(args[0], pd.Series)
            assert kwargs["output"] == output_path
            assert "Strategy Report: test_strat" in kwargs["title"]


def test_generate_qs_report_no_data():
    strategy_id = "no_data_strat"

    with patch(
        "trademachine.tradingmonitor_analytics.metrics.calculator.get_strategy_equity_curve"
    ) as mock_get_equity:
        mock_get_equity.return_value = pd.DataFrame()

        result = generate_qs_report(strategy_id=strategy_id)
        assert result is None


def test_generate_qs_report_portfolio_success(mock_equity_df):
    portfolio_id = 1
    output_path = "portfolio_report.html"

    # Mock database and models
    mock_portfolio = MagicMock()
    mock_portfolio.name = "Test Portfolio"
    mock_strat = MagicMock()
    mock_strat.id = "strat1"
    mock_portfolio.strategies = [mock_strat]

    with patch(
        "trademachine.tradingmonitor_analytics.metrics.calculator.SessionLocal"
    ) as mock_session_cls:
        mock_session = mock_session_cls.return_value
        mock_session.query.return_value.filter.return_value.first.return_value = (
            mock_portfolio
        )

        with patch(
            "trademachine.tradingmonitor_analytics.metrics.calculator.get_strategy_equity_curve"
        ) as mock_get_equity:
            mock_get_equity.return_value = mock_equity_df

            with patch("quantstats.reports.html") as mock_qs_html:
                result = generate_qs_report(
                    portfolio_id=portfolio_id, output_path=output_path
                )

                assert result == output_path
                assert mock_qs_html.called
                assert (
                    "Portfolio Report: Test Portfolio"
                    in mock_qs_html.call_args[1]["title"]
                )
