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
                profit=0.0,
                commission=0.0,
                swap=0.0,
            ),
            Deal(
                timestamp=datetime(2026, 1, 6, 10, tzinfo=UTC),
                ticket=12,
                strategy_id="s1",
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

    daily_payload = dh.get_strategy_daily_payload(db_session, "s1", side="sell")
    deals_payload = dh.get_strategy_deals_payload(
        db_session,
        "s1",
        page=1,
        page_size=10,
        side="sell",
    )

    # side="sell" follows the literal SELL rows shown in the history table.
    assert daily_payload == [{"date": "2026-01-06", "net_profit": 4.0}]
    assert deals_payload.total == 1
    assert deals_payload.items[0].ticket == 12


def test_get_strategy_history_payloads_support_sell_filter_by_deal_type(db_session):
    strategy = Strategy(id="s1", name="Alpha")
    db_session.add(strategy)
    db_session.flush()

    db_session.add_all(
        [
            Deal(
                timestamp=datetime(2026, 1, 5, 10, tzinfo=UTC),
                ticket=21,
                strategy_id="s1",
                symbol="EURUSD",
                type=DealType.BUY,
                volume=1.0,
                price=1.1,
                profit=0.0,
                commission=0.0,
                swap=0.0,
            ),
            Deal(
                timestamp=datetime(2026, 1, 6, 11, tzinfo=UTC),
                ticket=22,
                strategy_id="s1",
                symbol="EURUSD",
                type=DealType.SELL,
                volume=2.0,
                price=1.2,
                profit=20.0,
                commission=-2.0,
                swap=0.0,
            ),
        ]
    )
    db_session.flush()

    daily_payload = dh.get_strategy_daily_payload(db_session, "s1", side="sell")
    trade_stats_payload = dh.get_strategy_trade_stats_payload(
        db_session, "s1", side="sell"
    )

    assert daily_payload == [{"date": "2026-01-06", "net_profit": 18.0}]
    assert trade_stats_payload["by_hour"][11]["count"] == 1
    assert trade_stats_payload["by_hour"][11]["net_profit"] == pytest.approx(18.0)
    assert trade_stats_payload["by_dow"][1]["count"] == 1
    assert trade_stats_payload["by_dow"][1]["net_profit"] == pytest.approx(18.0)


def test_get_portfolio_deals_payload_search_matches_strategy_id_and_deal_type(
    db_session,
):
    db_session.add_all(
        [
            Strategy(id="s1", name="Alpha"),
            Strategy(id="s2", name="Beta"),
            Deal(
                timestamp=datetime(2026, 1, 5, 10, tzinfo=UTC),
                ticket=31,
                strategy_id="s1",
                symbol="EURUSD",
                type=DealType.BUY,
                volume=1.0,
                price=1.1,
                profit=5.0,
                commission=0.0,
                swap=0.0,
            ),
            Deal(
                timestamp=datetime(2026, 1, 6, 11, tzinfo=UTC),
                ticket=32,
                strategy_id="s2",
                symbol="GBPUSD",
                type=DealType.SELL,
                volume=1.0,
                price=1.2,
                profit=7.0,
                commission=0.0,
                swap=0.0,
            ),
        ]
    )
    db_session.flush()

    strategy_match = dh.get_portfolio_deals_payload(
        db_session,
        ["s1", "s2"],
        page=1,
        page_size=10,
        q="s2",
    )
    deal_type_match = dh.get_portfolio_deals_payload(
        db_session,
        ["s1", "s2"],
        page=1,
        page_size=10,
        q="sell",
    )

    assert strategy_match.total == 1
    assert strategy_match.items[0].strategy_id == "s2"
    assert deal_type_match.total == 1
    assert deal_type_match.items[0].ticket == 32


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
                profit=0.0,
                commission=0.0,
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
                profit=18.0,
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

    # side="sell" follows the literal SELL rows shown in the backtest history.
    assert daily_payload == [{"date": "2026-01-06", "net_profit": 17.0}]
    assert deals_payload.total == 1
    assert deals_payload.items[0].ticket == 2


def test_get_backtest_history_payloads_support_sell_filter_by_deal_type(db_session):
    strategy = Strategy(id="s1", name="Alpha")
    backtest = Backtest(
        strategy_id="s1",
        client_run_id=8,
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
                ticket=31,
                symbol="EURUSD",
                type=DealType.BUY,
                volume=1.0,
                price=1.1,
                profit=0.0,
                commission=0.0,
                swap=0.0,
            ),
            BacktestDeal(
                backtest_id=backtest.id,
                timestamp=datetime(2026, 1, 6, 11, tzinfo=UTC),
                ticket=32,
                symbol="EURUSD",
                type=DealType.SELL,
                volume=2.0,
                price=1.2,
                profit=24.0,
                commission=-4.0,
                swap=0.0,
            ),
        ]
    )
    db_session.flush()

    daily_payload = dh.get_backtest_daily_payload(db_session, backtest.id, side="sell")
    trade_stats_payload = dh.get_backtest_trade_stats_payload(
        db_session, backtest.id, side="sell"
    )

    assert daily_payload == [{"date": "2026-01-06", "net_profit": 20.0}]
    assert trade_stats_payload["by_hour"][11]["count"] == 1
    assert trade_stats_payload["by_hour"][11]["net_profit"] == pytest.approx(20.0)
    assert trade_stats_payload["by_dow"][1]["count"] == 1
    assert trade_stats_payload["by_dow"][1]["net_profit"] == pytest.approx(20.0)
