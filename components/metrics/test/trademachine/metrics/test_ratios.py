"""Golden tests for ratio formulas."""

from __future__ import annotations

import pytest
from trademachine.metrics.formulas.ratios import (
    payout_ratio,
    profit_factor,
    return_dd_ratio,
    winning_pct,
    wins_losses_ratio,
)

PNLS = [100.0, -50.0, 200.0, -75.0, 150.0]
# wins: 100, 200, 150 → gross_profit=450
# losses: -50, -75  → gross_loss=125


class TestProfitFactor:
    def test_basic(self) -> None:
        # 450 / 125 = 3.6
        assert profit_factor(PNLS) == pytest.approx(3.6)

    def test_no_losses(self) -> None:
        assert profit_factor([100.0, 200.0]) is None

    def test_all_losses(self) -> None:
        assert profit_factor([-10.0, -20.0]) == pytest.approx(0.0)

    def test_equal(self) -> None:
        assert profit_factor([100.0, -100.0]) == pytest.approx(1.0)


class TestReturnDDRatio:
    def test_basic(self) -> None:
        # profit=325, drawdown=200 → 1.625
        assert return_dd_ratio(325.0, 200.0) == pytest.approx(1.625)

    def test_zero_drawdown(self) -> None:
        assert return_dd_ratio(325.0, 0.0) is None

    def test_negative_profit(self) -> None:
        result = return_dd_ratio(-100.0, 200.0)
        assert result == pytest.approx(-0.5)


class TestPayoutRatio:
    def test_basic(self) -> None:
        # avg_win=150, avg_loss=-62.5 → 150/62.5 = 2.4
        assert payout_ratio(150.0, -62.5) == pytest.approx(2.4)

    def test_zero_avg_loss(self) -> None:
        assert payout_ratio(150.0, 0.0) is None

    def test_none_inputs(self) -> None:
        assert payout_ratio(None, -62.5) is None
        assert payout_ratio(150.0, None) is None


class TestWinsLossesRatio:
    def test_basic(self) -> None:
        # 3 wins / 2 losses = 1.5
        assert wins_losses_ratio(PNLS) == pytest.approx(1.5)

    def test_no_losses(self) -> None:
        assert wins_losses_ratio([100.0, 200.0]) is None

    def test_no_wins(self) -> None:
        assert wins_losses_ratio([-10.0, -20.0]) == pytest.approx(0.0)


class TestWinningPct:
    def test_basic(self) -> None:
        # 3 wins / 5 trades = 0.6
        assert winning_pct(PNLS) == pytest.approx(0.6)

    def test_all_wins(self) -> None:
        assert winning_pct([10.0, 20.0]) == pytest.approx(1.0)

    def test_all_losses(self) -> None:
        assert winning_pct([-10.0, -20.0]) == pytest.approx(0.0)

    def test_empty(self) -> None:
        assert winning_pct([]) is None
