import warnings
from datetime import UTC, datetime, timedelta

import pytest
from trademachine.tradingmonitor_analytics.services import dashboard_overview as dov
from trademachine.tradingmonitor_storage.db.models import (
    Account,
    Deal,
    DealType,
    EquityCurve,
    Portfolio,
    Setting,
    Strategy,
    StrategyRuntimeSnapshot,
)


def test_get_summary_payload_aggregates_workspace_counts(db_session):
    account = Account(id="acc-1", account_type="Real")
    strategy_a = Strategy(
        id="s1",
        name="Alpha",
        symbol="EURUSD",
        operational_style="Trend",
        trade_duration="Swing",
        account=account,
    )
    strategy_b = Strategy(
        id="s2",
        name="Beta",
        symbol="EURUSD",
        operational_style=None,
        trade_duration=None,
    )
    portfolio = Portfolio(name="Main", strategies=[strategy_a, strategy_b])
    db_session.add_all([account, strategy_a, strategy_b, portfolio])
    db_session.flush()

    payload = dov.get_summary_payload(db_session)

    assert payload.strategies_count == 2
    assert payload.portfolios_count == 1
    assert payload.accounts_count == 1
    assert payload.by_symbol == {"EURUSD": 2}
    assert payload.by_style == {"Trend": 1, "Unknown": 1}
    assert payload.by_duration == {"Swing": 1, "Unknown": 1}


def test_get_real_overview_payload_aggregates_live_metrics(db_session):
    now = datetime.now(UTC)
    real_account = Account(id="acc-real", account_type="Real")
    demo_account = Account(id="acc-demo", account_type="Demo")
    real_strategy = Strategy(
        id="s-real",
        name="Alpha",
        symbol="EURUSD",
        initial_balance=1000.0,
        real_account=True,
        account=real_account,
    )
    demo_strategy = Strategy(
        id="s-demo",
        name="Beta",
        symbol="GBPUSD",
        initial_balance=1000.0,
        real_account=False,
        account=demo_account,
    )
    db_session.add_all(
        [
            real_account,
            demo_account,
            real_strategy,
            demo_strategy,
            Setting(key="real_page_mode", value="real"),
        ]
    )
    db_session.flush()

    db_session.add_all(
        [
            Deal(
                timestamp=now - timedelta(hours=1),
                ticket=1,
                strategy_id="s-real",
                symbol="EURUSD",
                type=DealType.BUY,
                volume=0.1,
                price=1.1,
                profit=100.0,
                commission=-2.0,
                swap=0.0,
            ),
            Deal(
                timestamp=now - timedelta(hours=1),
                ticket=2,
                strategy_id="s-demo",
                symbol="GBPUSD",
                type=DealType.BUY,
                volume=0.1,
                price=1.2,
                profit=55.0,
                commission=-1.0,
                swap=0.0,
            ),
            EquityCurve(
                strategy_id="s-real",
                timestamp=now - timedelta(hours=2),
                balance=1000.0,
                equity=1025.0,
            ),
            EquityCurve(
                strategy_id="s-real",
                timestamp=now - timedelta(minutes=30),
                balance=1098.0,
                equity=1110.5,
            ),
            StrategyRuntimeSnapshot(
                strategy_id="s-real",
                timestamp=now - timedelta(minutes=5),
                open_profit=12.5,
                open_trades_count=2,
                pending_orders_count=1,
            ),
        ]
    )
    db_session.flush()

    payload = dov.get_real_overview_payload(
        db_session,
        max_points_per_strategy=50,
    )

    assert payload["mode"] == "real"
    assert len(payload["strategies"]) == 1
    strategy_payload = payload["strategies"][0]
    assert strategy_payload["id"] == "s-real"
    assert strategy_payload["net_profit"] == pytest.approx(98.0)
    assert strategy_payload["day_pnl"] == pytest.approx(98.0)
    assert strategy_payload["floating_pnl"] == pytest.approx(12.5)
    assert strategy_payload["open_trades_count"] == 2
    assert strategy_payload["pending_orders_count"] == 1
    assert strategy_payload["equity_curve"][-1]["equity"] == pytest.approx(1110.5)
    assert payload["totals"] == {
        "net_profit": 98.0,
        "floating_pnl": 12.5,
        "day_pnl": 98.0,
        "open_trades_count": 2,
        "pending_orders_count": 1,
        "counts_available": True,
    }


