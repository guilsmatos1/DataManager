from pathlib import Path

import pytest
from trademachine.metalabelingmaster.core import process_report


def test_process_report_valid_html():
    report_path = Path(
        "components/portfoliomaster/test/trademachine/portfoliomaster/reports/USTEC_H1_DT_0063689.html"
    )

    if not report_path.exists():
        # skip if file is missing locally
        return

    df = process_report(str(report_path))

    assert not df.empty, "DataFrame should not be empty for a valid report"
    assert "entry_time" in df.columns
    assert "exit_time" in df.columns
    assert "pnl" in df.columns
    assert "meta_label" in df.columns

    assert df["meta_label"].isin([0, 1]).all(), "Meta label must be 0 or 1"

    # Check specific logic
    profitable_trades = df[df["pnl"] > 0]
    unprofitable_trades = df[df["pnl"] <= 0]

    assert (profitable_trades["meta_label"] == 1).all()
    assert (unprofitable_trades["meta_label"] == 0).all()


def test_process_report_invalid_path():
    with pytest.raises((FileNotFoundError, ValueError)):
        process_report("invalid/path/report.html")
