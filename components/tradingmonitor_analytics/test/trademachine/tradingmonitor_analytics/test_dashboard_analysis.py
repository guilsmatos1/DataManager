from datetime import UTC, datetime

import pandas as pd
import pytest
from trademachine.tradingmonitor_analytics.services import dashboard_analysis as da
from trademachine.tradingmonitor_storage.db.models import (
    Account,
    Backtest,
    BacktestDeal,
    Benchmark,
    DealType,
    Portfolio,
    Strategy,
)


def test_list_portfolios_payload_selects_requested_mode(db_session, monkeypatch):
    strategy_demo = Strategy(id="s-demo", name="Demo", real_account=False)
    strategy_real = Strategy(id="s-real", name="Real", real_account=True)
    portfolio = Portfolio(
        name="Main",
        strategies=[strategy_demo, strategy_real],
    )
    db_session.add_all([strategy_demo, strategy_real, portfolio])
    db_session.flush()

    monkeypatch.setattr(
        da,
        "_calculate_backtest_portfolio_net_profit",
        lambda db, strategy_ids: 30.0,
    )

    def _fake_calculate_portfolio_metrics(strategy_ids: list[str]) -> dict[str, float]:
        if strategy_ids == ["s-demo"]:
            return {"Profit": 10.0}
        if strategy_ids == ["s-real"]:
            return {"Profit": 20.0}
        raise AssertionError(f"Unexpected strategy_ids: {strategy_ids}")

    monkeypatch.setattr(
        da,
        "calculate_portfolio_metrics",
        _fake_calculate_portfolio_metrics,
    )

    payload = da.list_portfolios_payload(db_session, mode="real")

    assert len(payload) == 1
    assert payload[0].demo_net_profit == pytest.approx(10.0)
    assert payload[0].real_net_profit == pytest.approx(20.0)
    assert payload[0].backtest_net_profit == pytest.approx(30.0)
    assert payload[0].net_profit == pytest.approx(20.0)


def test_list_portfolios_payload_tolerates_metric_failures(db_session, monkeypatch):
    strategy_demo = Strategy(id="s-demo", name="Demo", real_account=False)
    portfolio = Portfolio(
        name="Broken Metrics",
        strategies=[strategy_demo],
    )
    db_session.add_all([strategy_demo, portfolio])
    db_session.flush()

    monkeypatch.setattr(
        da,
        "_calculate_backtest_portfolio_net_profit",
        lambda db, strategy_ids: 30.0,
    )
    monkeypatch.setattr(
        da,
        "calculate_portfolio_metrics",
        lambda strategy_ids: (_ for _ in ()).throw(ValueError("boom")),
    )

    payload = da.list_portfolios_payload(db_session, mode="demo")

    assert len(payload) == 1
    assert payload[0].id == portfolio.id
    assert payload[0].demo_net_profit is None
    assert payload[0].real_net_profit is None
    assert payload[0].backtest_net_profit == pytest.approx(30.0)
    assert payload[0].net_profit is None
    assert payload[0].metrics_error == "boom"


def test_list_strategy_backtests_payload_injects_net_profit(db_session):
    strategy = Strategy(id="s1", name="Alpha")
    db_session.add(strategy)
    db_session.flush()

    older_backtest = Backtest(
        strategy_id="s1",
        client_run_id=1,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        status="complete",
    )
    newer_backtest = Backtest(
        strategy_id="s1",
        client_run_id=2,
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
        status="complete",
    )
    db_session.add_all([older_backtest, newer_backtest])
    db_session.flush()

    db_session.add(
        BacktestDeal(
            backtest_id=older_backtest.id,
            timestamp=datetime(2026, 1, 1, 10, tzinfo=UTC),
            ticket=1,
            symbol="EURUSD",
            type=DealType.SELL,
            volume=1.0,
            price=1.2,
            profit=120.0,
            commission=-2.0,
            swap=0.0,
        )
    )
    db_session.flush()

    payload = da.list_strategy_backtests_payload(db_session, "s1")

    assert [row.id for row in payload] == [newer_backtest.id, older_backtest.id]
    assert payload[0].net_profit is None
    assert payload[1].net_profit == pytest.approx(118.0)


def test_get_advanced_analysis_payload_builds_expected_response(
    db_session, monkeypatch
):
    account = Account(id="acc-1", account_type="Real")
    strategy = Strategy(id="s1", name="Alpha", real_account=True, account=account)
    benchmark = Benchmark(
        name="S&P 500",
        source="OPENBB",
        asset="SPY",
        timeframe="D1",
        is_default=True,
    )
    db_session.add_all([account, strategy, benchmark])
    db_session.flush()

    deals_df = pd.DataFrame(
        {"strategy_id": ["s1"], "profit": [50.0], "commission": [0.0], "swap": [0.0]},
        index=pd.DatetimeIndex([datetime(2026, 1, 1, tzinfo=UTC)]),
    )
    equity_df = pd.DataFrame(
        {"equity": [1050.0]},
        index=pd.DatetimeIndex([datetime(2026, 1, 1, tzinfo=UTC)]),
    )

    monkeypatch.setattr(
        da, "_strategy_ids_with_saved_runtime_history", lambda db: {"s1"}
    )
    monkeypatch.setattr(
        da,
        "_collect_deal_and_equity_frames",
        lambda db, history_type, selected_strategies, dt_from, dt_to: (
            [deals_df],
            [equity_df],
        ),
    )
    monkeypatch.setattr(
        da,
        "calculate_metrics_from_df",
        lambda deals, equity, advanced=False: {"Profit": 50.0},
    )
    monkeypatch.setattr(
        da,
        "load_benchmark_curve",
        lambda db, benchmark_id, date_from=None, date_to=None: pd.DataFrame(),
    )

    payload = da.get_advanced_analysis_payload(
        db_session,
        strategy_ids=["s1"],
        history_type="real",
        date_from="2026-01-01",
        date_to="2026-01-02",
        initial_balance=1000.0,
        benchmark_id=None,
        side=None,
    )

    assert payload["history_type"] == "real"
    assert payload["selected_strategies"] == ["s1"]
    assert payload["metrics"]["Profit"] == pytest.approx(50.0)
    assert payload["metrics"]["Return on Capital (%)"] == pytest.approx(5.0)
    assert payload["benchmark"]["asset"] == "SPY"
    assert payload["equity_curve"][0]["equity"] == pytest.approx(1050.0)
    assert payload["strategy_contributions"] == [
        {"strategy_id": "s1", "name": "Alpha", "profit": 50.0}
    ]
