"""
Tests for PortifolioCLI pipeline:
  - load_reports (HTML directory, invalid dir, cache)
  - _apply_date_filter / _apply_strategy_filter
  - _export_to_json / _save_best_portfolio_trades
  - run_optimization (integration via real data)
  - list_loaded_strategies
"""

import json
import os
from unittest.mock import MagicMock, patch

import polars as pl
import pytest
from portifoliomaster.api.cli import PortifolioCLI
from portifoliomaster.core.exceptions import ValidationError

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def loaded_cli():
    """PortifolioCLI with real strategies loaded from tests/reports/."""
    cli = PortifolioCLI()
    cli.load_reports(REPORTS_DIR)
    assert cli.loaded_expert_names, "No strategies loaded — check tests/reports/"
    return cli


@pytest.fixture(scope="module")
def sample_portfolio(loaded_cli):
    """A minimal portfolio dict using the first loaded strategy."""
    name = loaded_cli.loaded_expert_names[0]
    return {
        "Combo": (name,),
        "Net_Profit": 1000.0,
        "RetDD": 5.0,
        "Maximum_Drawdown": 200.0,
    }


# ---------------------------------------------------------------------------
# load_reports
# ---------------------------------------------------------------------------


def test_load_reports_from_directory():
    cli = PortifolioCLI()
    cli.load_reports(REPORTS_DIR)
    assert len(cli.loaded_expert_names) > 0


def test_load_reports_invalid_directory(caplog):
    cli = PortifolioCLI()
    cli.load_reports("/nonexistent/path/xyz", use_cache=False)
    assert cli.loaded_expert_names == []


def test_load_reports_empty_directory(tmp_path):
    cli = PortifolioCLI()
    cli.load_reports(str(tmp_path), use_cache=False)
    assert cli.loaded_expert_names == []


def test_load_reports_no_cache_no_dir(caplog):
    """load_reports with no cache and no directory logs an error and returns."""
    cli = PortifolioCLI()
    cli.load_reports(directory_path=None, use_cache=False)
    assert cli.loaded_expert_names == []


def test_load_reports_from_cache(tmp_path):
    """load_reports reads from cache.parquet when present."""
    # First load to create real data
    cli_src = PortifolioCLI()
    cli_src.load_reports(REPORTS_DIR)
    matrix = cli_src.portfolio_manager.get_returns_matrix()

    # Write a valid cache in tmp_path
    cache_path = os.path.join(str(tmp_path), "cache.parquet")
    matrix.write_parquet(cache_path)

    # Load from cache (change cwd to tmp_path)
    original_cwd = os.getcwd()
    try:
        os.chdir(str(tmp_path))
        cli2 = PortifolioCLI()
        cli2.load_reports(use_cache=True)
        assert len(cli2.loaded_expert_names) > 0
    finally:
        os.chdir(original_cwd)


# ---------------------------------------------------------------------------
# list_loaded_strategies
# ---------------------------------------------------------------------------


def test_list_loaded_strategies_runs_without_error(loaded_cli, capsys):
    loaded_cli.list_loaded_strategies()
    output = capsys.readouterr().out
    assert len(output) > 0


def test_list_loaded_strategies_empty(capsys):
    cli = PortifolioCLI()
    cli.list_loaded_strategies()  # should not raise


# ---------------------------------------------------------------------------
# _apply_date_filter
# ---------------------------------------------------------------------------


def test_apply_date_filter_start_only(loaded_cli):
    long_df = loaded_cli.portfolio_manager.get_all_trades_long()
    min_date = long_df["Horário"].min()
    mid_date = str(min_date)[:10]  # YYYY-MM-DD

    filtered = loaded_cli._apply_date_filter(long_df, date_initial=mid_date, date_final=None)
    assert len(filtered) <= len(long_df)
    assert not filtered.is_empty()


def test_apply_date_filter_end_only(loaded_cli):
    long_df = loaded_cli.portfolio_manager.get_all_trades_long()
    max_date = long_df["Horário"].max()
    mid_date = str(max_date)[:10]

    filtered = loaded_cli._apply_date_filter(long_df, date_initial=None, date_final=mid_date)
    assert not filtered.is_empty()


