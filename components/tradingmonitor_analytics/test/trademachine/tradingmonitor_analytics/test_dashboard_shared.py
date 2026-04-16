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


def test_closed_trades_extracts_only_realized_rows():
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

    result = ds.closed_trades(deals_df)

    assert list(result["type"]) == ["SELL", "BUY"]
    assert list(result["profit"]) == pytest.approx([100.0, 40.0])
    assert list(result["commission"]) == pytest.approx([-2.0, -1.0])


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


def test_closed_trades_partial_close_splits_profit_proportionally():
    """Open 2.0 lots BUY, close only 0.5 lots — profit/commission/swap prorated."""
    deals_df = pd.DataFrame(
        {
            "strategy_id": ["s1", "s1"],
            "symbol": ["EURUSD", "EURUSD"],
            "type": ["BUY", "SELL"],
            "volume": [2.0, 0.5],
            "price": [1.1, 1.2],
            "profit": [0.0, 200.0],
            "commission": [0.0, -8.0],
            "swap": [0.0, -4.0],
        },
        index=pd.DatetimeIndex(
            [datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC)]
        ),
    )

    result = ds.closed_trades(deals_df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["volume"] == pytest.approx(0.5)
    assert row["profit"] == pytest.approx(200.0)
    assert row["commission"] == pytest.approx(-8.0)
    assert row["swap"] == pytest.approx(-4.0)


def test_closed_trades_partial_close_large_sell_prorates():
    """Open 1.0 lot BUY, then SELL 3.0 lots — only 1.0 closes, rest opens short."""
    deals_df = pd.DataFrame(
        {
            "strategy_id": ["s1", "s1"],
            "symbol": ["EURUSD", "EURUSD"],
            "type": ["BUY", "SELL"],
            "volume": [1.0, 3.0],
            "price": [1.1, 1.2],
            "profit": [0.0, 300.0],
            "commission": [0.0, -9.0],
            "swap": [0.0, -6.0],
        },
        index=pd.DatetimeIndex(
            [datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC)]
        ),
    )

    result = ds.closed_trades(deals_df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["volume"] == pytest.approx(1.0)
    # ratio = 1.0 / 3.0
    assert row["profit"] == pytest.approx(300.0 / 3.0)
    assert row["commission"] == pytest.approx(-9.0 / 3.0)
    assert row["swap"] == pytest.approx(-6.0 / 3.0)


def test_closed_trades_multiple_symbols_tracked_independently():
    """Positions in different symbols don't close each other."""
    deals_df = pd.DataFrame(
        {
            "strategy_id": ["s1"] * 4,
            "symbol": ["EURUSD", "GBPUSD", "EURUSD", "GBPUSD"],
            "type": ["BUY", "SELL", "SELL", "BUY"],
            "volume": [1.0, 2.0, 1.0, 2.0],
            "price": [1.1, 1.3, 1.2, 1.25],
            "profit": [0.0, 0.0, 50.0, 80.0],
            "commission": [0.0, 0.0, -1.0, -2.0],
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

    result = ds.closed_trades(deals_df)

    assert len(result) == 2
    eu_row = result[result["symbol"] == "EURUSD"].iloc[0]
    gb_row = result[result["symbol"] == "GBPUSD"].iloc[0]
    assert eu_row["volume"] == pytest.approx(1.0)
    assert eu_row["profit"] == pytest.approx(50.0)
    assert gb_row["volume"] == pytest.approx(2.0)
    assert gb_row["profit"] == pytest.approx(80.0)


def test_closed_trades_position_reversal():
    """BUY 1.0, then SELL 2.0 — closes 1.0, opens 1.0 short. Then BUY 1.0 closes short."""
    deals_df = pd.DataFrame(
        {
            "strategy_id": ["s1"] * 3,
            "symbol": ["EURUSD"] * 3,
            "type": ["BUY", "SELL", "BUY"],
            "volume": [1.0, 2.0, 1.0],
            "price": [1.1, 1.2, 1.15],
            "profit": [0.0, 300.0, 60.0],
            "commission": [0.0, -6.0, -3.0],
            "swap": [0.0, 0.0, 0.0],
        },
        index=pd.DatetimeIndex(
            [
                datetime(2026, 1, 1, tzinfo=UTC),
                datetime(2026, 1, 2, tzinfo=UTC),
                datetime(2026, 1, 3, tzinfo=UTC),
            ]
        ),
    )

    result = ds.closed_trades(deals_df)

    assert len(result) == 2
    # First close: SELL closes 1.0 of 2.0 lots (ratio = 0.5)
    assert result.iloc[0]["type"] == "SELL"
    assert result.iloc[0]["volume"] == pytest.approx(1.0)
    assert result.iloc[0]["profit"] == pytest.approx(150.0)
    assert result.iloc[0]["commission"] == pytest.approx(-3.0)
    # Second close: BUY closes 1.0 of the opened short
    assert result.iloc[1]["type"] == "BUY"
    assert result.iloc[1]["volume"] == pytest.approx(1.0)
    assert result.iloc[1]["profit"] == pytest.approx(60.0)


def test_closed_trades_empty_dataframe():
    result = ds.closed_trades(pd.DataFrame())
    assert result.empty


def test_closed_trades_no_type_column():
    deals_df = pd.DataFrame({"symbol": ["EURUSD"], "volume": [1.0]})
    result = ds.closed_trades(deals_df)
    assert result.equals(deals_df)


def test_closed_trades_only_opens_returns_empty():
    """All BUYs with no closing SELLs — no realized trades."""
    deals_df = pd.DataFrame(
        {
            "strategy_id": ["s1", "s1"],
            "symbol": ["EURUSD", "EURUSD"],
            "type": ["BUY", "BUY"],
            "volume": [1.0, 2.0],
            "price": [1.1, 1.15],
            "profit": [0.0, 0.0],
            "commission": [0.0, 0.0],
            "swap": [0.0, 0.0],
        },
        index=pd.DatetimeIndex(
            [datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC)]
        ),
    )

    result = ds.closed_trades(deals_df)

    assert result.empty


def test_closed_trades_filters_non_trade_types():
    """Rows with type not in CLOSED_TRADE_TYPES are excluded."""
    deals_df = pd.DataFrame(
        {
            "strategy_id": ["s1", "s1", "s1"],
            "symbol": ["EURUSD", "EURUSD", "EURUSD"],
            "type": ["BUY", "BALANCE", "SELL"],
            "volume": [1.0, 500.0, 1.0],
            "price": [1.1, 0.0, 1.2],
            "profit": [0.0, 500.0, 100.0],
            "commission": [0.0, 0.0, -2.0],
            "swap": [0.0, 0.0, 0.0],
        },
        index=pd.DatetimeIndex(
            [
                datetime(2026, 1, 1, tzinfo=UTC),
                datetime(2026, 1, 2, tzinfo=UTC),
                datetime(2026, 1, 3, tzinfo=UTC),
            ]
        ),
    )

    result = ds.closed_trades(deals_df)

    assert len(result) == 1
    assert result.iloc[0]["type"] == "SELL"
    assert result.iloc[0]["profit"] == pytest.approx(100.0)


def test_compute_max_drawdown_returns_peak_to_valley_fraction():
    result = ds.compute_max_drawdown([1000.0, 1100.0, 900.0, 950.0])

    assert result == pytest.approx((1100.0 - 900.0) / 1100.0)
