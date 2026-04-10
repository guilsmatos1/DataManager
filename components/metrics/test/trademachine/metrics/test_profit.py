"""Golden tests for profit formulas.

Values verified by hand:
  trades pnls = [100, -50, 200, -75, 150]
  initial_capital = 10_000
  ending_capital  = 10_000 + 325 = 10_325
  period: 2025-01-01 to 2026-01-01 (365 days = 1 year exactly via 365.25 calc)
"""

from __future__ import annotations

from datetime import datetime

import pytest
from trademachine.metrics.formulas.profit import (
    average_loss,
    average_trade,
    average_win,
    daily_avg_profit,
    gross_loss,
    gross_profit,
    monthly_avg_profit,
    total_profit,
    yearly_avg_profit,
)

PNLS = [100.0, -50.0, 200.0, -75.0, 150.0]
START = datetime(2025, 1, 1)
END = datetime(2026, 1, 1)  # 365 days


class TestTotalProfit:
    def test_positive(self) -> None:
        assert total_profit(10_325.0, 10_000.0) == pytest.approx(325.0)

    def test_negative(self) -> None:
        assert total_profit(9_500.0, 10_000.0) == pytest.approx(-500.0)

    def test_zero(self) -> None:
        assert total_profit(10_000.0, 10_000.0) == pytest.approx(0.0)


class TestGrossProfitLoss:
    def test_gross_profit(self) -> None:
        assert gross_profit(PNLS) == pytest.approx(450.0)  # 100+200+150

    def test_gross_loss(self) -> None:
        assert gross_loss(PNLS) == pytest.approx(-125.0)  # -50-75

    def test_no_wins(self) -> None:
        assert gross_profit([-10.0, -20.0]) == pytest.approx(0.0)

    def test_no_losses(self) -> None:
        assert gross_loss([10.0, 20.0]) == pytest.approx(0.0)


class TestAverages:
    def test_average_win(self) -> None:
        # wins: 100, 200, 150 → avg = 450/3 = 150
        assert average_win(PNLS) == pytest.approx(150.0)

    def test_average_loss(self) -> None:
        # losses: -50, -75 → avg = -125/2 = -62.5
        assert average_loss(PNLS) == pytest.approx(-62.5)

    def test_average_trade(self) -> None:
        # total = 325, count = 5 → 65
        assert average_trade(PNLS) == pytest.approx(65.0)

    def test_average_win_no_wins(self) -> None:
        assert average_win([-10.0]) is None

    def test_average_loss_no_losses(self) -> None:
        assert average_loss([10.0]) is None

    def test_average_trade_empty(self) -> None:
        assert average_trade([]) is None


class TestPeriodAverages:
    # 365 calendar days → years ≈ 365/365.25
    # profit = 325

    def test_daily_avg_profit(self) -> None:
        expected = 325.0 / 365.0
        assert daily_avg_profit(325.0, START, END) == pytest.approx(expected, rel=1e-3)

    def test_monthly_avg_profit(self) -> None:
        from trademachine.metrics.utils.time import months_between

        months = months_between(START, END)
        expected = 325.0 / months
        assert monthly_avg_profit(325.0, START, END) == pytest.approx(
            expected, rel=1e-6
        )

    def test_yearly_avg_profit(self) -> None:
        from trademachine.metrics.utils.time import years_between

        years = years_between(START, END)
        expected = 325.0 / years
        assert yearly_avg_profit(325.0, START, END) == pytest.approx(expected, rel=1e-6)

    def test_zero_period_returns_none(self) -> None:
        t = datetime(2025, 6, 1)
        assert daily_avg_profit(100.0, t, t) is None
        assert monthly_avg_profit(100.0, t, t) is None
        assert yearly_avg_profit(100.0, t, t) is None
