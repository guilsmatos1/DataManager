"""Tests for trademachine.portfoliomaster.services.adherence."""

import dataclasses
import os

import numpy as np
import pytest
from trademachine.portfoliomaster.services.adherence import (
    AdherenceResult,
    StrategyAdherence,
    _daily_pnl,
    _parse_date,
    _pearson_daily,
    _win_rate,
    adherence_result_to_dict,
    run_adherence_check,
)

_TEST_DIR = os.path.dirname(__file__)
_REPORTS_DIR = os.path.join(_TEST_DIR, "reports")
_SQX_DIR = os.path.join(_TEST_DIR, "reports-sqx")

# ── _win_rate ────────────────────────────────────────────────────────────────


def test_win_rate_all_positive():
    assert _win_rate(np.array([10.0, 20.0, 5.0])) == 1.0


def test_win_rate_all_negative():
    assert _win_rate(np.array([-10.0, -20.0])) == 0.0


def test_win_rate_mixed():
    result = _win_rate(np.array([10.0, -5.0, 0.0, -3.0]))
    assert result == pytest.approx(0.5)  # 10>=0, 0>=0 → 2/4


def test_win_rate_empty():
    assert _win_rate(np.array([])) == 0.0


def test_win_rate_zero_counts_as_win():
    assert _win_rate(np.array([0.0])) == 1.0


# ── _parse_date ──────────────────────────────────────────────────────────────


def test_parse_date_dash_format():
    assert _parse_date("2018-01-11 22:00:00") == "2018-01-11"


def test_parse_date_dot_format():
    assert _parse_date("2018.01.11 22:00:00") == "2018-01-11"


def test_parse_date_just_date():
    assert _parse_date("2020-06-15") == "2020-06-15"


# ── _daily_pnl ───────────────────────────────────────────────────────────────


def test_daily_pnl_groups_by_date():
    returns = np.array([10.0, 20.0, -5.0])
    timestamps = [
        "2020.01.01 10:00:00",
        "2020.01.01 14:00:00",
        "2020.01.02 10:00:00",
    ]
    result = _daily_pnl(returns, timestamps)
    assert result == {"2020-01-01": 30.0, "2020-01-02": -5.0}


def test_daily_pnl_single_trade():
    result = _daily_pnl(np.array([42.0]), ["2020-03-15 09:00:00"])
    assert result == {"2020-03-15": 42.0}


def test_daily_pnl_empty():
    result = _daily_pnl(np.array([]), [])
    assert result == {}


# ── _pearson_daily ───────────────────────────────────────────────────────────


def test_pearson_perfect_correlation():
    mt5 = {f"2020-01-{d:02d}": float(d) for d in range(1, 11)}
    sqx = {f"2020-01-{d:02d}": float(d) * 2 for d in range(1, 11)}
    r, n = _pearson_daily(mt5, sqx)
    assert r == pytest.approx(1.0)
    assert n == 10


def test_pearson_negative_correlation():
    mt5 = {f"2020-01-{d:02d}": float(d) for d in range(1, 11)}
    sqx = {f"2020-01-{d:02d}": float(-d) for d in range(1, 11)}
    r, n = _pearson_daily(mt5, sqx)
    assert r == pytest.approx(-1.0)


def test_pearson_fewer_than_5_common_days():
    mt5 = {"2020-01-01": 1.0, "2020-01-02": 2.0}
    sqx = {"2020-01-01": 1.0, "2020-01-02": 2.0}
    r, n = _pearson_daily(mt5, sqx)
    assert r == 0.0
    assert n == 2


def test_pearson_no_overlap():
    mt5 = {"2020-01-01": 1.0}
    sqx = {"2020-02-01": 1.0}
    r, n = _pearson_daily(mt5, sqx)
    assert r == 0.0
    assert n == 0


def test_pearson_zero_variance():
    mt5 = {f"2020-01-{d:02d}": 5.0 for d in range(1, 11)}
    sqx = {f"2020-01-{d:02d}": float(d) for d in range(1, 11)}
    r, n = _pearson_daily(mt5, sqx)
    assert r == 0.0
    assert n == 10


# ── StrategyAdherence / AdherenceResult dataclasses ──────────────────────────


def _make_strategy(name: str = "strat", passes: bool = True) -> StrategyAdherence:
    return StrategyAdherence(
        name=name,
        mt5_trades=100,
        sqx_trades=90,
        trade_ratio=0.9,
        mt5_win_rate=0.55,
        sqx_win_rate=0.54,
        win_rate_ratio=0.98,
        pearson=0.92,
        common_days=50,
        mt5_retdd=2.5,
        sqx_retdd=2.3,
        retdd_ratio=0.92,
        mt5_profit=1000.0,
        sqx_profit=900.0,
        mt5_maxdd=-400.0,
        sqx_maxdd=-390.0,
        passes=passes,
        mt5_equity=np.array([0.0, 10.0, 20.0]),
        sqx_equity=np.array([0.0, 9.0, 18.0]),
        mt5_timestamps=["2020-01-01 10:00:00", "2020-01-02 10:00:00"],
    )


def test_strategy_adherence_is_dataclass():
    s = _make_strategy()
    assert dataclasses.is_dataclass(s)
    assert s.name == "strat"
    assert s.passes is True


def test_adherence_result_aggregate():
    result = AdherenceResult(
        strategies=[_make_strategy("a", True), _make_strategy("b", False)],
        total=2,
        passed=1,
        failed=1,
        pass_rate=50.0,
        threshold=0.80,
        pearson_threshold=0.85,
    )
    assert result.total == 2
    assert result.passed == 1
    assert result.pass_rate == 50.0


