import json
import os
from unittest.mock import patch

import numpy as np
import pytest

from portifoliomaster.api.cli import PortifolioCLI
from portifoliomaster.services.adherence import (
    AdherenceResult,
    StrategyAdherence,
    _daily_pnl,
    _pearson_daily,
    adherence_result_to_dict,
    run_adherence_check,
)
from portifoliomaster.utils.sqx_parser import parse_sqx_csv, parse_sqx_directory
from portifoliomaster.utils.visualizer import generate_adherence_report_html

# Paths for real data testing
REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")
REPORTS_SQX_DIR = os.path.join(os.path.dirname(__file__), "reports-sqx")

# --- Internal Helper Tests ---


def test_daily_pnl():
    """Test grouping trade returns by calendar date."""
    returns = np.array([10.0, 5.0, -3.0, 8.0])
    # Mixed formats: YYYY-MM-DD and YYYY.MM.DD
    timestamps = [
        "2023-01-01 10:00:00",
        "2023.01.01 11:00:00",
        "2023-01-02 09:00:00",
        "2023.01.03 15:00:00",
    ]
    daily = _daily_pnl(returns, timestamps)

    assert daily["2023-01-01"] == 15.0  # 10 + 5
    assert daily["2023-01-02"] == -3.0
    assert daily["2023-01-03"] == 8.0
    assert len(daily) == 3


def test_pearson_daily():
    """Test Pearson correlation calculation between two daily P&L dicts."""
    # Perfect correlation
    d1 = {
        "2023-01-01": 10.0,
        "2023-01-02": 20.0,
        "2023-01-03": 30.0,
        "2023-01-04": 40.0,
        "2023-01-05": 50.0,
    }
    d2 = {
        "2023-01-01": 1.0,
        "2023-01-02": 2.0,
        "2023-01-03": 3.0,
        "2023-01-04": 4.0,
        "2023-01-05": 5.0,
    }
    r, n = _pearson_daily(d1, d2)
    assert n == 5
    assert r == pytest.approx(1.0)

    # Too few common days (<5)
    d3 = {
        "2023-01-01": 10.0,
        "2023-01-02": 20.0,
        "2023-01-03": 30.0,
        "2023-01-04": 40.0,
    }
    r, n = _pearson_daily(d3, d2)
    assert n == 4
    assert r == 0.0

    # Zero variance in one side
    d4 = {
        "2023-01-01": 10.0,
        "2023-01-02": 10.0,
        "2023-01-03": 10.0,
        "2023-01-04": 10.0,
        "2023-01-05": 10.0,
    }
    r, n = _pearson_daily(d4, d2)
    assert n == 5
    assert r == 0.0


# --- SQX Parser Tests ---


def test_parse_sqx_csv_valid(tmp_path):
    """Test parsing a valid SQX CSV file."""
    csv_content = (
        '"Ticket";"Symbol";"Type";"Open time";"Open price";"Size";"Close time";"Close price";'
        '"Profit/Loss";"Balance";"Sample type";"Close type";"MAE ($)";"MAE (pips)";"MFE ($)";'
        '"Time in trade";"Comment";"Close type";"Close time";"Comm/Swap"\n'
        '"1";"SYM";"Buy";"2023.01.01 10:00:00";"100.0";"1.0";"2023.01.01 11:00:00";"110.0";"10.0";"110.0";"IST";"TP";"0";"0";"10";"1h";"";"TP";"2023.01.01 11:00:00";"-1.0"\n'
        '"2";"SYM";"Sell";"2023.01.02 10:00:00";"110.0";"1.0";"2023.01.02 11:00:00";"100.0";"10.0";"120.0";"IST";"TP";"0";"0";"10";"1h";"";"TP";"2023.01.02 11:00:00";"-1.0"\n'
    )
    csv_file = tmp_path / "test_strategy.csv"
    csv_file.write_text(csv_content)

    name, returns, timestamps = parse_sqx_csv(str(csv_file))

    assert name == "test_strategy"
    assert len(returns) == 2
    assert np.allclose(returns, [9.0, 9.0])  # 10.0 + (-1.0)
    assert timestamps == ["2023.01.01 11:00:00", "2023.01.02 11:00:00"]


def test_parse_sqx_csv_empty(tmp_path):
    """Test parsing an empty SQX CSV file (only header)."""
    csv_content = '"Ticket";"Symbol";"Type";"Open time";"Open price";"Size";"Close time";"Close price";"Profit/Loss";"Balance";"Sample type";"Close type";"MAE ($)";"MAE (pips)";"MFE ($)";"Time in trade";"Comment";"Close type";"Close time";"Comm/Swap"\n'
    csv_file = tmp_path / "empty.csv"
    csv_file.write_text(csv_content)

    name, returns, timestamps = parse_sqx_csv(str(csv_file))
    assert name == "empty"
    assert len(returns) == 0
    assert timestamps == []


