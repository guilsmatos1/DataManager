"""Golden tests for exposure formula."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from trademachine.metrics.formulas.exposure import exposure
from trademachine.metrics.types import TradeRecord

BASE = datetime(2025, 1, 1)


def _trade(
    entry_offset_h: float, exit_offset_h: float, side: str = "long"
) -> TradeRecord:
    return TradeRecord(
        entry_time=BASE + timedelta(hours=entry_offset_h),
        exit_time=BASE + timedelta(hours=exit_offset_h),
        pnl=100.0,
        side=side,
    )


class TestExposure:
    def test_half_time(self) -> None:
        # 2 trades × 1h each over 4h period = 2/4 = 0.5
        trades = [_trade(0, 1), _trade(2, 3)]
        result = exposure(trades, BASE, BASE + timedelta(hours=4))
        assert result == pytest.approx(0.5)

    def test_full_exposure(self) -> None:
        # trade covers entire period
        trades = [_trade(0, 10)]
        result = exposure(trades, BASE, BASE + timedelta(hours=10))
        assert result == pytest.approx(1.0)

    def test_capped_at_one(self) -> None:
        # overlapping trades exceed period — capped at 1.0
        trades = [_trade(0, 10), _trade(0, 10)]
        result = exposure(trades, BASE, BASE + timedelta(hours=10))
        assert result == pytest.approx(1.0)

    def test_empty_trades(self) -> None:
        assert exposure([], BASE, BASE + timedelta(days=1)) is None

    def test_zero_period(self) -> None:
        trades = [_trade(0, 1)]
        assert exposure(trades, BASE, BASE) is None
