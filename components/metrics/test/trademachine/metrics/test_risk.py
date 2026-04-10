"""Golden tests for risk formulas."""

from __future__ import annotations

import math

import pytest
from trademachine.metrics.formulas.risk import (
    expectancy,
    r_expectancy,
    r_expectancy_score,
    sqn,
    sqn_score,
)

# wins: 100, 200, 150 → win_rate=0.6, avg_win=150
# losses: -50, -75  → loss_rate=0.4, avg_loss=-62.5
# expectancy = 0.6*150 + 0.4*(-62.5) = 90 - 25 = 65
PNLS = [100.0, -50.0, 200.0, -75.0, 150.0]


class TestExpectancy:
    def test_basic(self) -> None:
        assert expectancy(PNLS) == pytest.approx(65.0)

    def test_all_wins(self) -> None:
        assert expectancy([100.0, 200.0]) == pytest.approx(150.0)

    def test_all_losses(self) -> None:
        assert expectancy([-50.0, -100.0]) == pytest.approx(-75.0)

    def test_empty(self) -> None:
        assert expectancy([]) is None


class TestRExpectancy:
    def test_basic(self) -> None:
        # 65 / 100 = 0.65
        assert r_expectancy(PNLS, 100.0) == pytest.approx(0.65)

    def test_zero_risk(self) -> None:
        assert r_expectancy(PNLS, 0.0) is None

    def test_negative_risk_same_magnitude(self) -> None:
        assert r_expectancy(PNLS, -100.0) == pytest.approx(0.65)


class TestRExpectancyScore:
    def test_basic(self) -> None:
        # R=0.65, 5 trades / 1 year → 0.65 * 5 = 3.25
        assert r_expectancy_score(PNLS, 100.0, 1.0) == pytest.approx(3.25)

    def test_zero_years(self) -> None:
        assert r_expectancy_score(PNLS, 100.0, 0.0) is None

    def test_empty_trades(self) -> None:
        assert r_expectancy_score([], 100.0, 1.0) is None


class TestSQN:
    def test_basic(self) -> None:
        n = len(PNLS)
        mean = sum(PNLS) / n
        std = math.sqrt(sum((p - mean) ** 2 for p in PNLS) / (n - 1))
        expected = (mean / std) * math.sqrt(n)
        assert sqn(PNLS) == pytest.approx(expected, rel=1e-6)

    def test_single_trade(self) -> None:
        assert sqn([100.0]) is None

    def test_all_same(self) -> None:
        assert sqn([100.0, 100.0, 100.0]) is None  # std=0


class TestSQNScore:
    def test_basic(self) -> None:
        sq = sqn(PNLS)
        expected = sq * math.sqrt(1.0 / 1.0)
        assert sqn_score(PNLS, 1.0) == pytest.approx(expected, rel=1e-6)

    def test_zero_years(self) -> None:
        assert sqn_score(PNLS, 0.0) is None

    def test_single_trade(self) -> None:
        assert sqn_score([100.0], 1.0) is None
