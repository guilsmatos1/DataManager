"""Golden tests for returns formulas."""

from __future__ import annotations

from datetime import datetime

import pytest
from trademachine.metrics.formulas.returns import (
    annual_over_maxdd,
    cagr,
    yearly_avg_return_pct,
)

START = datetime(2025, 1, 1)
END = datetime(2026, 1, 1)


class TestYearlyAvgReturnPct:
    def test_basic(self) -> None:
        # profit=325, initial=10_000 → 0.0325
        assert yearly_avg_return_pct(325.0, 10_000.0) == pytest.approx(0.0325)

    def test_zero_initial_capital(self) -> None:
        assert yearly_avg_return_pct(100.0, 0.0) is None

    def test_negative_return(self) -> None:
        assert yearly_avg_return_pct(-500.0, 10_000.0) == pytest.approx(-0.05)


class TestCAGR:
    def test_one_year_growth(self) -> None:
        # 10_000 → 10_325 over ~1 year → CAGR ≈ 3.25%
        result = cagr(10_000.0, 10_325.0, START, END)
        assert result == pytest.approx(0.0325, rel=1e-3)

    def test_zero_period(self) -> None:
        t = datetime(2025, 6, 1)
        assert cagr(10_000.0, 10_325.0, t, t) is None

    def test_non_positive_capital(self) -> None:
        assert cagr(0.0, 10_000.0, START, END) is None
        assert cagr(10_000.0, 0.0, START, END) is None

    def test_two_year_doubling(self) -> None:
        start = datetime(2023, 1, 1)
        end = datetime(2025, 1, 1)
        # 10_000 → 20_000 over 2 years → CAGR = 2^(1/2) - 1 ≈ 41.42%
        result = cagr(10_000.0, 20_000.0, start, end)
        assert result == pytest.approx(2**0.5 - 1, rel=1e-3)


class TestAnnualOverMaxDD:
    def test_basic(self) -> None:
        # CAGR=0.10, DD%=0.05 → ratio=2.0
        assert annual_over_maxdd(0.10, 0.05) == pytest.approx(2.0)

    def test_zero_drawdown(self) -> None:
        assert annual_over_maxdd(0.10, 0.0) is None

    def test_none_inputs(self) -> None:
        assert annual_over_maxdd(None, 0.05) is None
        assert annual_over_maxdd(0.10, None) is None

    def test_negative_cagr(self) -> None:
        # negative return / positive drawdown → negative ratio
        result = annual_over_maxdd(-0.05, 0.10)
        assert result == pytest.approx(-0.5)
