from datetime import UTC, datetime

import pandas as pd
import pytest
from trademachine.tradingmonitor_analytics.services import dashboard_metrics as dm
from trademachine.tradingmonitor_storage.db.models import (
    Backtest,
    BacktestEquity,
    Portfolio,
    Strategy,
)


def test_get_strategy_metrics_payload_filters_sell_rows_for_side(
    db_session, monkeypatch
):
    strategy = Strategy(id="s1", name="Alpha", initial_balance=1000.0)
    db_session.add(strategy)
    db_session.flush()

    deals_df = pd.DataFrame(
        {
            "strategy_id": ["s1", "s1"],
            "symbol": ["EURUSD", "EURUSD"],
            "type": ["BUY", "SELL"],
            "volume": [1.0, 1.0],
            "price": [1.1, 1.2],
            "profit": [0.0, 120.0],
            "commission": [0.0, -2.0],
            "swap": [0.0, 0.0],
        },
        index=pd.DatetimeIndex(
            [
                datetime(2026, 1, 1, tzinfo=UTC),
                datetime(2026, 1, 2, tzinfo=UTC),
            ]
        ),
    )
    captured: dict[str, pd.DataFrame] = {}

    monkeypatch.setattr(dm, "get_strategy_deals", lambda strategy_id: deals_df)

    def _fake_calculate(deals: pd.DataFrame, equity: pd.DataFrame) -> dict[str, float]:
        captured["deals"] = deals
        captured["equity"] = equity
        return {"Profit": 118.0}

    monkeypatch.setattr(dm, "calculate_metrics_from_df", _fake_calculate)

    result = dm.get_strategy_metrics_payload(db_session, "s1", side="sell")

    assert result["Profit"] == pytest.approx(118.0)
    assert result["Return (%)"] == pytest.approx(11.8)
    assert list(captured["deals"]["type"]) == ["SELL"]
    assert float(captured["equity"].iloc[-1]["equity"]) == pytest.approx(1118.0)


def test_get_strategy_metrics_payload_counts_all_buy_and_sell_deals_for_both(
    db_session, monkeypatch
):
    strategy = Strategy(id="s1", name="Alpha", initial_balance=1000.0)
    db_session.add(strategy)
    db_session.flush()

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
    captured: dict[str, pd.DataFrame] = {}

    monkeypatch.setattr(dm, "get_strategy_deals", lambda strategy_id: deals_df)

    def _fake_calculate(deals: pd.DataFrame, equity: pd.DataFrame) -> dict[str, float]:
        captured["deals"] = deals
        captured["equity"] = equity
        return {"Profit": 137.0, "Total Trades": float(len(deals))}

    monkeypatch.setattr(dm, "calculate_metrics_from_df", _fake_calculate)

    result = dm.get_strategy_metrics_payload(db_session, "s1")

    assert result["Profit"] == pytest.approx(137.0)
    assert result["Return (%)"] == pytest.approx(13.7)
    assert list(captured["deals"]["type"]) == ["BUY", "SELL", "SELL", "BUY"]
    assert len(captured["deals"]) == 4
    # Synthetic equity: cumsum of (profit+commission+swap) + initial_balance(1000)
    # [0-2+0, 100-2+0, 100-2+0, 140-3+0] cumsum = [0, 98, 98, 137] + 1000
    assert float(captured["equity"].iloc[-1]["equity"]) == pytest.approx(1137.0)


def test_get_strategy_metrics_payload_sets_cumulative_return_from_initial_balance(
    db_session, monkeypatch
):
    strategy = Strategy(id="s1", name="Alpha", initial_balance=1000.0)
    db_session.add(strategy)
    db_session.flush()

    monkeypatch.setattr(
        dm,
        "get_strategy_deals",
        lambda strategy_id: pd.DataFrame(
            {
                "type": ["BUY"],
                "profit": [120.0],
                "commission": [-2.0],
                "swap": [0.0],
            },
            index=pd.DatetimeIndex([datetime(2026, 1, 1, tzinfo=UTC)]),
        ),
    )
    monkeypatch.setattr(
        dm,
        "calculate_metrics_from_df",
        lambda deals, equity: {"Profit": 118.0, "Return (%)": None},
    )

    result = dm.get_strategy_metrics_payload(db_session, "s1")

    assert result["Profit"] == pytest.approx(118.0)
    assert result["Return (%)"] == pytest.approx(11.8)