# ── adherence_result_to_dict ─────────────────────────────────────────────────


def test_to_dict_structure():
    result = AdherenceResult(
        strategies=[_make_strategy("a", True), _make_strategy("b", False)],
        total=2,
        passed=1,
        failed=1,
        pass_rate=50.0,
        threshold=0.80,
        pearson_threshold=0.85,
    )
    d = adherence_result_to_dict(result)

    assert "generated_at" in d
    assert d["config"]["threshold"] == 0.80
    assert d["config"]["pearson_threshold"] == 0.85
    assert d["summary"]["total"] == 2
    assert d["summary"]["passed"] == 1
    assert d["summary"]["failed"] == 1
    assert d["passed_strategies"] == ["a"]
    assert d["failed_strategies"] == ["b"]
    assert len(d["strategies"]) == 2


def test_to_dict_excludes_equity():
    result = AdherenceResult(
        strategies=[_make_strategy()],
        total=1,
        passed=1,
        failed=0,
        pass_rate=100.0,
        threshold=0.80,
        pearson_threshold=0.85,
    )
    d = adherence_result_to_dict(result)
    strat = d["strategies"][0]
    assert "mt5_equity" not in strat
    assert "sqx_equity" not in strat
    assert "mt5_timestamps" not in strat


def test_to_dict_empty_result():
    result = AdherenceResult(
        strategies=[],
        total=0,
        passed=0,
        failed=0,
        pass_rate=0.0,
        threshold=0.80,
        pearson_threshold=0.85,
    )
    d = adherence_result_to_dict(result)
    assert d["strategies"] == []
    assert d["passed_strategies"] == []
    assert d["failed_strategies"] == []


# ── run_adherence_check (with real test data) ────────────────────────────────


def test_run_adherence_check_returns_result():
    result = run_adherence_check(_REPORTS_DIR, _SQX_DIR)

    assert isinstance(result, AdherenceResult)
    assert result.total > 0
    assert result.passed + result.failed == result.total
    assert 0.0 <= result.pass_rate <= 100.0
    assert result.threshold == 0.80
    assert result.pearson_threshold == 0.85


def test_run_adherence_check_strategies_have_required_fields():
    result = run_adherence_check(_REPORTS_DIR, _SQX_DIR)

    for s in result.strategies:
        assert s.mt5_trades > 0
        assert s.sqx_trades > 0
        assert 0.0 <= s.trade_ratio
        assert isinstance(s.pearson, float)
        assert s.common_days >= 0
        assert isinstance(s.mt5_equity, np.ndarray)
        assert isinstance(s.sqx_equity, np.ndarray)


def test_run_adherence_check_custom_thresholds():
    strict = run_adherence_check(
        _REPORTS_DIR, _SQX_DIR, threshold=0.99, pearson_threshold=0.99
    )
    lenient = run_adherence_check(
        _REPORTS_DIR, _SQX_DIR, threshold=0.01, pearson_threshold=0.01
    )

    assert lenient.passed >= strict.passed


def test_run_adherence_check_pass_logic():
    result = run_adherence_check(_REPORTS_DIR, _SQX_DIR)

    for s in result.strategies:
        expected = (
            s.trade_ratio >= result.threshold and s.pearson >= result.pearson_threshold
        )
        assert s.passes == expected, f"{s.name}: expected passes={expected}"


def test_run_adherence_check_no_mt5_reports(tmp_path):
    empty_mt5 = tmp_path / "mt5"
    empty_mt5.mkdir()
    with pytest.raises(ValueError, match="No MT5 HTML reports"):
        run_adherence_check(str(empty_mt5), _SQX_DIR)


def test_run_adherence_check_no_matched_strategies(tmp_path):
    """When MT5 and SQX have no overlapping strategy names, result is empty."""
    mt5_dir = tmp_path / "mt5"
    sqx_dir = tmp_path / "sqx"
    mt5_dir.mkdir()
    sqx_dir.mkdir()

    # Copy one MT5 report
    import glob as g
    import shutil

    mt5_files = g.glob(os.path.join(_REPORTS_DIR, "*.html"))[:1]
    for f in mt5_files:
        shutil.copy(f, mt5_dir / "UNIQUE_NAME_XYZ.html")

    # Create SQX CSV with different name
    sqx_header = (
        '"Ticket";"Symbol";"Type";"Open time";"Open price";"Size";'
        '"Close time";"Close price";"Profit/Loss";"Balance";'
        '"Sample type";"Close type";"MAE ($)";"MAE (pips)";"MFE ($)";'
        '"Time in trade";"Comment";"Close type";"Close time";"Comm/Swap"'
    )
    sqx_row = (
        '"1";"USTEC";"Buy";"2020.01.01 10:00:00";"10000";"1.0";'
        '"2020.01.01 12:00:00";"10100";"100.00";"100100";'
        '"IST";"SL";"-10";"100";"150";"2h";"";'
        '"SL";"2020.01.01 12:00:00";"-5.00"'
    )
    (sqx_dir / "DIFFERENT_NAME_ABC.csv").write_text(f"{sqx_header}\n{sqx_row}")

    result = run_adherence_check(str(mt5_dir), str(sqx_dir))
    assert result.total == 0
    assert result.pass_rate == 0.0


def test_adherence_result_to_dict_roundtrip():
    result = run_adherence_check(_REPORTS_DIR, _SQX_DIR)
    d = adherence_result_to_dict(result)

    assert d["summary"]["total"] == result.total
    assert d["summary"]["passed"] == result.passed
    assert len(d["strategies"]) == result.total
