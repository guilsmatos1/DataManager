"""Tests for trademachine.portfoliomaster.utils.sqx_parser."""

import os
from unittest.mock import patch

import numpy as np
import pytest
from trademachine.portfoliomaster.utils.sqx_parser import (
    parse_sqx_csv,
    parse_sqx_directory,
)

_TEST_DIR = os.path.dirname(__file__)
_SQX_DIR = os.path.join(_TEST_DIR, "reports-sqx")

# ── Helpers ──────────────────────────────────────────────────────────────────

_SQX_HEADER = (
    '"Ticket";"Symbol";"Type";"Open time";"Open price";"Size";'
    '"Close time";"Close price";"Profit/Loss";"Balance";'
    '"Sample type";"Close type";"MAE ($)";"MAE (pips)";"MFE ($)";'
    '"Time in trade";"Comment";"Close type";"Close time";"Comm/Swap"'
)


def _make_sqx_row(
    ticket: int = 1,
    close_time: str = "2020.01.01 12:00:00",
    profit: str = "100.00",
    comm_swap: str = "-5.00",
) -> str:
    return (
        f'"{ticket}";"USTEC";"Buy";"2020.01.01 10:00:00";"10000.00";"1.0";'
        f'"{close_time}";"10100.00";"{profit}";"100100.00";'
        f'"IST";"SL";"-10.00";"100.00";"150.00";"2h 0m";"";'
        f'"SL";"{close_time}";"{comm_swap}"'
    )


def _write_csv(tmp_path, filename: str, rows: list[str]) -> str:
    content = "\n".join([_SQX_HEADER, *rows])
    filepath = tmp_path / filename
    filepath.write_text(content)
    return str(filepath)


# ── parse_sqx_csv ───────────────────────────────────────────────────────────


def test_parse_single_trade(tmp_path):
    filepath = _write_csv(tmp_path, "strat_a.csv", [_make_sqx_row()])
    name, returns, timestamps = parse_sqx_csv(filepath)

    assert name == "strat_a"
    assert len(returns) == 1
    np.testing.assert_almost_equal(returns[0], 95.0)  # 100 + (-5)
    assert timestamps == ["2020.01.01 12:00:00"]


def test_parse_multiple_trades(tmp_path):
    rows = [
        _make_sqx_row(ticket=1, profit="200.00", comm_swap="-10.00"),
        _make_sqx_row(ticket=2, profit="-50.00", comm_swap="-3.00"),
    ]
    filepath = _write_csv(tmp_path, "multi.csv", rows)
    name, returns, timestamps = parse_sqx_csv(filepath)

    assert name == "multi"
    assert len(returns) == 2
    np.testing.assert_almost_equal(returns[0], 190.0)
    np.testing.assert_almost_equal(returns[1], -53.0)


def test_parse_empty_csv(tmp_path):
    filepath = _write_csv(tmp_path, "empty.csv", [])
    name, returns, timestamps = parse_sqx_csv(filepath)

    assert name == "empty"
    assert len(returns) == 0
    assert timestamps == []


def test_parse_returns_float64(tmp_path):
    filepath = _write_csv(tmp_path, "dtype.csv", [_make_sqx_row()])
    _, returns, _ = parse_sqx_csv(filepath)
    assert returns.dtype == np.float64


def test_parse_invalid_file_raises(tmp_path):
    filepath = _write_csv(tmp_path, "bad.csv", [_make_sqx_row()])
    with patch("pandas.read_csv", side_effect=Exception("boom")):
        with pytest.raises(ValueError, match="Failed to read SQX CSV"):
            parse_sqx_csv(filepath)


def test_parse_binary_garbage_returns_empty(tmp_path):
    bad = tmp_path / "garbage.csv"
    bad.write_bytes(b"\x00\x01\x02\x03")
    name, returns, timestamps = parse_sqx_csv(str(bad))
    assert name == "garbage"
    assert len(returns) == 0


def test_parse_too_few_columns_raises(tmp_path):
    bad = tmp_path / "few_cols.csv"
    bad.write_text("a;b;c\n1;2;3\n")
    with pytest.raises(IndexError):
        parse_sqx_csv(str(bad))


def test_strategy_name_from_stem(tmp_path):
    filepath = _write_csv(tmp_path, "USTEC_H1_DT_0063689.csv", [_make_sqx_row()])
    name, _, _ = parse_sqx_csv(filepath)
    assert name == "USTEC_H1_DT_0063689"


# ── parse_sqx_directory ─────────────────────────────────────────────────────


def test_directory_parses_multiple_files(tmp_path):
    _write_csv(tmp_path, "a.csv", [_make_sqx_row(profit="10.00", comm_swap="0.00")])
    _write_csv(tmp_path, "b.csv", [_make_sqx_row(profit="20.00", comm_swap="0.00")])

    result = parse_sqx_directory(str(tmp_path))

    assert set(result.keys()) == {"a", "b"}
    np.testing.assert_almost_equal(result["a"][0][0], 10.0)
    np.testing.assert_almost_equal(result["b"][0][0], 20.0)


def test_directory_skips_bad_files(tmp_path):
    _write_csv(tmp_path, "good.csv", [_make_sqx_row()])
    _write_csv(tmp_path, "bad.csv", [_make_sqx_row()])

    original_parse = parse_sqx_csv

    def _patched(filepath):
        if "bad.csv" in filepath:
            raise ValueError("simulated parse failure")
        return original_parse(filepath)

    with patch(
        "trademachine.portfoliomaster.utils.sqx_parser.parse_sqx_csv",
        side_effect=_patched,
    ):
        result = parse_sqx_directory(str(tmp_path))

    assert "good" in result
    assert "bad" not in result


def test_directory_not_found_raises():
    with pytest.raises(ValueError, match="SQX directory not found"):
        parse_sqx_directory("/nonexistent/path")


def test_directory_empty(tmp_path):
    result = parse_sqx_directory(str(tmp_path))
    assert result == {}


# ── Real SQX test data ──────────────────────────────────────────────────────


def test_real_sqx_files_parse():
    """Sanity check: all real SQX CSV files in test data parse without error."""
    import glob

    csv_files = glob.glob(os.path.join(_SQX_DIR, "*.csv"))
    assert csv_files, f"No CSV files found in {_SQX_DIR}"

    for filepath in csv_files:
        name, returns, timestamps = parse_sqx_csv(filepath)
        assert name
        assert len(returns) > 0
        assert len(returns) == len(timestamps)
        assert returns.dtype == np.float64


def test_real_sqx_directory_parse():
    result = parse_sqx_directory(_SQX_DIR)
    assert len(result) > 0
    for _name, (returns, timestamps) in result.items():
        assert len(returns) == len(timestamps)
