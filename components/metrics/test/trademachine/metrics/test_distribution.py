"""Golden tests for distribution formulas."""

from __future__ import annotations

import pytest
from trademachine.metrics.formulas.distribution import (
    deviation,
    stability,
    z_probability,
    z_score,
)

PNLS = [100.0, -50.0, 200.0, -75.0, 150.0]
# mean = 65, deviations: |35|,|115|,|135|,|140|,|85| → avg = 510/5 = 102
EQUITY_STRAIGHT = [10_000.0, 10_100.0, 10_200.0, 10_300.0, 10_400.0]
EQUITY_CURVE = [10_000.0, 10_100.0, 10_050.0, 10_250.0, 10_175.0, 10_325.0]


class TestDeviation:
    def test_basic(self) -> None:
        assert deviation(PNLS) == pytest.approx(102.0)

    def test_single(self) -> None:
        assert deviation([100.0]) is None

    def test_all_same(self) -> None:
        assert deviation([50.0, 50.0, 50.0]) == pytest.approx(0.0)


class TestZScore:
    def test_sign_positive_mean(self) -> None:
        result = z_score(PNLS)
        assert result is not None
        assert result > 0  # positive mean → positive z

    def test_single(self) -> None:
        assert z_score([100.0]) is None

    def test_all_same(self) -> None:
        assert z_score([100.0, 100.0]) is None  # std=0

    def test_zero_mean(self) -> None:
        assert z_score([10.0, -10.0]) == pytest.approx(0.0)


class TestZProbability:
    def test_range(self) -> None:
        result = z_probability(PNLS)
        assert result is not None
        assert 0.0 <= result <= 1.0

    def test_positive_z_above_half(self) -> None:
        assert z_probability(PNLS) > 0.5

    def test_zero_z_gives_half(self) -> None:
        # symmetric pnls → mean=0 → z=0 → p=0.5
        result = z_probability([10.0, -10.0])
        assert result == pytest.approx(0.5)

    def test_none_propagates(self) -> None:
        assert z_probability([100.0]) is None


class TestStability:
    def test_perfect_line(self) -> None:
        assert stability(EQUITY_STRAIGHT) == pytest.approx(1.0, rel=1e-6)

    def test_curved(self) -> None:
        result = stability(EQUITY_CURVE)
        assert result is not None
        assert 0.0 < result < 1.0

    def test_single_point(self) -> None:
        assert stability([10_000.0]) is None

    def test_flat(self) -> None:
        assert stability([100.0, 100.0, 100.0]) is None  # ss_yy=0