def test_get_strategy_metrics_payload_uses_plugin_drawdown(db_session, monkeypatch):
    strategy = Strategy(id="s1", name="Alpha", initial_balance=1000.0)
    db_session.add(strategy)
    db_session.flush()

    monkeypatch.setattr(
        dm,
        "get_strategy_deals",
        lambda strategy_id: pd.DataFrame(
            {
                "type": ["BUY", "SELL"],
                "profit": [50.0, -150.0],
                "commission": [0.0, 0.0],
                "swap": [0.0, 0.0],
            },
            index=pd.DatetimeIndex(
                [
                    datetime(2026, 1, 1, tzinfo=UTC),
                    datetime(2026, 1, 2, tzinfo=UTC),
                ]
            ),
        ),
    )
    monkeypatch.setattr(
        dm,
        "calculate_metrics_from_df",
        lambda deals, equity: {"Profit": -100.0, "Drawdown": -25.0},
    )

    result = dm.get_strategy_metrics_payload(db_session, "s1")

    # Drawdown now comes directly from calculate_metrics_from_df (plugin)
    assert result["Drawdown"] == pytest.approx(-25.0)


def test_get_portfolio_equity_breakdown_payload_aggregates_curves(
    db_session, monkeypatch
):
    strategy_a = Strategy(id="s1", name="Alpha")
    strategy_b = Strategy(id="s2", name="Beta")
    portfolio = Portfolio(name="P1", strategies=[strategy_a, strategy_b])
    db_session.add_all([strategy_a, strategy_b, portfolio])
    db_session.flush()

    timestamps = pd.DatetimeIndex(
        [
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 2, tzinfo=UTC),
        ]
    )
    # Synthetic equity is built from deals: cumsum(profit + commission + swap)
    deals = {
        "s1": pd.DataFrame(
            {
                "type": ["BUY", "SELL"],
                "profit": [100.0, 10.0],
                "commission": [0.0, 0.0],
                "swap": [0.0, 0.0],
            },
            index=timestamps,
        ),
        "s2": pd.DataFrame(
            {
                "type": ["BUY", "SELL"],
                "profit": [50.0, 15.0],
                "commission": [0.0, 0.0],
                "swap": [0.0, 0.0],
            },
            index=timestamps,
        ),
    }
    monkeypatch.setattr(
        dm, "get_strategy_deals", lambda strategy_id: deals[strategy_id]
    )

    payload = dm.get_portfolio_equity_breakdown_payload(db_session, portfolio.id)

    # s1: cumsum [100, 110], s2: cumsum [50, 65], total: [150, 175]
    assert len(payload["total"]) == 2
    assert payload["total"][-1]["equity"] == pytest.approx(175.0)
    assert payload["strategies"]["s1"]["name"] == "Alpha"
    assert payload["strategies"]["s2"]["points"][-1]["equity"] == pytest.approx(65.0)


def test_get_portfolio_equity_breakdown_payload_tolerates_duplicate_timestamps(
    db_session, monkeypatch
):
    strategy_a = Strategy(id="s1", name="Alpha")
    strategy_b = Strategy(id="s2", name="Beta")
    portfolio = Portfolio(name="P1", strategies=[strategy_a, strategy_b])
    db_session.add_all([strategy_a, strategy_b, portfolio])
    db_session.flush()

    duplicate_timestamps = pd.DatetimeIndex(
        [
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 2, tzinfo=UTC),
        ]
    )
    deals = {
        "s1": pd.DataFrame(
            {
                "type": ["BUY", "SELL", "BUY"],
                "profit": [10.0, -5.0, 15.0],
                "commission": [0.0, 0.0, 0.0],
                "swap": [0.0, 0.0, 0.0],
            },
            index=duplicate_timestamps,
        ),
        "s2": pd.DataFrame(
            {
                "type": ["BUY", "SELL", "BUY"],
                "profit": [10.0, -5.0, 15.0],
                "commission": [0.0, 0.0, 0.0],
                "swap": [0.0, 0.0, 0.0],
            },
            index=duplicate_timestamps,
        ),
    }
    monkeypatch.setattr(
        dm, "get_strategy_deals", lambda strategy_id: deals[strategy_id]
    )

    payload = dm.get_portfolio_equity_breakdown_payload(db_session, portfolio.id)

    assert len(payload["total"]) == 2
    assert payload["total"][0]["equity"] == pytest.approx(10.0)
    assert payload["total"][-1]["equity"] == pytest.approx(40.0)
    assert len(payload["strategies"]["s1"]["points"]) == 2


