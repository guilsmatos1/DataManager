from datetime import UTC, datetime

import pandas as pd
import pytest
from trademachine.tradingmonitor_analytics.services import dashboard_shared as ds
from trademachine.tradingmonitor_storage.db.models import Account, Strategy


def test_closed_trades_for_side_extracts_realized_long_rows():
    deals_df = pd.DataFrame(
        {
            "strategy_id": ["s1", "s1", "s1", "s1"],
            "symbol": ["EURUSD", "EURUSD", "EURUSD", "EURUSD"],
            "type": ["BUY", "SELL", "SELL", "BUY"],
            "volume": [1.0, 1.0, 1.0, 1.0],
            "price": [1.1, 1.2, 1.15, 1.05],
            "profit": [0.0, 100.0, 0.0, 40.0],
            "commission": [0.0, -2.0, 0.0, -1.0],
            "swap": [0.0, 0.0, 0.0, 0.0],
        },
        index=pd.DatetimeIndex(
            [
                datetime(2026, 1, 1, tzinfo=UTC),
                datetime(2026, 1, 2, tzinfo=UTC),
                datetime(2026, 1, 3, tzinfo=UTC),
                datetime(2026, 1, 4, tzinfo=UTC),
            ]
        ),
    )

    result = ds.closed_trades_for_side(deals_df, "buy")

    assert list(result["type"]) == ["SELL"]
    assert result.iloc[0]["profit"] == pytest.approx(100.0)
    assert result.iloc[0]["commission"] == pytest.approx(-2.0)


def test_strategy_matches_history_type_prefers_account_type_over_flag():
    real_account = Account(id="acc-real", account_type="Real")
    demo_account = Account(id="acc-demo", account_type="Demo")

    strategy_marked_demo_but_real_account = Strategy(
        id="s1",
        real_account=False,
        account=real_account,
    )
    strategy_marked_real_but_demo_account = Strategy(
        id="s2",
        real_account=True,
        account=demo_account,
    )

    assert (
        ds.strategy_matches_history_type(strategy_marked_demo_but_real_account, "real")
        is True
    )
    assert (
        ds.strategy_matches_history_type(strategy_marked_demo_but_real_account, "demo")
        is False
    )
    assert (
        ds.strategy_matches_history_type(strategy_marked_real_but_demo_account, "demo")
        is True
    )
    assert (
        ds.strategy_matches_history_type(strategy_marked_real_but_demo_account, "real")
        is False
    )


def test_compute_max_drawdown_returns_peak_to_valley_fraction():
    result = ds.compute_max_drawdown([1000.0, 1100.0, 900.0, 950.0])

    assert result == pytest.approx((1100.0 - 900.0) / 1100.0)
