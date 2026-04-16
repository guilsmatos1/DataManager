from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text
from trademachine.tradingmonitor_storage.db.aggregates import (
    get_strategy_daily_profit_rows,
    get_strategy_intraday_profit_map,
    get_strategy_net_profit_map,
    get_strategy_trade_count_map,
)
from trademachine.tradingmonitor_storage.db.models import Deal, DealType, Strategy


def test_daily_aggregate_helpers_prefer_precomputed_relation(db_session):
    db_session.add(Strategy(id="s1", name="Alpha"))
    db_session.add(
        Deal(
            timestamp=datetime(2026, 1, 1, 12, tzinfo=UTC),
            ticket=1,
            strategy_id="s1",
            symbol="EURUSD",
            type=DealType.BUY,
            volume=0.1,
            price=1.1,
            profit=10.0,
            commission=-1.0,
            swap=0.0,
        )
    )
    db_session.flush()

    db_session.execute(
        text(
            """
            CREATE TABLE strategy_pnl_daily (
                bucket TEXT NOT NULL,
                strategy_id TEXT NOT NULL,
                net_profit NUMERIC NOT NULL,
                trades_count INTEGER NOT NULL
            )
            """
        )
    )
    db_session.execute(
        text(
            """
            INSERT INTO strategy_pnl_daily (bucket, strategy_id, net_profit, trades_count)
            VALUES ('2026-01-01 00:00:00+00:00', 's1', 123.45, 7)
            """
        )
    )
    db_session.flush()

    assert get_strategy_net_profit_map(db_session, ["s1"]) == {"s1": 123.45}
    assert get_strategy_trade_count_map(db_session, ["s1"]) == {"s1": 7}
    assert get_strategy_daily_profit_rows(db_session, ["s1"]) == [
        {"date": "2026-01-01", "net_profit": 123.45}
    ]


def test_intraday_aggregate_helper_prefers_hourly_relation(db_session):
    db_session.execute(
        text(
            """
            CREATE TABLE strategy_pnl_hourly (
                bucket DATETIME NOT NULL,
                strategy_id TEXT NOT NULL,
                net_profit NUMERIC NOT NULL,
                trades_count INTEGER NOT NULL
            )
            """
        )
    )
    db_session.execute(
        text(
            """
            INSERT INTO strategy_pnl_hourly (bucket, strategy_id, net_profit, trades_count)
            VALUES
                ('2026-01-01 03:00:00.000000', 's1', 10.0, 1),
                ('2026-01-01 04:00:00.000000', 's1', -2.5, 1),
                ('2026-01-01 05:00:00.000000', 's2', 7.0, 1)
            """
        )
    )
    db_session.flush()

    assert get_strategy_intraday_profit_map(
        db_session,
        strategy_ids=["s1", "s2"],
        day_start_utc=datetime(2026, 1, 1, 3),
        now_utc=datetime(2026, 1, 1, 5, 30),
    ) == {"s1": 7.5, "s2": 7.0}


def test_daily_profit_rows_can_group_using_local_timezone(db_session):
    db_session.add(Strategy(id="s1", name="Alpha"))
    db_session.add_all(
        [
            Deal(
                timestamp=datetime(2026, 4, 9, 20, 30, tzinfo=UTC),
                ticket=1,
                strategy_id="s1",
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
                strategy_id="s1",
                symbol="EURUSD",
                type=DealType.SELL,
                volume=0.1,
                price=1.2,
                profit=20.0,
                commission=-2.0,
                swap=0.0,
            ),
        ]
    )
    db_session.flush()

    assert get_strategy_daily_profit_rows(
        db_session,
        ["s1"],
        timezone=ZoneInfo("Europe/Athens"),
    ) == [
        {"date": "2026-04-09", "net_profit": 38.0},
        {"date": "2026-04-10", "net_profit": 18.0},
    ]
