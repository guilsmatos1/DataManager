"""Golden tests for symmetry formulas."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from trademachine.metrics.formulas.symmetry import nsymmetry, symmetry, trades_symmetry
from trademachine.metrics.types import TradeRecord

BASE = datetime(2025, 1, 1)


def _t(pnl: float, side: str) -> TradeRecord:
    return TradeRecord(
        entry_time=BASE,
        exit_time=BASE + timedelta(hours=1),
        pnl=pnl,
        side=side,
    )


TRADES = [_t(200, "long"), _t(100, "long"), _t(-50, "short"), _t(150, "short")]
# long_profit=300, short_profit=100, long_count=2, short_count=2


class TestSymmetry:
    def test_basic(self) -> None:
        assert symmetry(TRADES) == pytest.approx(200.0)  # 300 - 100

    def test_empty(self) -> None:
        assert symmetry([]) is None

    def test_only_longs(self) -> None:
        assert symmetry([_t(100, "long")]) == pytest.approx(100.0)


class TestTradesSymmetry:
    def test_basic(self) -> None:
        assert trades_symmetry(TRADES) == pytest.approx(0.0)  # 2 - 2

    def test_more_longs(self) -> None:
        trades = [_t(100, "long"), _t(100, "long"), _t(-50, "short")]
        assert trades_symmetry(trades) == pytest.approx(1.0)

    def test_empty(self) -> None:
        assert trades_symmetry([]) is None


class TestNSymmetry:
    def test_both_profitable(self) -> None:
        assert nsymmetry(TRADES) == 0

    def test_asymmetric_long_wins_short_loses(self) -> None:
        trades = [_t(200, "long"), _t(-50, "short")]
        assert nsymmetry(trades) == -1

    def test_asymmetric_short_wins_long_loses(self) -> None:
        trades = [_t(-100, "long"), _t(200, "short")]
        assert nsymmetry(trades) == -1

    def test_only_longs(self) -> None:
        assert nsymmetry([_t(100, "long")]) == 0

    def test_empty(self) -> None:
        assert nsymmetry([]) is None