def test_get_real_daily_payload_filters_current_mode_strategies(db_session):
    real_account = Account(id="acc-real", account_type="Real")
    demo_account = Account(id="acc-demo", account_type="Demo")
    real_strategy = Strategy(id="s-real", name="Alpha", account=real_account)
    demo_strategy = Strategy(id="s-demo", name="Beta", account=demo_account)
    db_session.add_all(
        [
            real_account,
            demo_account,
            real_strategy,
            demo_strategy,
            Setting(key="real_page_mode", value="real"),
            Deal(
                timestamp=datetime(2026, 4, 9, 20, 30, tzinfo=UTC),
                ticket=1,
                strategy_id="s-real",
                symbol="EURUSD",
                type=DealType.BUY,
                volume=0.1,
                price=1.1,
                profit=40.0,
                commission=-2.0,
                swap=0.0,
            ),
            Deal(
                timestamp=datetime(2026, 4, 9, 21, 30, tzinfo=UTC),
                ticket=2,
                strategy_id="s-real",
                symbol="EURUSD",
                type=DealType.SELL,
                volume=0.1,
                price=1.2,
                profit=20.0,
                commission=-2.0,
                swap=0.0,
            ),
            Deal(
                timestamp=datetime(2026, 4, 10, 12, 0, tzinfo=UTC),
                ticket=3,
                strategy_id="s-demo",
                symbol="GBPUSD",
                type=DealType.BUY,
                volume=0.1,
                price=1.2,
                profit=15.0,
                commission=-1.0,
                swap=0.0,
            ),
        ]
    )
    db_session.flush()

    payload = dov.get_real_daily_payload(
        db_session,
        now_utc=datetime(2026, 4, 10, 18, 0, tzinfo=UTC),
    )

    assert payload == [
        {"date": "2026-04-09", "net_profit": 38.0},
        {"date": "2026-04-10", "net_profit": 18.0},
    ]


def test_get_real_daily_payload_appends_current_local_day_when_missing(db_session):
    real_account = Account(id="acc-real", account_type="Real")
    real_strategy = Strategy(id="s-real", name="Alpha", account=real_account)
    db_session.add_all(
        [
            real_account,
            real_strategy,
            Setting(key="real_page_mode", value="real"),
            Deal(
                timestamp=datetime(2026, 4, 10, 12, 0, tzinfo=UTC),
                ticket=1,
                strategy_id="s-real",
                symbol="EURUSD",
                type=DealType.BUY,
                volume=0.1,
                price=1.1,
                profit=10.0,
                commission=-1.0,
                swap=0.0,
            ),
        ]
    )
    db_session.flush()

    payload = dov.get_real_daily_payload(
        db_session,
        now_utc=datetime(2026, 4, 12, 9, 0, tzinfo=UTC),
    )

    assert payload == [
        {"date": "2026-04-10", "net_profit": 9.0},
        {"date": "2026-04-12", "net_profit": 0.0, "trades_count": 0},
    ]


def test_get_real_recent_deals_payload_returns_strategy_names(db_session):
    now = datetime.now(UTC)
    account = Account(id="acc-real", account_type="Real")
    strategy = Strategy(id="s-real", name="Alpha", account=account)
    db_session.add_all(
        [
            account,
            strategy,
            Setting(key="real_page_mode", value="real"),
            Deal(
                timestamp=now - timedelta(minutes=5),
                ticket=1,
                strategy_id="s-real",
                symbol="EURUSD",
                type=DealType.BUY,
                volume=0.1,
                price=1.1,
                profit=10.0,
                commission=-1.0,
                swap=0.0,
            ),
            Deal(
                timestamp=now,
                ticket=2,
                strategy_id="s-real",
                symbol="EURUSD",
                type=DealType.SELL,
                volume=0.1,
                price=1.2,
                profit=25.0,
                commission=-2.0,
                swap=0.0,
            ),
        ]
    )
    db_session.flush()

    payload = dov.get_real_recent_deals_payload(db_session, limit=1)

    assert len(payload) == 1
    assert payload[0]["ticket"] == 2
    assert payload[0]["strategy_name"] == "Alpha"


def test_compute_var_ignores_zero_equity_without_runtime_warning():
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        var_95 = dov._compute_var([0.0, 100.0, 90.0, 95.0, 105.0, 100.0, 110.0])

    assert var_95 is not None
    assert var_95 > 0