def test_parse_sqx_csv_invalid_file():
    """Test parsing a non-existent SQX CSV file."""
    with pytest.raises(ValueError, match="Failed to read SQX CSV"):
        parse_sqx_csv("non_existent.csv")


def test_parse_sqx_directory_valid(tmp_path):
    """Test parsing a directory with valid SQX files."""
    (tmp_path / "strat1.csv").write_text(
        '"Ticket";"Symbol";"Type";"Open time";"Open price";"Size";"Close time";"Close price";"Profit/Loss";"Balance";"Sample type";"Close type";"MAE ($)";"MAE (pips)";"MFE ($)";"Time in trade";"Comment";"Close type";"Close time";"Comm/Swap"\n"1";"S1";"Buy";"T1";"10";"1";"2023.01.01 10:00";"11";"1.0";"101";"IST";"TP";"0";"0";"1";"1h";"";"TP";"2023.01.01 10:00";"0.0"'
    )
    (tmp_path / "strat2.csv").write_text(
        '"Ticket";"Symbol";"Type";"Open time";"Open price";"Size";"Close time";"Close price";"Profit/Loss";"Balance";"Sample type";"Close type";"MAE ($)";"MAE (pips)";"MFE ($)";"Time in trade";"Comment";"Close type";"Close time";"Comm/Swap"\n"1";"S2";"Buy";"T1";"20";"1";"2023.01.02 10:00";"22";"2.0";"102";"IST";"TP";"0";"0";"2";"1h";"";"TP";"2023.01.02 10:00";"0.0"'
    )
    (tmp_path / "not_a_csv.txt").write_text("something")

    result = parse_sqx_directory(str(tmp_path))
    assert len(result) == 2
    assert "strat1" in result
    assert "strat2" in result
    assert len(result["strat1"][0]) == 1
    assert result["strat1"][0][0] == 1.0


def test_parse_sqx_directory_not_found():
    """Test parsing a non-existent directory."""
    with pytest.raises(ValueError, match="SQX directory not found"):
        parse_sqx_directory("/tmp/non_existent_dir_12345")


# --- Adherence Service Tests ---


def test_run_adherence_check_real_data():
    """Test run_adherence_check using real data from tests/reports and tests/reports-sqx."""
    # Ensure directories exist
    assert os.path.isdir(REPORTS_DIR)
    assert os.path.isdir(REPORTS_SQX_DIR)

    # Run adherence check on a subset or all
    # To keep it fast, we can mock _load_mt5_strategies and parse_sqx_directory
    # but here we are asked to use real data.
    result = run_adherence_check(REPORTS_DIR, REPORTS_SQX_DIR, threshold=0.8)

    assert isinstance(result, AdherenceResult)
    assert result.total > 0
    assert result.threshold == 0.8
    assert len(result.strategies) == result.total

    # Verify at least one strategy
    sample = result.strategies[0]
    assert sample.name != ""
    assert sample.mt5_trades > 0
    assert sample.sqx_trades > 0
    assert len(sample.mt5_equity) == sample.mt5_trades + 1
    assert len(sample.sqx_equity) == sample.sqx_trades + 1


def test_run_adherence_check_mismatch(tmp_path):
    """Test run_adherence_check with mismatched strategies between directories."""
    mt5_dir = tmp_path / "mt5"
    sqx_dir = tmp_path / "sqx"
    mt5_dir.mkdir()
    sqx_dir.mkdir()

    # Create one matching strategy and one mismatch on each side
    # We need to mock _load_mt5_strategies and parse_sqx_directory to avoid creating real HTML/CSV
    with (
        patch("portifoliomaster.services.adherence._load_mt5_strategies") as mock_mt5,
        patch("portifoliomaster.services.adherence.parse_sqx_directory") as mock_sqx,
    ):
        # 6 trades on 6 different days — enough for Pearson (needs >=5 common days)
        # MT5 and SQX have identical daily P&L pattern → pearson ≈ 1.0
        days_mt5 = [
            "2023-01-01",
            "2023-01-02",
            "2023-01-03",
            "2023-01-04",
            "2023-01-05",
            "2023-01-06",
        ]
        days_sqx = [
            "2023-01-01",
            "2023-01-02",
            "2023-01-03",
            "2023-01-04",
            "2023-01-05",
            "2023-01-06",
        ]
        mt5_ret = np.array([10.0, -5.0, 8.0, -3.0, 6.0, -2.0])
        sqx_ret = np.array(
            [9.0, -4.5, 7.2, -2.7, 5.4, -1.8]
        )  # proportional → pearson=1.0
        mock_mt5.return_value = (
            {"match": mt5_ret, "only_mt5": np.array([5.0])},
            {"match": days_mt5, "only_mt5": ["2023-01-01"]},
        )
        mock_sqx.return_value = {
            "match": (sqx_ret, days_sqx),
            "only_sqx": (np.array([4.0]), ["2023-01-01"]),
        }

        result = run_adherence_check(str(mt5_dir), str(sqx_dir))

        assert result.total == 1
        assert result.strategies[0].name == "match"
        assert result.strategies[0].trade_ratio == 1.0
        assert result.strategies[0].retdd_ratio == 1.0
        assert result.strategies[0].pearson >= 0.99
        assert result.strategies[0].passes is True


