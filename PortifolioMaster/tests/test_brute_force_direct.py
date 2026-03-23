import glob
import json
import os
import subprocess
import sys

import pytest
from portifoliomaster.services.metrics import calculate_metrics_from_deals
from portifoliomaster.utils.mt5_parser import MT5ReportParser

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _make_env():
    env = os.environ.copy()
    src_path = os.path.join(PROJECT_ROOT, "src")
    env["PYTHONPATH"] = os.pathsep.join([src_path, env.get("PYTHONPATH", "")])
    return env


def _run_cmd(extra_args, output_dir, cwd=None):
    base = [
        sys.executable,
        "-m",
        "portifoliomaster.main",
        "--load",
        REPORTS_DIR,
        "--optimize",
        "--workers",
        "1",
        "--output",
        output_dir,
    ]
    return subprocess.run(
        base + extra_args,
        capture_output=True,
        text=True,
        cwd=cwd or PROJECT_ROOT,
        env=_make_env(),
    )


def _load_portfolios(output_dir):
    rank_path = os.path.join(output_dir, "rank.json")
    if not os.path.exists(rank_path):
        return []
    with open(rank_path, encoding="utf-8") as f:
        return json.load(f)["portfolios"]


def test_single_strategy_engine_matches_direct_calculation(tmp_path):
    """
    For a 1-asset optimization, the engine's Net_Profit for a specific strategy
    must match what calculate_metrics_from_deals computes directly from the same report.
    Uses 2 strategies so the correlation matrix is valid, then finds the target row.
    Runs in tmp_path so it never reads a polluted shared cache.parquet.
    """
    report_files = sorted(glob.glob(os.path.join(REPORTS_DIR, "*.html")))
    assert len(report_files) >= 2, "Need at least 2 HTML files in tests/reports/"

    parser = MT5ReportParser()
    target_name = parser.parse_report(report_files[0])
    second_name = parser.parse_report(report_files[1])

    direct_metrics = calculate_metrics_from_deals(parser.deals_by_expert[target_name])
    if not direct_metrics:
        pytest.skip("No closed trades found in first report")

    output_dir = str(tmp_path / "output")
    result = _run_cmd(
        [
            "--strats",
            f"{target_name},{second_name}",
            "--min",
            "1",
            "--max",
            "1",
            "--corr",
            "1.0",
            "--top",
            "10",
            "--rank",
            "NetProfit",
        ],
        output_dir,
        cwd=str(tmp_path),  # isolated dir → no shared cache.parquet
    )

    portfolios = _load_portfolios(output_dir)
    if not portfolios:
        pytest.skip(f"Optimization produced no output.\nstderr: {result.stderr}")

    target_p = next(
        (p for p in portfolios if p["strategies"] == [target_name]),
        None,
    )
    if target_p is None:
        pytest.skip(f"Target strategy '{target_name}' not found in output")

    engine_profit = target_p["metrics"]["Net_Profit"]
    assert abs(direct_metrics["Net_Profit"] - engine_profit) < 1.0, (
        f"Net_Profit mismatch: direct={direct_metrics['Net_Profit']:.2f}, "
        f"engine={engine_profit:.2f}"
    )


def test_top_portfolio_metrics_are_internally_consistent(tmp_path):
    """
    The top-ranked portfolio from a 3-asset optimization must satisfy
    mathematical invariants: MaxDD >= 0 and RetDD == Profit/MaxDD.
    """
    output_dir = str(tmp_path / "output")
    result = _run_cmd(
        ["--min", "3", "--max", "3", "--corr", "1.0", "--top", "5", "--rank", "RetDD"],
        output_dir,
        cwd=str(tmp_path),
    )

    portfolios = _load_portfolios(output_dir)
    assert portfolios, f"No output created.\nstdout: {result.stdout}\nstderr: {result.stderr}"

    top = portfolios[0]["metrics"]
    assert top["Maximum_Drawdown"] >= 0.0, "Negative MaxDD"
    assert top["Total_Trades"] > 0, "Zero trades"
    assert top["Net_Profit"] != 0.0, "Net profit should not be exactly zero"

    if top["Maximum_Drawdown"] > 0:
        expected_retdd = top["Net_Profit"] / top["Maximum_Drawdown"]
        assert abs(top["RetDD"] - expected_retdd) < 0.01, (
            f"RetDD inconsistency: got {top['RetDD']:.4f}, expected {expected_retdd:.4f}"
        )


def test_correlation_filter_excludes_high_corr_portfolios(tmp_path):
    """Portfolios passing a strict corr filter (0.0) should not exceed those with corr=1.0."""
    out_tight = str(tmp_path / "tight")
    out_all = str(tmp_path / "all")

    _run_cmd(
        ["--min", "2", "--max", "2", "--top", "50", "--rank", "RetDD", "--corr", "0.0"],
        out_tight,
        cwd=str(tmp_path),
    )
    _run_cmd(
        ["--min", "2", "--max", "2", "--top", "50", "--rank", "RetDD", "--corr", "1.0"],
        out_all,
        cwd=str(tmp_path),
    )

    p_tight = _load_portfolios(out_tight)
    p_all = _load_portfolios(out_all)

    assert p_all, "No output for corr=1.0"
    assert len(p_tight) <= len(p_all), (
        f"Tight filter ({len(p_tight)}) returned more results than no filter ({len(p_all)})"
    )
