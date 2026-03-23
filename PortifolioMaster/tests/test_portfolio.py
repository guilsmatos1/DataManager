import glob
import os

import pytest
from portifoliomaster.services.portfolio import PortfolioManager
from portifoliomaster.utils.mt5_parser import MT5ReportParser

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")


@pytest.fixture(scope="module")
def loaded_manager():
    """PortfolioManager with 5 real strategies loaded from tests/reports/."""
    report_files = sorted(glob.glob(os.path.join(REPORTS_DIR, "*.html")))[:5]
    assert report_files, "No HTML files found in tests/reports/"

    parser = MT5ReportParser()
    pm = PortfolioManager()
    for filepath in report_files:
        expert_name = parser.parse_report(filepath)
        pm.add_strategy(expert_name, parser.deals_by_expert[expert_name])
    return pm


def test_add_strategy_returns_true():
    """add_strategy returns True for a valid report."""
    report_files = glob.glob(os.path.join(REPORTS_DIR, "*.html"))
    assert report_files, "No HTML files found in tests/reports/"

    parser = MT5ReportParser()
    expert_name = parser.parse_report(report_files[0])

    pm = PortfolioManager()
    success = pm.add_strategy(expert_name, parser.deals_by_expert[expert_name])

    assert success is True
    assert expert_name in pm.strategies


def test_add_strategy_stores_net_profit_column():
    """Stored strategy DataFrame contains Net_Profit column with non-zero values."""
    report_files = glob.glob(os.path.join(REPORTS_DIR, "*.html"))
    assert report_files, "No HTML files found in tests/reports/"

    parser = MT5ReportParser()
    expert_name = parser.parse_report(report_files[0])

    pm = PortfolioManager()
    pm.add_strategy(expert_name, parser.deals_by_expert[expert_name])

    df = pm.strategies[expert_name]
    assert "Net_Profit" in df.columns
    assert len(df) > 0
    assert df["Net_Profit"].sum() != 0.0


def test_strategy_metrics_are_valid(loaded_manager):
    """calculate_strategy_metrics returns valid non-null metrics."""
    for name in loaded_manager.strategies:
        metrics = loaded_manager.calculate_strategy_metrics(name)

        assert metrics is not None, f"None metrics for {name}"
        assert "Profit" in metrics
        assert "MaxDD" in metrics
        assert "RetDD" in metrics
        assert "Trades" in metrics
        assert metrics["MaxDD"] >= 0.0
        assert metrics["Trades"] > 0


def test_get_returns_matrix_shape_and_columns(loaded_manager):
    """get_returns_matrix returns a wide DataFrame with one column per strategy."""
    matrix = loaded_manager.get_returns_matrix()

    assert not matrix.is_empty()
    assert "Horário" in matrix.columns

    for name in loaded_manager.strategies:
        assert name in matrix.columns, f"Strategy column missing: {name}"


def test_get_returns_matrix_no_nulls(loaded_manager):
    """Returns matrix has no null values (all timestamps filled with 0.0)."""
    matrix = loaded_manager.get_returns_matrix()

    for name in loaded_manager.strategies:
        assert matrix[name].null_count() == 0, f"Nulls found in column: {name}"


def test_get_all_trades_long_format(loaded_manager):
    """get_all_trades_long returns all trades with Strategy and Net_Profit columns."""
    long_df = loaded_manager.get_all_trades_long()

    assert not long_df.is_empty()
    assert "Strategy" in long_df.columns
    assert "Net_Profit" in long_df.columns
    assert "Horário" in long_df.columns

    expected_strategies = set(loaded_manager.strategies.keys())
    actual_strategies = set(long_df["Strategy"].unique().to_list())
    assert actual_strategies == expected_strategies


def test_empty_manager_returns_empty_matrix():
    """An empty PortfolioManager returns an empty matrix."""
    pm = PortfolioManager()
    matrix = pm.get_returns_matrix()
    assert matrix.is_empty()