def test_apply_date_filter_full_range_keeps_all(loaded_cli):
    long_df = loaded_cli.portfolio_manager.get_all_trades_long()
    min_date = str(long_df["Horário"].min())[:10]
    max_date = str(long_df["Horário"].max())[:10]

    filtered = loaded_cli._apply_date_filter(long_df, date_initial=min_date, date_final=max_date)
    assert len(filtered) == len(long_df)


def test_apply_date_filter_impossible_range_raises(loaded_cli):
    long_df = loaded_cli.portfolio_manager.get_all_trades_long()
    with pytest.raises(ValidationError, match="No trades found"):
        loaded_cli._apply_date_filter(long_df, date_initial="2050-01-01", date_final="2050-12-31")


# ---------------------------------------------------------------------------
# _apply_strategy_filter
# ---------------------------------------------------------------------------


def test_apply_strategy_filter_valid_names(loaded_cli):
    long_df = loaded_cli.portfolio_manager.get_all_trades_long()
    name = loaded_cli.loaded_expert_names[0]

    filtered = loaded_cli._apply_strategy_filter(long_df, [name], min_assets=1)
    strategies_in_result = filtered["Strategy"].unique().to_list()
    assert name in strategies_in_result
    assert len(strategies_in_result) == 1


def test_apply_strategy_filter_unknown_names_warns_but_uses_valid(loaded_cli):
    long_df = loaded_cli.portfolio_manager.get_all_trades_long()
    valid = loaded_cli.loaded_expert_names[0]

    filtered = loaded_cli._apply_strategy_filter(long_df, [valid, "NONEXISTENT"], min_assets=1)
    assert not filtered.is_empty()


def test_apply_strategy_filter_too_few_raises(loaded_cli):
    long_df = loaded_cli.portfolio_manager.get_all_trades_long()
    with pytest.raises(ValidationError):
        loaded_cli._apply_strategy_filter(long_df, ["NONEXISTENT"], min_assets=1)


# ---------------------------------------------------------------------------
# _export_to_json
# ---------------------------------------------------------------------------


def test_export_to_json_creates_file(loaded_cli, sample_portfolio, tmp_path):
    out_file = str(tmp_path / "portfolio")
    loaded_cli._export_to_json(sample_portfolio, out_file)

    assert os.path.exists(out_file + ".json")
    with open(out_file + ".json") as f:
        data = json.load(f)
    assert "strategies" in data
    assert isinstance(data["strategies"], list)


def test_export_to_json_with_extension(loaded_cli, sample_portfolio, tmp_path):
    out_file = str(tmp_path / "portfolio.json")
    loaded_cli._export_to_json(sample_portfolio, out_file)
    assert os.path.exists(out_file)


def test_export_to_json_content(loaded_cli, sample_portfolio, tmp_path):
    out_file = str(tmp_path / "portfolio")
    loaded_cli._export_to_json(sample_portfolio, out_file)

    with open(out_file + ".json") as f:
        data = json.load(f)

    expected_strategies = list(sample_portfolio["Combo"])
    assert data["strategies"] == expected_strategies


# ---------------------------------------------------------------------------
# _save_best_portfolio_trades
# ---------------------------------------------------------------------------


def test_save_best_portfolio_trades_csv(loaded_cli, sample_portfolio, tmp_path):
    out_file = str(tmp_path / "trades.csv")
    loaded_cli._save_best_portfolio_trades([sample_portfolio], out_file)
    assert os.path.exists(out_file)
    df = pl.read_csv(out_file)
    assert "Net_Profit" in df.columns
    assert "Strategy" in df.columns
    assert "portfolio_rank" not in df.columns  # single portfolio — no rank column


def test_save_best_portfolio_trades_parquet(loaded_cli, sample_portfolio, tmp_path):
    out_file = str(tmp_path / "trades.parquet")
    loaded_cli._save_best_portfolio_trades([sample_portfolio], out_file)
    assert os.path.exists(out_file)
    df = pl.read_parquet(out_file)
    assert len(df) > 0