def test_run_adherence_check_failure_threshold(tmp_path):
    """Test run_adherence_check where a strategy fails the threshold."""
    with (
        patch("portifoliomaster.services.adherence._load_mt5_strategies") as mock_mt5,
        patch("portifoliomaster.services.adherence.parse_sqx_directory") as mock_sqx,
    ):
        # MT5: 10 trades, SQX: 7 trades -> 0.7 ratio < 0.8 threshold
        mock_mt5.return_value = (
            {"fail": np.ones(10) * 10.0},
            {"fail": ["2023-01-01"] * 10},
        )
        mock_sqx.return_value = {"fail": (np.ones(7) * 10.0, ["2023-01-01"] * 7)}

        result = run_adherence_check("dir1", "dir2", threshold=0.8)

        assert result.total == 1
        assert result.passed == 0
        assert result.failed == 1
        assert result.strategies[0].passes is False
        assert result.strategies[0].trade_ratio == 0.7


def test_adherence_result_to_dict():
    """Test conversion of AdherenceResult to a dictionary."""
    strat = StrategyAdherence(
        name="test",
        mt5_trades=10,
        sqx_trades=9,
        mt5_win_rate=0.6,
        sqx_win_rate=0.55,
        win_rate_ratio=0.917,
        pearson=0.99,
        common_days=8,
        mt5_profit=100.0,
        sqx_profit=90.0,
        mt5_maxdd=10.0,
        sqx_maxdd=11.0,
        mt5_retdd=10.0,
        sqx_retdd=8.18,
        trade_ratio=0.9,
        retdd_ratio=0.818,
        passes=True,
        mt5_equity=np.array([0, 10, 20]),
        sqx_equity=np.array([0, 9, 18]),
        mt5_timestamps=["T1", "T2"],
        sqx_timestamps=["T1", "T2"],
    )
    res = AdherenceResult(
        strategies=[strat],
        total=1,
        passed=1,
        failed=0,
        pass_rate=100.0,
        threshold=0.8,
        pearson_threshold=0.85,
    )

    d = adherence_result_to_dict(res)

    assert d["summary"]["total"] == 1
    assert d["summary"]["pass_rate"] == 100.0
    assert d["config"]["threshold"] == 0.8
    assert len(d["strategies"]) == 1
    assert d["strategies"][0]["name"] == "test"
    assert d["strategies"][0]["passes"] is True
    # Equity arrays should NOT be in the dict
    assert "mt5_equity" not in d["strategies"][0]
    assert "sqx_equity" not in d["strategies"][0]
    assert "generated_at" in d


# --- CLI and Visualizer Integration Tests ---


def test_adherence_run_cli(tmp_path):
    """Test PortifolioCLI.adherence_run with mocked backend."""
    cli = PortifolioCLI()
    # Mock the results of run_adherence_check
    strat = StrategyAdherence(
        name="MockStrat",
        mt5_trades=10,
        sqx_trades=10,
        trade_ratio=1.0,
        mt5_win_rate=0.5,
        sqx_win_rate=0.5,
        win_rate_ratio=1.0,
        pearson=1.0,
        common_days=10,
        mt5_profit=100.0,
        sqx_profit=100.0,
        mt5_maxdd=10.0,
        sqx_maxdd=10.0,
        mt5_retdd=10.0,
        sqx_retdd=10.0,
        retdd_ratio=1.0,
        passes=True,
        mt5_equity=np.zeros(11),
        sqx_equity=np.zeros(11),
        mt5_timestamps=["T"] * 10,
        sqx_timestamps=["T"] * 10,
    )
    mock_result = AdherenceResult(
        strategies=[strat],
        total=1,
        passed=1,
        failed=0,
        pass_rate=100.0,
        threshold=0.8,
        pearson_threshold=0.85,
    )

    with (
        patch("portifoliomaster.api.cli.run_adherence_check", return_value=mock_result),
        patch(
            "portifoliomaster.api.cli.generate_adherence_report_html"
        ) as mock_gen_html,
    ):
        cli.adherence_run(
            mt5_dir="mock_mt5",
            sqx_dir="mock_sqx",
            output_dir=str(tmp_path),
            open_browser=False,
        )

        # Check if JSON was created inside the output directory
        results_json = tmp_path / "results.json"
        assert results_json.exists()
        with open(results_json) as f:
            data = json.load(f)
            assert data["summary"]["total"] == 1
            assert data["strategies"][0]["name"] == "MockStrat"

        # Check if generate_adherence_report_html was called with path inside output_dir
        expected_html = os.path.join(str(tmp_path), "adherence_report.html")
        mock_gen_html.assert_called_once_with(mock_result, expected_html, False)


