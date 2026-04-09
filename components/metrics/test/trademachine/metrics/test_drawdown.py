"""Golden tests for drawdown formulas.

Equity curve used:
  [10_000, 10_100, 10_050, 10_250, 10_175, 10_325]
   idx 0    idx 1   idx 2   idx 3   idx 4   idx 5

Peaks and troughs:
  After idx 0: peak=10_000
  idx 1: 10_100 > peak → new peak=10_100
  idx 2: 10_050 < peak → DD = 10_100 - 10_050 = 50
  idx 3: 10_250 > peak → new peak=10_250
  idx 4: 10_175 < peak → DD = 10_250 - 10_175 = 75  ← max DD
  idx 5: 10_325 > peak → new peak=10_325

Max DD = 75  (absolute)
Max DD% = 75 / 10_250 ≈ 0.007317
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from trademachine.metrics.formulas.drawdown import (
    drawdown,
    drawdown_pct,
    stagnation_days,
    stagnation_pct,
)

EQUITY = [10_000.0, 10_100.0, 10_050.0, 10_250.0, 10_175.0, 10_325.0]
BASE = datetime(2025, 1, 1)
TIMESTAMPS = [BASE + timedelta(days=i * 10) for i in range(len(EQUITY))]


class TestDrawdown:
    def test_basic(self) -> None:
        assert drawdown(EQUITY) == pytest.approx(75.0)

    def test_monotone_up(self) -> None:
        assert drawdown([100.0, 110.0, 120.0]) == pytest.approx(0.0)

    def test_monotone_down(self) -> None:
        # peak=100, min=70 → DD=30
        assert drawdown([100.0, 90.0, 70.0]) == pytest.approx(30.0)

    def test_single_point(self) -> None:
        assert drawdown([10_000.0]) is None

    def test_empty(self) -> None:
        assert drawdown([]) is None


class TestDrawdownPct:
    def test_basic(self) -> None:
        # 75 / 10_250 ≈ 0.007317
        expected = 75.0 / 10_250.0
        assert drawdown_pct(EQUITY) == pytest.approx(expected, rel=1e-5)

    def test_monotone_up(self) -> None:
        assert drawdown_pct([100.0, 110.0, 120.0]) == pytest.approx(0.0)

    def test_single_point(self) -> None:
        assert drawdown_pct([10_000.0]) is None

    def test_zero_peak_skipped(self) -> None:
        # Peak starts at 0 — division guarded, then rises; no drawdown recorded
        assert drawdown_pct([0.0, 100.0, 90.0]) == pytest.approx(0.1)

    def test_zero_equity_no_division_error(self) -> None:
        # Both points at 0 — peak == 0 guard prevents ZeroDivisionError
        assert drawdown_pct([0.0, 0.0]) == pytest.approx(0.0)


class TestStagnationDays:
    def test_basic(self) -> None:
        # Peak at idx 3 (day 30), next peak at idx 5 (day 50).
        # Stagnation window: day 30 → day 40 (idx 4 still below peak) = 10 days.
        result = stagnation_days(EQUITY, TIMESTAMPS)
        assert result == 10

    def test_all_new_highs(self) -> None:
        ts = [BASE + timedelta(days=i) for i in range(3)]
        assert stagnation_days([100.0, 110.0, 120.0], ts) == 0

    def test_mismatched_lengths(self) -> None:
        assert stagnation_days(EQUITY, TIMESTAMPS[:3]) is None

    def test_single_point(self) -> None:
        assert stagnation_days([100.0], [BASE]) is None


class TestStagnationPct:
    def test_basic(self) -> None:
        # total period = 50 days, max stagnation = 10 days → 0.20
        result = stagnation_pct(EQUITY, TIMESTAMPS)
        assert result == pytest.approx(0.20)

    def test_zero_period(self) -> None:
        ts = [BASE, BASE]
        assert stagnation_pct([100.0, 90.0], ts) is None

    def test_single_point(self) -> None:
        assert stagnation_pct([100.0], [BASE]) is None
