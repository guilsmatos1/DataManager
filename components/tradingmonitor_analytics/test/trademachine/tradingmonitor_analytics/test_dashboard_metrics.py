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


def test_get_strategy_metrics_payload_uses_synthetic_equity_for_side(
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

    result = dm.get_strategy_metrics_payload(db_session, "s1", side="buy")

    assert result["Profit"] == pytest.approx(118.0)
    assert result["Return (%)"] == pytest.approx(11.8)
    assert list(captured["deals"]["type"]) == ["SELL"]
    assert float(captured["equity"].iloc[-1]["equity"]) == pytest.approx(1118.0)


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
        "get_strategy_equity_curve",
        lambda strategy_id: pd.DataFrame(
            {"equity": [1000.0, 1118.0]},
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
        lambda deals, equity: {"Profit": 118.0, "Return (%)": None},
    )

    result = dm.get_strategy_metrics_payload(db_session, "s1")

    assert result["Profit"] == pytest.approx(118.0)
    assert result["Return (%)"] == pytest.approx(11.8)


def test_get_strategy_metrics_payload_sets_max_drawdown_from_initial_balance(
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
        "get_strategy_equity_curve",
        lambda strategy_id: pd.DataFrame(
            {"equity": [1000.0, 1200.0, 900.0, 950.0]},
            index=pd.DatetimeIndex(
                [
                    datetime(2026, 1, 1, tzinfo=UTC),
                    datetime(2026, 1, 2, tzinfo=UTC),
                    datetime(2026, 1, 3, tzinfo=UTC),
                    datetime(2026, 1, 4, tzinfo=UTC),
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

    assert result["Drawdown"] == pytest.approx(30.0)


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
    curves = {
        "s1": pd.DataFrame({"equity": [100.0, 110.0]}, index=timestamps),
        "s2": pd.DataFrame({"equity": [50.0, 65.0]}, index=timestamps),
    }
    monkeypatch.setattr(
        dm, "get_strategy_equity_curve", lambda strategy_id: curves[strategy_id]
    )

    payload = dm.get_portfolio_equity_breakdown_payload(db_session, portfolio.id)

    assert len(payload["total"]) == 2
    assert payload["total"][-1]["equity"] == pytest.approx(175.0)
    assert payload["strategies"]["s1"]["name"] == "Alpha"
    assert payload["strategies"]["s2"]["points"][-1]["equity"] == pytest.approx(65.0)


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
