from datetime import UTC, datetime
from unittest.mock import patch

import pandas as pd
import pytest
from trademachine.tradingmonitor_analytics.metrics import repository


def test_get_strategy_deals_uses_since_filter():
    expected = pd.DataFrame(
        {"strategy_id": ["s1"], "profit": [12.5]},
        index=pd.DatetimeIndex([datetime(2026, 1, 1, tzinfo=UTC)], name="timestamp"),
    )
    since = datetime(2026, 1, 1, tzinfo=UTC)

    with patch(
        "trademachine.tradingmonitor_analytics.metrics.repository.pd.read_sql",
        return_value=expected,
    ) as mock_read_sql:
        result = repository.get_strategy_deals("s1", since=since)

    assert result is expected
    query = str(mock_read_sql.call_args.args[0])
    assert "FROM deals" in query
    assert "timestamp >= :since" in query
    assert mock_read_sql.call_args.kwargs["params"] == {"sid": "s1", "since": since}
    assert mock_read_sql.call_args.kwargs["index_col"] == "timestamp"


def test_get_strategy_deals_without_since_uses_base_query():
    expected = pd.DataFrame(
        {"strategy_id": ["s1"], "profit": [12.5]},
        index=pd.DatetimeIndex([datetime(2026, 1, 1, tzinfo=UTC)], name="timestamp"),
    )

    with patch(
        "trademachine.tradingmonitor_analytics.metrics.repository.pd.read_sql",
        return_value=expected,
    ) as mock_read_sql:
        result = repository.get_strategy_deals("s1")

    assert result is expected
    query = str(mock_read_sql.call_args.args[0])
    assert "FROM deals" in query
    assert "timestamp >= :since" not in query
    assert mock_read_sql.call_args.kwargs["params"] == {"sid": "s1"}


def test_get_strategy_equity_curve_queries_equity_curve_table():
    expected = pd.DataFrame(
        {"equity": [1000.0]},
        index=pd.DatetimeIndex([datetime(2026, 1, 1, tzinfo=UTC)], name="timestamp"),
    )

    with patch(
        "trademachine.tradingmonitor_analytics.metrics.repository.pd.read_sql",
        return_value=expected,
    ) as mock_read_sql:
        result = repository.get_strategy_equity_curve("s1")

    assert result is expected
    query = str(mock_read_sql.call_args.args[0])
    assert "FROM equity_curve" in query
    assert mock_read_sql.call_args.kwargs["params"] == {"sid": "s1"}


def test_get_backtest_deals_queries_backtest_table():
    expected = pd.DataFrame(
        {"backtest_id": [7], "profit": [10.0]},
        index=pd.DatetimeIndex([datetime(2026, 1, 1, tzinfo=UTC)], name="timestamp"),
    )

    with patch(
        "trademachine.tradingmonitor_analytics.metrics.repository.pd.read_sql",
        return_value=expected,
    ) as mock_read_sql:
        result = repository.get_backtest_deals(7)

    assert result is expected
    query = str(mock_read_sql.call_args.args[0])
    assert "FROM backtest_deals" in query
    assert mock_read_sql.call_args.kwargs["params"] == {"bid": 7}


def test_get_backtest_equity_queries_backtest_equity_table():
    expected = pd.DataFrame(
        {"equity": [1000.0]},
        index=pd.DatetimeIndex([datetime(2026, 1, 1, tzinfo=UTC)], name="timestamp"),
    )

    with patch(
        "trademachine.tradingmonitor_analytics.metrics.repository.pd.read_sql",
        return_value=expected,
    ) as mock_read_sql:
        result = repository.get_backtest_equity(7)

    assert result is expected
    query = str(mock_read_sql.call_args.args[0])
    assert "FROM backtest_equity" in query
    assert mock_read_sql.call_args.kwargs["params"] == {"bid": 7}


def test_get_strategy_deals_raises_repository_error_on_query_error():
    with patch(
        "trademachine.tradingmonitor_analytics.metrics.repository.pd.read_sql",
        side_effect=RuntimeError("boom"),
    ):
        with pytest.raises(repository.MetricsRepositoryError) as exc_info:
            repository.get_strategy_deals("s1")

    assert "strategy deals for s1" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, RuntimeError)
