from datetime import UTC, datetime
from unittest.mock import patch

import pandas as pd
import pytest
from trademachine.tradingmonitor.metrics import repository


def test_get_strategy_profit_aggregate_uses_daily_view():
    expected = pd.DataFrame(
        {"net_profit": [12.5], "trades_count": [3]},
        index=pd.DatetimeIndex([datetime(2026, 1, 1, tzinfo=UTC)], name="timestamp"),
    )

    with patch(
        "trademachine.tradingmonitor.metrics.repository._read_sql",
        return_value=expected,
    ) as mock_read_sql:
        result = repository.get_strategy_profit_aggregate("s1", resolution="daily")

    assert result is expected
    query, params = mock_read_sql.call_args.args
    assert "strategy_pnl_daily" in query
    assert "strategy_id = :sid" in query
    assert params == {"sid": "s1", "since": None}


def test_get_multi_strategy_profit_aggregate_uses_hourly_view_and_since():
    expected = pd.DataFrame(
        {
            "strategy_id": ["s1", "s2"],
            "net_profit": [10.0, -5.0],
            "trades_count": [2, 1],
        },
        index=pd.DatetimeIndex(
            [
                datetime(2026, 1, 1, 10, tzinfo=UTC),
                datetime(2026, 1, 1, 11, tzinfo=UTC),
            ],
            name="timestamp",
        ),
    )
    since = datetime(2026, 1, 1, tzinfo=UTC)

    with patch(
        "trademachine.tradingmonitor.metrics.repository.pd.read_sql",
        return_value=expected,
    ) as mock_read_sql:
        result = repository.get_multi_strategy_profit_aggregate(
            ["s1", "s1", "s2"], resolution="hourly", since=since
        )

    assert result is expected
    query = mock_read_sql.call_args.args[0]
    assert "strategy_pnl_hourly" in str(query)
    assert mock_read_sql.call_args.kwargs["params"] == {
        "sids": ["s1", "s2"],
        "since": since,
    }
    assert mock_read_sql.call_args.kwargs["index_col"] == "timestamp"


def test_get_strategy_profit_aggregate_rejects_unknown_resolution():
    with pytest.raises(ValueError, match="Unsupported profit aggregate resolution"):
        repository.get_strategy_profit_aggregate("s1", resolution="weekly")


def test_get_multi_strategy_profit_aggregate_between_uses_until():
    expected = pd.DataFrame(
        {
            "strategy_id": ["s1"],
            "net_profit": [10.0],
            "trades_count": [2],
        },
        index=pd.DatetimeIndex(
            [datetime(2026, 1, 2, tzinfo=UTC)],
            name="timestamp",
        ),
    )
    since = datetime(2026, 1, 1, tzinfo=UTC)
    until = datetime(2026, 1, 31, tzinfo=UTC)

    with patch(
        "trademachine.tradingmonitor.metrics.repository.pd.read_sql",
        return_value=expected,
    ) as mock_read_sql:
        result = repository.get_multi_strategy_profit_aggregate_between(
            ["s1", "s1"], resolution="daily", since=since, until=until
        )

    assert result is expected
    query = mock_read_sql.call_args.args[0]
    assert "strategy_pnl_daily" in str(query)
    assert "bucket <= :until" in str(query)
    assert mock_read_sql.call_args.kwargs["params"] == {
        "sids": ["s1"],
        "since": since,
        "until": until,
    }


def test_get_multi_strategy_deals_between_uses_until():
    expected = pd.DataFrame(
        {
            "strategy_id": ["s1"],
            "type": ["BUY"],
            "profit": [10.0],
            "commission": [0.0],
            "swap": [0.0],
        },
        index=pd.DatetimeIndex(
            [datetime(2026, 1, 2, tzinfo=UTC)],
            name="timestamp",
        ),
    )
    since = datetime(2026, 1, 1, tzinfo=UTC)
    until = datetime(2026, 1, 31, tzinfo=UTC)

    with patch(
        "trademachine.tradingmonitor.metrics.repository.pd.read_sql",
        return_value=expected,
    ) as mock_read_sql:
        result = repository.get_multi_strategy_deals_between(
            ["s1", "s1"], since=since, until=until
        )

    assert result is expected
    query = mock_read_sql.call_args.args[0]
    assert "FROM deals" in str(query)
    assert "timestamp <= :until" in str(query)
    assert mock_read_sql.call_args.kwargs["params"] == {
        "sids": ["s1"],
        "since": since,
        "until": until,
    }


def test_get_multi_strategy_equity_curve_between_uses_until():
    expected = pd.DataFrame(
        {
            "strategy_id": ["s1"],
            "equity": [1000.0],
        },
        index=pd.DatetimeIndex(
            [datetime(2026, 1, 2, tzinfo=UTC)],
            name="timestamp",
        ),
    )
    since = datetime(2026, 1, 1, tzinfo=UTC)
    until = datetime(2026, 1, 31, tzinfo=UTC)

    with patch(
        "trademachine.tradingmonitor.metrics.repository.pd.read_sql",
        return_value=expected,
    ) as mock_read_sql:
        result = repository.get_multi_strategy_equity_curve_between(
            ["s1"], since=since, until=until
        )

    assert result is expected
    query = mock_read_sql.call_args.args[0]
    assert "FROM equity_curve" in str(query)
    assert "timestamp <= :until" in str(query)
    assert mock_read_sql.call_args.kwargs["params"] == {
        "sids": ["s1"],
        "since": since,
        "until": until,
    }


def test_get_multi_strategy_equity_aggregate_between_uses_daily_view():
    expected = pd.DataFrame(
        {
            "strategy_id": ["s1"],
            "equity": [1000.0],
        },
        index=pd.DatetimeIndex(
            [datetime(2026, 1, 2, tzinfo=UTC)],
            name="timestamp",
        ),
    )

    with patch(
        "trademachine.tradingmonitor.metrics.repository.pd.read_sql",
        return_value=expected,
    ) as mock_read_sql:
        result = repository.get_multi_strategy_equity_aggregate_between(
            ["s1"], resolution="daily"
        )

    assert result is expected
    query = mock_read_sql.call_args.args[0]
    assert "strategy_equity_daily_last" in str(query)
    assert mock_read_sql.call_args.kwargs["params"] == {
        "sids": ["s1"],
        "since": None,
        "until": None,
    }