def test_save_best_portfolio_trades_default_extension(loaded_cli, sample_portfolio, tmp_path):
    """Unknown extension defaults to CSV with .csv appended."""
    out_file = str(tmp_path / "trades")
    loaded_cli._save_best_portfolio_trades([sample_portfolio], out_file)
    assert os.path.exists(out_file + ".csv")


def test_save_best_portfolio_trades_combo_as_string(loaded_cli, tmp_path):
    """_save_best_portfolio_trades handles comma-separated string combos."""
    name = loaded_cli.loaded_expert_names[0]
    portfolio = {
        "Combo": name,  # string instead of tuple
        "Net_Profit": 500.0,
        "RetDD": 2.0,
        "Maximum_Drawdown": 100.0,
    }
    out_file = str(tmp_path / "trades_str.csv")
    loaded_cli._save_best_portfolio_trades([portfolio], out_file)
    assert os.path.exists(out_file)


def test_save_best_portfolio_trades_multi(loaded_cli, sample_portfolio, tmp_path):
    """Multiple portfolios produce a portfolio_rank column."""
    names = loaded_cli.loaded_expert_names
    second = {
        "Combo": tuple(names[:2]) if len(names) >= 2 else sample_portfolio["Combo"],
        "Net_Profit": 200.0,
        "RetDD": 1.5,
        "Maximum_Drawdown": 80.0,
    }
    out_file = str(tmp_path / "trades_multi.parquet")
    loaded_cli._save_best_portfolio_trades([sample_portfolio, second], out_file)
    df = pl.read_parquet(out_file)
    assert "portfolio_rank" in df.columns
    assert set(df["portfolio_rank"].unique().to_list()).issuperset({1, 2})


# ---------------------------------------------------------------------------
# run_optimization (integration)
# ---------------------------------------------------------------------------


def test_run_optimization_no_strategies_logs_warning(caplog):
    """run_optimization with no strategies loaded logs a warning and returns."""
    cli = PortifolioCLI()
    cli.run_optimization(
        min_assets=1,
        max_assets=1,
        top_n=3,
        rank_by="RetDD",
        max_correlation=1.0,
        num_workers=1,
    )
    # No crash expected


def test_run_optimization_basic(loaded_cli):
    """run_optimization with real data produces best_portfolios."""
    found = loaded_cli.run_optimization(
        min_assets=1,
        max_assets=1,
        top_n=3,
        rank_by="RetDD",
        max_correlation=1.0,
        num_workers=1,
        corr_period="D",
        show_terminal=False,
        greedy=False,
        min_metric=0.0,
    )
    assert found
    assert len(loaded_cli.last_optimization_results) > 0


def test_run_optimization_greedy_mode(loaded_cli):
    """run_optimization with greedy=True does not raise and returns results."""
    loaded_cli.run_optimization(
        min_assets=1,
        max_assets=1,
        top_n=1,
        rank_by="RetDD",
        max_correlation=1.0,
        num_workers=1,
        corr_period="D",
        show_terminal=False,
        greedy=True,
        min_metric=0.0,
    )


def test_run_optimization_with_date_filter(loaded_cli):
    """run_optimization respects date_initial / date_final filters."""
    long_df = loaded_cli.portfolio_manager.get_all_trades_long()
    max_date = str(long_df["Horário"].max())[:10]

    loaded_cli.run_optimization(
        min_assets=1,
        max_assets=1,
        top_n=1,
        rank_by="RetDD",
        max_correlation=1.0,
        num_workers=1,
        corr_period="D",
        show_terminal=False,
        greedy=False,
        min_metric=0.0,
        date_initial=None,
        date_final=max_date,
    )


def test_run_optimization_with_strategy_filter(loaded_cli):
    """run_optimization filters to a specific strategy subset."""
    name = loaded_cli.loaded_expert_names[0]
    loaded_cli.run_optimization(
        min_assets=1,
        max_assets=1,
        top_n=1,
        rank_by="NetProfit",
        max_correlation=1.0,
        num_workers=1,
        corr_period="D",
        show_terminal=False,
        greedy=False,
        include_strats=[name],
        min_metric=0.0,
    )