def test_adherence_run_auto_output_dir(tmp_path):
    """Without output_dir, adherence_run always creates an auto-timestamped folder with
    both results.json and adherence_report.html inside."""
    cli = PortifolioCLI()
    strat = StrategyAdherence(
        name="S",
        mt5_trades=10,
        sqx_trades=10,
        trade_ratio=1.0,
        mt5_win_rate=0.5,
        sqx_win_rate=0.5,
        win_rate_ratio=1.0,
        pearson=1.0,
        common_days=10,
        mt5_profit=100.0,
        sqx_profit=100.0,
        mt5_maxdd=10.0,
        sqx_maxdd=10.0,
        mt5_retdd=10.0,
        sqx_retdd=10.0,
        retdd_ratio=1.0,
        passes=True,
        mt5_equity=np.zeros(11),
        sqx_equity=np.zeros(11),
        mt5_timestamps=["T"] * 10,
        sqx_timestamps=["T"] * 10,
    )
    mock_result = AdherenceResult(
        strategies=[strat],
        total=1,
        passed=1,
        failed=0,
        pass_rate=100.0,
        threshold=0.8,
        pearson_threshold=0.85,
    )

    orig_dir = os.getcwd()
    os.chdir(tmp_path)
    try:
        with (
            patch(
                "portifoliomaster.api.cli.run_adherence_check", return_value=mock_result
            ),
            patch(
                "portifoliomaster.api.cli.generate_adherence_report_html"
            ) as mock_html,
        ):
            cli.adherence_run(
                mt5_dir="m", sqx_dir="s", output_dir=None, open_browser=False
            )

        # An auto-named folder starting with "adherence_" must exist
        created = [
            p
            for p in tmp_path.iterdir()
            if p.is_dir() and p.name.startswith("adherence_")
        ]
        assert len(created) == 1, f"Expected 1 adherence_* dir, got: {created}"
        out_dir = created[0]

        # results.json must be inside
        assert (out_dir / "results.json").exists()
        with open(out_dir / "results.json") as f:
            data = json.load(f)
        assert data["summary"]["total"] == 1

        # HTML must have been written inside the same folder
        html_call_path = mock_html.call_args[0][1]
        assert out_dir.name in html_call_path
    finally:
        os.chdir(orig_dir)


def test_generate_adherence_report_html(tmp_path):
    """Test HTML report generation without error."""
    strat = StrategyAdherence(
        name="TestStrat",
        mt5_trades=2,
        sqx_trades=2,
        trade_ratio=1.0,
        mt5_win_rate=0.5,
        sqx_win_rate=0.5,
        win_rate_ratio=1.0,
        pearson=1.0,
        common_days=2,
        mt5_profit=100.0,
        sqx_profit=100.0,
        mt5_maxdd=10.0,
        sqx_maxdd=10.0,
        mt5_retdd=10.0,
        sqx_retdd=10.0,
        retdd_ratio=1.0,
        passes=True,
        mt5_equity=np.array([0, 10, 20]),
        sqx_equity=np.array([0, 10, 20]),
        mt5_timestamps=["2023.01.01", "2023.01.02"],
        sqx_timestamps=["2023.01.01", "2023.01.02"],
    )
    res = AdherenceResult(
        strategies=[strat],
        total=1,
        passed=1,
        failed=0,
        pass_rate=100.0,
        threshold=0.8,
        pearson_threshold=0.85,
    )

    report_file = tmp_path / "test_report.html"
    path = generate_adherence_report_html(res, str(report_file), open_browser=False)

    assert os.path.exists(path)
    with open(path) as f:
        content = f.read()
        assert "Adherence Report" in content
        assert "TestStrat" in content
        assert "PASS" in content
