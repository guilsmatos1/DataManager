from datetime import UTC, datetime

import pytest
from trademachine.tradingmonitor_analytics.services import dashboard_history as dh
from trademachine.tradingmonitor_storage.db.models import (
    Backtest,
    BacktestDeal,
    Deal,
    DealType,
    Strategy,
)


def test_get_strategy_trade_stats_payload_groups_by_hour_and_weekday(db_session):
    strategy = Strategy(id="s1", name="Alpha")
    db_session.add(strategy)
    db_session.flush()

    db_session.add_all(
        [
            Deal(
                timestamp=datetime(2026, 1, 5, 10, tzinfo=UTC),
                ticket=1,
                strategy_id="s1",
                symbol="EURUSD",
                type=DealType.BUY,
                volume=0.1,
                price=1.1,
                profit=20.0,
                commission=-1.0,
                swap=0.0,
            ),
            Deal(
                timestamp=datetime(2026, 1, 5, 10, 30, tzinfo=UTC),
                ticket=2,
                strategy_id="s1",
                symbol="EURUSD",
                type=DealType.SELL,
                volume=0.1,
                price=1.2,
                profit=10.0,
                commission=-1.0,
                swap=0.0,
            ),
        ]
    )
    db_session.flush()

    payload = dh.get_strategy_trade_stats_payload(db_session, "s1")

    assert payload["by_hour"][10]["count"] == 2
    assert payload["by_hour"][10]["net_profit"] == pytest.approx(28.0)
    assert payload["by_dow"][0]["label"] == "Mon"
    assert payload["by_dow"][0]["count"] == 2


def test_get_strategy_daily_and_deals_payload_support_filters(db_session):
    strategy = Strategy(id="s1", name="Alpha")
    db_session.add(strategy)
    db_session.flush()

    db_session.add_all(
        [
            Deal(
                timestamp=datetime(2026, 1, 5, 10, tzinfo=UTC),
                ticket=11,
                strategy_id="s1",
                symbol="EURUSD",
                type=DealType.BUY,
                volume=0.1,
                price=1.1,
                profit=20.0,
                commission=-1.0,
                swap=0.0,
            ),
            Deal(
                timestamp=datetime(2026, 1, 6, 10, tzinfo=UTC),
                ticket=12,
                strategy_id="s1",
                symbol="GBPUSD",
                type=DealType.SELL,
                volume=0.1,
                price=1.2,
                profit=5.0,
                commission=-1.0,
                swap=0.0,
            ),
        ]
    )
    db_session.flush()

    daily_payload = dh.get_strategy_daily_payload(db_session, "s1", side="buy")
    deals_payload = dh.get_strategy_deals_payload(
        db_session,
        "s1",
        page=1,
        page_size=10,
        q="GBP",
        side=None,
    )

    # side="buy" → P&L comes from SELL deals (close long positions)
    assert daily_payload == [{"date": "2026-01-06", "net_profit": 4.0}]
    assert deals_payload.total == 1
    assert deals_payload.items[0].ticket == 12


def test_get_backtest_trade_stats_payload_groups_by_hour_and_weekday(db_session):
    strategy = Strategy(id="s1", name="Alpha")
    backtest = Backtest(
        strategy_id="s1",
        client_run_id=7,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        status="complete",
    )
    db_session.add_all([strategy, backtest])
    db_session.flush()

    db_session.add_all(
        [
            BacktestDeal(
                backtest_id=backtest.id,
                timestamp=datetime(2026, 1, 6, 14, tzinfo=UTC),
                ticket=1,
                symbol="EURUSD",
                type=DealType.BUY,
                volume=0.1,
                price=1.1,
                profit=30.0,
                commission=-2.0,
                swap=0.0,
            ),
            BacktestDeal(
                backtest_id=backtest.id,
                timestamp=datetime(2026, 1, 6, 14, 5, tzinfo=UTC),
                ticket=2,
                symbol="EURUSD",
                type=DealType.SELL,
                volume=0.1,
                price=1.2,
                profit=5.0,
                commission=-1.0,
                swap=0.0,
            ),
        ]
    )
    db_session.flush()

    payload = dh.get_backtest_trade_stats_payload(db_session, backtest.id)

    assert payload["by_hour"][14]["count"] == 2
    assert payload["by_hour"][14]["net_profit"] == pytest.approx(32.0)
    assert payload["by_dow"][1]["label"] == "Tue"
    assert payload["by_dow"][1]["count"] == 2


def test_get_backtest_daily_and_deals_payload_support_side_filter(db_session):
    strategy = Strategy(id="s1", name="Alpha")
    backtest = Backtest(
        strategy_id="s1",
        client_run_id=7,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        status="complete",
    )
    db_session.add_all([strategy, backtest])
    db_session.flush()

    db_session.add_all(
        [
            BacktestDeal(
                backtest_id=backtest.id,
                timestamp=datetime(2026, 1, 5, 10, tzinfo=UTC),
                ticket=1,
                symbol="EURUSD",
                type=DealType.BUY,
                volume=0.1,
                price=1.1,
                profit=18.0,
                commission=-1.0,
                swap=0.0,
            ),
            BacktestDeal(
                backtest_id=backtest.id,
                timestamp=datetime(2026, 1, 6, 11, tzinfo=UTC),
                ticket=2,
                symbol="EURUSD",
                type=DealType.SELL,
                volume=0.1,
                price=1.2,
                profit=7.0,
                commission=-1.0,
                swap=0.0,
            ),
        ]
    )
    db_session.flush()

    daily_payload = dh.get_backtest_daily_payload(db_session, backtest.id, side="sell")
    deals_payload = dh.get_backtest_deals_payload(
        db_session,
        backtest.id,
        page=1,
        page_size=10,
        side="sell",
    )

    # side="sell" → P&L comes from BUY deals (close short positions)
    assert daily_payload == [{"date": "2026-01-05", "net_profit": 17.0}]
    # deals table still filters by execution direction: SELL deals for "short"
    assert deals_payload.total == 1
    assert deals_payload.items[0].ticket == 2