# ---------------------------------------------------------------------------
# _save_output_dir
# ---------------------------------------------------------------------------


def test_save_output_dir_creates_all_files(loaded_cli, tmp_path):
    """_save_output_dir creates rank.json, portfolios/rank_01.parquet and report.html."""
    name = loaded_cli.loaded_expert_names[0]
    mock_engine = MagicMock()
    mock_engine.best_portfolios = [{"Combo": (name,), "Net_Profit": 100.0, "RetDD": 2.0}]

    out_dir = str(tmp_path / "run_test")
    kwargs = {
        "output_dir": out_dir,
        "rank_by": "RetDD",
        "max_correlation": 1.0,
        "min_assets": 1,
        "max_assets": 1,
    }

    # Mocking generate_portfolio_report_html to avoid webbrowser open
    with patch(
        "portifoliomaster.api.cli.generate_portfolio_report_html", return_value="report.html"
    ):
        final_dir = loaded_cli._save_output_dir(mock_engine, kwargs)

    assert os.path.exists(final_dir)
    assert os.path.exists(os.path.join(final_dir, "rank.json"))
    assert os.path.exists(os.path.join(final_dir, "portfolios", "rank_01.parquet"))
    # summary.csv should NOT exist (removed previously)
    assert not os.path.exists(os.path.join(final_dir, "summary.csv"))


def test_save_output_dir_auto_timestamp(loaded_cli, tmp_path):
    """_save_output_dir creates a run_YYYY-MM-DD_HH-MM folder if output_dir is empty."""
    mock_engine = MagicMock()
    mock_engine.best_portfolios = [
        {"Combo": (loaded_cli.loaded_expert_names[0],), "Net_Profit": 10}
    ]

    original_cwd = os.getcwd()
    try:
        os.chdir(str(tmp_path))
        kwargs = {"output_dir": None}
        with patch(
            "portifoliomaster.api.cli.generate_portfolio_report_html", return_value="report.html"
        ):
            final_dir = loaded_cli._save_output_dir(mock_engine, kwargs)
        assert os.path.basename(final_dir).startswith("run_")
    finally:
        os.chdir(original_cwd)


# ---------------------------------------------------------------------------
# run_optimization edge cases
# ---------------------------------------------------------------------------


def test_run_optimization_output_dir_flag(loaded_cli, tmp_path):
    """run_optimization triggers _save_output_dir when output_dir is passed."""
    out_dir = str(tmp_path / "full_run")
    with patch(
        "portifoliomaster.api.cli.generate_portfolio_report_html", return_value="report.html"
    ):
        loaded_cli.run_optimization(
            min_assets=1,
            max_assets=1,
            top_n=1,
            rank_by="RetDD",
            max_correlation=1.0,
            output_dir=out_dir,
            num_workers=1,
        )
    assert os.path.exists(out_dir)
    assert os.path.exists(os.path.join(out_dir, "rank.json"))


def test_run_optimization_report_flag(loaded_cli, tmp_path):
    """run_optimization triggers report generation."""
    with patch("portifoliomaster.api.cli.generate_portfolio_report_html") as mock_report:
        mock_report.return_value = "report.html"
        loaded_cli.run_optimization(
            min_assets=1,
            max_assets=1,
            top_n=1,
            rank_by="RetDD",
            max_correlation=1.0,
            num_workers=1,
            plot_chart=True,
        )
        mock_report.assert_called()


def test_run_optimization_unexpected_error(loaded_cli, caplog):
    """run_optimization handles unexpected crashes gracefully."""
    with patch("portifoliomaster.api.cli.BruteForceEngine", side_effect=Exception("BOOM")):
        loaded_cli.run_optimization(
            min_assets=1,
            max_assets=1,
            top_n=1,
            rank_by="RetDD",
            max_correlation=1.0,
        )
        assert "Unexpected optimization failure" in caplog.text
