"""Shared fixtures for metrics tests."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from trademachine.metrics.public import EquityPoint, TradeRecord


@pytest.fixture
def sample_trades() -> list[TradeRecord]:
    base = datetime(2025, 1, 1)
    pnls = [100.0, -50.0, 200.0, -75.0, 150.0]
    return [
        TradeRecord(
            entry_time=base + timedelta(days=i),
            exit_time=base + timedelta(days=i, hours=4),
            pnl=pnl,
            side="long" if i % 2 == 0 else "short",
        )
        for i, pnl in enumerate(pnls)
    ]


@pytest.fixture
def sample_equity() -> list[EquityPoint]:
    base = datetime(2025, 1, 1)
    values = [10_000, 10_100, 10_050, 10_250, 10_175, 10_325]
    return [
        EquityPoint(timestamp=base + timedelta(days=i), equity=v)
        for i, v in enumerate(values)
    ]


@pytest.fixture
def initial_capital() -> float:
    return 10_000.0
