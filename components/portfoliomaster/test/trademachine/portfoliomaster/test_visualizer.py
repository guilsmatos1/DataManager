"""
Tests for Visualizer Module.
Mocks UI interactions (Plotly show, webbrowser open) to run in CI.
"""

import os
from unittest.mock import patch

import polars as pl
import pytest
from trademachine.portfoliomaster.utils.visualizer import (
    _build_equity_data,
    generate_montecarlo_report_html,
    generate_portfolio_report_html,
    plot_portfolio_equity,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_strategies():
    """Returns a dict of sample strategy DataFrames."""
    df1 = pl.DataFrame({"Horário": [1, 2, 3], "Net_Profit": [10.0, 20.0, -5.0]})
    df2 = pl.DataFrame({"Horário": [1, 2, 4], "Net_Profit": [5.0, -2.0, 15.0]})
    return {"Strat1": df1, "Strat2": df2}


@pytest.fixture
def sample_portfolios():
    """Returns a list of portfolio result dicts."""
    return [
        {
            "Combo": ("Strat1", "Strat2"),
            "Total_Trades": 6,
            "Net_Profit": 43.0,
            "RetDD": 2.5,
            "Maximum_Drawdown": 17.2,
            "Winning_Trades_Count": 4,
            "Losing_Trades_Count": 2,
        }
    ]


# ---------------------------------------------------------------------------
# _build_equity_data
# ---------------------------------------------------------------------------


def test_build_equity_data_valid(sample_strategies):
    combo = ("Strat1", "Strat2")
    strat_traces, (port_ts, port_equity) = _build_equity_data(combo, sample_strategies)

    assert len(strat_traces) == 2
    assert strat_traces[0][0] == "Strat1"
    assert strat_traces[0][2] == [10.0, 30.0, 25.0]  # CumSum

    # Portfolio equity: sum of all trades sorted by time
    # Times: 1, 1, 2, 2, 3, 4
    # Profits: 10, 5, 20, -2, -5, 15
    # CumSum: 10, 15, 35, 33, 28, 43
    assert port_equity[-1] == 43.0
    assert len(port_ts) == 6


def test_build_equity_data_empty():
    strat_traces, (port_ts, port_equity) = _build_equity_data((), {})
    assert strat_traces == []
    assert port_ts == []
    assert port_equity == []


def test_build_equity_data_missing_strategy(sample_strategies):
    combo = ("Strat1", "Missing")
    strat_traces, (port_ts, port_equity) = _build_equity_data(combo, sample_strategies)
    assert len(strat_traces) == 1
    assert strat_traces[0][0] == "Strat1"


# ---------------------------------------------------------------------------
# plot_portfolio_equity
# ---------------------------------------------------------------------------


@patch("plotly.graph_objects.Figure.show")
def test_plot_portfolio_equity_calls_show(mock_show, sample_strategies):
    plot_portfolio_equity(("Strat1",), sample_strategies)
    mock_show.assert_called_once()


def test_plot_portfolio_equity_empty_combo_raises():
    with pytest.raises(ValueError, match="combo cannot be empty"):
        plot_portfolio_equity((), {})


# ---------------------------------------------------------------------------
# generate_portfolio_report_html
# ---------------------------------------------------------------------------


@patch("webbrowser.open")
def test_generate_portfolio_report_html_creates_file(
    _, sample_portfolios, sample_strategies, tmp_path
):
    output_path = str(tmp_path / "report.html")
    path = generate_portfolio_report_html(
        sample_portfolios,
        sample_strategies,
        output_path=output_path,
        open_browser=False,
    )

    assert os.path.exists(path)
    with open(path, encoding="utf-8") as f:
        content = f.read()
        assert "Portfolio Optimization Results" in content
        assert "Strat1" in content
        assert "Strat2" in content
        assert "plotly-latest.min.js" in content


@patch("webbrowser.open")
def test_generate_portfolio_report_html_handles_errors(_, tmp_path):
    """Test that it doesn't crash if a portfolio has no data."""
    portfolios = [{"Combo": ("Missing",)}]
    output_path = str(tmp_path / "error_report.html")
    path = generate_portfolio_report_html(
        portfolios, {}, output_path=output_path, open_browser=False
    )
    assert os.path.exists(path)
    with open(path, encoding="utf-8") as f:
        content = f.read()
        assert "Chart error" in content


# ---------------------------------------------------------------------------
# generate_montecarlo_report_html
# ---------------------------------------------------------------------------


class MockMCResult:
    def __init__(self):
        import numpy as np

        self.simulated_equities = np.zeros((10, 5))
        self.original_equity = np.array([0, 1, 2, 3, 4])
        self.max_dd_distribution = np.array([10, 20])
        self.ret_dd_distribution = np.array([1, 2])
        self.original_max_dd = 15.0
        self.original_ret_dd = 2.0
        self.summary = {
            "n_iterations": 10,
            "n_trades": 5,
            "max_dd": {"mean": 15, "median": 15, "p5": 10, "p95": 20, "worst": 25},
            "ret_dd": {"mean": 2, "median": 2, "p5": 1, "p95": 3, "worst": 0.5},
        }


@patch("webbrowser.open")
def test_generate_montecarlo_report_html(_, tmp_path):
    mc_result = MockMCResult()
    output_path = str(tmp_path / "mc_report.html")
    path = generate_montecarlo_report_html(
        mc_result, ("Strat1",), output_path=output_path, open_browser=False
    )

    assert os.path.exists(path)
    with open(path, encoding="utf-8") as f:
        content = f.read()
        assert "Monte Carlo Simulation Report" in content
        assert "Strat1" in content
        assert "Original" in content