def test_get_portfolio_equity_payload_tolerates_duplicate_timestamps(
    db_session, monkeypatch
):
    strategy_a = Strategy(id="s1", name="Alpha")
    strategy_b = Strategy(id="s2", name="Beta")
    portfolio = Portfolio(name="P1", strategies=[strategy_a, strategy_b])
    db_session.add_all([strategy_a, strategy_b, portfolio])
    db_session.flush()

    duplicate_timestamps = pd.DatetimeIndex(
        [
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 2, tzinfo=UTC),
        ]
    )
    deals = pd.DataFrame(
        {
            "type": ["BUY", "SELL", "BUY"],
            "profit": [10.0, -5.0, 15.0],
            "commission": [0.0, 0.0, 0.0],
            "swap": [0.0, 0.0, 0.0],
        },
        index=duplicate_timestamps,
    )
    monkeypatch.setattr(dm, "get_strategy_deals", lambda _strategy_id: deals.copy())

    payload = dm.get_portfolio_equity_payload(db_session, portfolio.id)

    assert len(payload) == 2
    assert payload[0]["equity"] == pytest.approx(10.0)
    assert payload[-1]["equity"] == pytest.approx(40.0)


def test_get_backtest_equity_payload_returns_stored_points(db_session):
    strategy = Strategy(id="s1", name="Alpha")
    db_session.add(strategy)
    db_session.flush()
    backtest = Backtest(
        strategy_id="s1",
        client_run_id=1,
        initial_balance=1000.0,
    )
    db_session.add(backtest)
    db_session.flush()
    db_session.add_all(
        [
            BacktestEquity(
                backtest_id=backtest.id,
                timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                balance=1000.0,
                equity=1010.0,
            ),
            BacktestEquity(
                backtest_id=backtest.id,
                timestamp=datetime(2026, 1, 2, tzinfo=UTC),
                balance=1005.0,
                equity=1025.0,
            ),
        ]
    )
    db_session.flush()

    payload = dm.get_backtest_equity_payload(db_session, backtest.id)

    assert [point["backtest_id"] for point in payload] == [backtest.id, backtest.id]
    assert [point["balance"] for point in payload] == [1000.0, 1005.0]
    assert [point["equity"] for point in payload] == [1010.0, 1025.0]
    assert [point["timestamp"].date().isoformat() for point in payload] == [
        "2026-01-01",
        "2026-01-02",
    ]


def test_get_backtest_metrics_payload_counts_all_buy_and_sell_deals_for_both(
    db_session, monkeypatch
):
    strategy = Strategy(id="s1", name="Alpha")
    db_session.add(strategy)
    db_session.flush()
    backtest = Backtest(
        strategy_id="s1",
        client_run_id=11,
        initial_balance=1000.0,
    )
    db_session.add(backtest)
    db_session.flush()

    deals_df = pd.DataFrame(
        {
            "backtest_id": [backtest.id, backtest.id, backtest.id, backtest.id],
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
    captured: dict[str, pd.DataFrame] = {}

    monkeypatch.setattr(dm, "get_backtest_deals", lambda backtest_id: deals_df)
    monkeypatch.setattr(
        dm,
        "get_backtest_equity",
        lambda backtest_id: pd.DataFrame(
            {"equity": [1000.0, 1098.0, 1137.0]},
            index=pd.DatetimeIndex(
                [
                    datetime(2026, 1, 1, tzinfo=UTC),
                    datetime(2026, 1, 2, tzinfo=UTC),
                    datetime(2026, 1, 4, tzinfo=UTC),
                ]
            ),
        ),
    )

    def _fake_calculate(deals: pd.DataFrame, equity: pd.DataFrame) -> dict[str, float]:
        captured["deals"] = deals
        captured["equity"] = equity
        return {"Profit": 137.0, "Total Trades": float(len(deals))}

    monkeypatch.setattr(dm, "calculate_metrics_from_df", _fake_calculate)

    result = dm.get_backtest_metrics_payload(db_session, backtest.id)

    assert result["Profit"] == pytest.approx(137.0)
    assert result["Return (%)"] == pytest.approx(13.7)
    assert list(captured["deals"]["type"]) == ["BUY", "SELL", "SELL", "BUY"]
    assert len(captured["deals"]) == 4
    assert float(captured["equity"].iloc[-1]["equity"]) == pytest.approx(1137.0)
