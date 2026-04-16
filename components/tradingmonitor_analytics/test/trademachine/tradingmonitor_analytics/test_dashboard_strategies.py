from datetime import UTC, datetime, timedelta

import pytest
from trademachine.tradingmonitor_analytics.services import dashboard_strategies as ds
from trademachine.tradingmonitor_storage.db.models import (
    Account,
    Backtest,
    BacktestDeal,
    Deal,
    DealType,
    EquityCurve,
    Portfolio,
    Strategy,
)


def test_list_strategies_payload_filters_real_history_and_enriches_metrics(db_session):
    now = datetime.now(UTC)
    real_account = Account(id="acc-real", name="Real", account_type="Real")
    demo_account = Account(id="acc-demo", name="Demo", account_type="Demo")
    real_strategy = Strategy(
        id="s-real",
        name="Alpha",
        live=True,
        real_account=True,
        account=real_account,
    )
    demo_strategy = Strategy(
        id="s-demo",
        name="Beta",
        live=False,
        real_account=False,
        account=demo_account,
    )
    db_session.add_all([real_account, demo_account, real_strategy, demo_strategy])
    db_session.flush()

    db_session.add_all(
        [
            Deal(
                timestamp=now - timedelta(days=5),
                ticket=1,
                strategy_id="s-real",
                symbol="EURUSD",
                type=DealType.BUY,
                volume=0.1,
                price=1.1,
                profit=120.0,
                commission=-2.0,
                swap=0.0,
            ),
            Deal(
                timestamp=now - timedelta(days=4),
                ticket=2,
                strategy_id="s-real",
                symbol="EURUSD",
                type=DealType.SELL,
                volume=0.1,
                price=1.2,
                profit=-20.0,
                commission=-1.0,
                swap=0.0,
            ),
            Deal(
                timestamp=now - timedelta(days=4, hours=12),
                ticket=4,
                strategy_id="s-real",
                symbol="EURUSD",
                type=DealType.BUY,
                volume=0.1,
                price=1.1,
                profit=0.0,
                commission=0.0,
                swap=0.0,
            ),
            Deal(
                timestamp=now - timedelta(days=4, hours=6),
                ticket=5,
                strategy_id="s-real",
                symbol="EURUSD",
                type=DealType.SELL,
                volume=0.1,
                price=1.1,
                profit=0.0,
                commission=0.0,
                swap=0.0,
            ),
            Deal(
                timestamp=now - timedelta(days=4, hours=3),
                ticket=6,
                strategy_id="s-real",
                symbol="EURUSD",
                type=DealType.BUY,
                volume=0.1,
                price=1.1,
                profit=0.0,
                commission=0.0,
                swap=0.0,
            ),
            Deal(
                timestamp=now - timedelta(days=3),
                ticket=3,
                strategy_id="s-demo",
                symbol="GBPUSD",
                type=DealType.BUY,
                volume=0.1,
                price=1.3,
                profit=50.0,
                commission=-1.0,
                swap=0.0,
            ),
            EquityCurve(
                strategy_id="s-real",
                timestamp=now - timedelta(hours=60),
                balance=1000.0,
                equity=1080.0,
            ),
            EquityCurve(
                strategy_id="s-real",
                timestamp=now - timedelta(days=2),
                balance=1000.0,
                equity=1050.0,
            ),
        ]
    )
    db_session.flush()

    payload = ds.list_strategies_payload(db_session, history_type="real")

    assert len(payload) == 1
    strategy = payload[0]
    assert strategy.id == "s-real"
    assert strategy.account_name == "Real"
    assert strategy.account_type == "Real"
    assert strategy.net_profit == pytest.approx(97.0)
    assert strategy.trades_count == 5
    assert strategy.last_seen_at is not None
    assert strategy.last_trade_at is not None
    assert strategy.max_drawdown == pytest.approx((1080.0 - 1050.0) / 1080.0)
    assert strategy.zombie_alert is True


def test_list_strategies_payload_filters_backtest_history(db_session):
    strategy = Strategy(id="s1", name="Alpha")
    db_session.add(strategy)
    db_session.flush()

    backtest = Backtest(
        strategy_id="s1",
        client_run_id=7,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        status="complete",
    )
    db_session.add(backtest)
    db_session.flush()
    db_session.add(
        BacktestDeal(
            backtest_id=backtest.id,
            timestamp=datetime(2026, 1, 1, 10, tzinfo=UTC),
            ticket=1,
            symbol="EURUSD",
            type=DealType.BUY,
            volume=0.1,
            price=1.1,
            profit=40.0,
            commission=-1.0,
            swap=0.0,
        )
    )
    db_session.flush()

    payload = ds.list_strategies_payload(db_session, history_type="backtest")

    assert [row.id for row in payload] == ["s1"]
    assert payload[0].backtest_net_profit == pytest.approx(39.0)


def test_get_portfolio_strategies_payload_returns_enriched_portfolio_strategies(
    db_session,
):
    account = Account(id="acc-1", name="Real", account_type="Real")
    strategy = Strategy(
        id="s1",
        name="Alpha",
        live=True,
        real_account=True,
        account=account,
    )
    portfolio = Portfolio(name="Main", strategies=[strategy])
    db_session.add_all([account, strategy, portfolio])
    db_session.flush()

    db_session.add_all(
        [
            Deal(
                timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                ticket=1,
                strategy_id="s1",
                symbol="EURUSD",
                type=DealType.BUY,
                volume=0.1,
                price=1.1,
                profit=46.0,
                commission=-1.0,
                swap=0.0,
            ),
            EquityCurve(
                strategy_id="s1",
                timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                balance=1000.0,
                equity=1000.0,
            ),
            EquityCurve(
                strategy_id="s1",
                timestamp=datetime(2026, 1, 2, tzinfo=UTC),
                balance=1000.0,
                equity=1100.0,
            ),
            EquityCurve(
                strategy_id="s1",
                timestamp=datetime(2026, 1, 3, tzinfo=UTC),
                balance=1000.0,
                equity=1045.0,
            ),
        ]
    )
    db_session.flush()

    payload = ds.get_portfolio_strategies_payload(db_session, portfolio.id)

    assert len(payload) == 1
    assert payload[0].id == "s1"
    assert payload[0].account_name == "Real"
    assert payload[0].net_profit == pytest.approx(45.0)
    assert payload[0].max_drawdown == pytest.approx((1100.0 - 1045.0) / 1100.0)
    assert payload[0].ret_dd == pytest.approx(0.9)
