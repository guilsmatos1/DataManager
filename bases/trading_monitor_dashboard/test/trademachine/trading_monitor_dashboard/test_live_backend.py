from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from trademachine.trading_monitor_dashboard import routes
from trademachine.trading_monitor_dashboard.routes import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


@pytest.fixture
def mock_db():
    db = MagicMock()
    app.dependency_overrides[routes.get_db] = lambda: db
    try:
        yield db
    finally:
        app.dependency_overrides.clear()


def test_kill_strategy(mock_db):
    mock_db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
        id="strat1"
    )

    with patch(
        "trademachine.trading_monitor_dashboard.routes.send_kill_command",
        return_value=True,
    ) as mock_kill:
        response = client.post(
            "/api/strategies/strat1/kill",
            headers={"X-API-Key": "test-api-key-pytest"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "message": "Kill command sent to strategy strat1",
    }
    mock_kill.assert_called_once_with("strat1")


def test_kill_strategy_returns_404_for_unknown_strategy(mock_db):
    mock_db.query.return_value.filter.return_value.first.return_value = None

    response = client.post(
        "/api/strategies/missing/kill",
        headers={"X-API-Key": "test-api-key-pytest"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Strategy not found"


def test_summary_endpoint_uses_dashboard_overview_service(mock_db):
    with patch(
        "trademachine.trading_monitor_dashboard.routes.get_summary_payload",
        return_value={
            "strategies_count": 2,
            "portfolios_count": 1,
            "accounts_count": 1,
            "by_symbol": {"EURUSD": 2},
            "by_style": {"Trend": 2},
            "by_duration": {"Swing": 2},
        },
    ) as mock_summary:
        response = client.get(
            "/api/summary",
            headers={"X-API-Key": "test-api-key-pytest"},
        )

    assert response.status_code == 200
    assert response.json()["strategies_count"] == 2
    mock_summary.assert_called_once_with(mock_db)


def test_get_real_overview_uses_dashboard_overview_service(mock_db):
    with patch(
        "trademachine.trading_monitor_dashboard.routes.get_real_overview_payload",
        return_value={
            "mode": "real",
            "strategies": [{"id": "strat1", "equity_curve": []}],
            "totals": {
                "net_profit": 50.0,
                "floating_pnl": 10.0,
                "day_pnl": 5.0,
                "open_trades_count": 2,
                "pending_orders_count": 1,
                "counts_available": True,
            },
        },
    ) as mock_overview:
        response = client.get("/api/real", headers={"X-API-Key": "test-api-key-pytest"})

    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "real"
    assert data["totals"]["net_profit"] == 50.0
    mock_overview.assert_called_once_with(
        mock_db,
        max_points_per_strategy=2000,
    )


def test_get_real_daily_uses_dashboard_overview_service(mock_db):
    with patch(
        "trademachine.trading_monitor_dashboard.routes.get_real_daily_payload",
        return_value=[{"date": "2026-01-01", "net_profit": 12.5, "trades_count": None}],
    ) as mock_daily:
        response = client.get(
            "/api/real/daily",
            headers={"X-API-Key": "test-api-key-pytest"},
        )

    assert response.status_code == 200
    assert response.json()[0]["date"] == "2026-01-01"
    assert response.json()[0]["net_profit"] == 12.5
    mock_daily.assert_called_once_with(mock_db)


def test_get_real_recent_deals_uses_dashboard_overview_service(mock_db):
    with patch(
        "trademachine.trading_monitor_dashboard.routes.get_real_recent_deals_payload",
        return_value=[
            {
                "ticket": 7,
                "strategy_id": "s1",
                "strategy_name": "Alpha",
                "type": "buy",
                "net_profit": 15.0,
                "profit": 15.0,
                "commission": 0.0,
                "swap": 0.0,
            }
        ],
    ) as mock_recent:
        response = client.get(
            "/api/real/recent-deals?limit=10",
            headers={"X-API-Key": "test-api-key-pytest"},
        )

    assert response.status_code == 200
    assert response.json()[0]["ticket"] == 7
    mock_recent.assert_called_once_with(mock_db, limit=10)


def test_list_strategies_uses_dashboard_strategies_service(mock_db):
    with patch(
        "trademachine.trading_monitor_dashboard.routes.list_strategies_payload",
        return_value=[
            {
                "id": "s1",
                "name": "Alpha",
                "symbol": "EURUSD",
                "live": True,
                "real_account": True,
                "net_profit": 42.0,
            }
        ],
    ) as mock_list:
        response = client.get(
            "/api/strategies?history_type=real",
            headers={"X-API-Key": "test-api-key-pytest"},
        )

    assert response.status_code == 200
    assert response.json()[0]["net_profit"] == 42.0
    mock_list.assert_called_once_with(mock_db, "real")


def test_get_portfolio_strategies_uses_dashboard_strategies_service(mock_db):
    with patch(
        "trademachine.trading_monitor_dashboard.routes.get_portfolio_strategies_payload",
        return_value=[
            {
                "id": "s1",
                "name": "Alpha",
                "symbol": "EURUSD",
                "account_name": "Real",
                "net_profit": 18.0,
            }
        ],
    ) as mock_get:
        response = client.get(
            "/api/portfolios/7/strategies",
            headers={"X-API-Key": "test-api-key-pytest"},
        )

    assert response.status_code == 200
    assert response.json()[0]["net_profit"] == 18.0
    mock_get.assert_called_once_with(mock_db, 7)


def test_get_strategy_trade_stats_uses_dashboard_history_service(mock_db):
    with patch(
        "trademachine.trading_monitor_dashboard.routes.get_strategy_trade_stats_payload",
        return_value={"by_hour": [], "by_dow": []},
    ) as mock_get:
        response = client.get(
            "/api/strategies/s1/trade-stats",
            headers={"X-API-Key": "test-api-key-pytest"},
        )

    assert response.status_code == 200
    mock_get.assert_called_once_with(mock_db, "s1", None)


def test_get_strategy_trade_stats_passes_side_filter(mock_db):
    with patch(
        "trademachine.trading_monitor_dashboard.routes.get_strategy_trade_stats_payload",
        return_value={"by_hour": [], "by_dow": []},
    ) as mock_get:
        response = client.get(
            "/api/strategies/s1/trade-stats?side=buy",
            headers={"X-API-Key": "test-api-key-pytest"},
        )

    assert response.status_code == 200
    mock_get.assert_called_once_with(mock_db, "s1", "buy")


def test_get_strategy_daily_uses_dashboard_history_service(mock_db):
    with patch(
        "trademachine.trading_monitor_dashboard.routes.get_strategy_daily_payload",
        return_value=[{"date": "2026-01-01", "net_profit": 10.0}],
    ) as mock_get:
        response = client.get(
            "/api/strategies/s1/daily",
            headers={"X-API-Key": "test-api-key-pytest"},
        )

    assert response.status_code == 200
    assert response.json()[0]["net_profit"] == 10.0
    mock_get.assert_called_once_with(mock_db, "s1", None)


def test_get_strategy_deals_uses_dashboard_history_service(mock_db):
    with patch(
        "trademachine.trading_monitor_dashboard.routes.get_strategy_deals_payload",
        return_value={
            "items": [],
            "total": 0,
            "page": 1,
            "page_size": 50,
        },
    ) as mock_get:
        response = client.get(
            "/api/strategies/s1/deals?page=1&page_size=50&q=EUR",
            headers={"X-API-Key": "test-api-key-pytest"},
        )

    assert response.status_code == 200
    mock_get.assert_called_once_with(
        mock_db,
        "s1",
        page=1,
        page_size=50,
        q="EUR",
        side=None,
    )


def test_get_backtest_trade_stats_uses_dashboard_history_service(mock_db):
    with patch(
        "trademachine.trading_monitor_dashboard.routes.get_backtest_trade_stats_payload",
        return_value={"by_hour": [], "by_dow": []},
    ) as mock_get:
        response = client.get(
            "/api/backtests/9/trade-stats",
            headers={"X-API-Key": "test-api-key-pytest"},
        )

    assert response.status_code == 200
    mock_get.assert_called_once_with(mock_db, 9, None)


def test_get_backtest_daily_uses_dashboard_history_service(mock_db):
    with patch(
        "trademachine.trading_monitor_dashboard.routes.get_backtest_daily_payload",
        return_value=[{"date": "2026-01-01", "net_profit": 7.0}],
    ) as mock_get:
        response = client.get(
            "/api/backtests/9/daily",
            headers={"X-API-Key": "test-api-key-pytest"},
        )

    assert response.status_code == 200
    assert response.json()[0]["net_profit"] == 7.0
    mock_get.assert_called_once_with(mock_db, 9, None)


def test_get_backtest_deals_uses_dashboard_history_service(mock_db):
    with patch(
        "trademachine.trading_monitor_dashboard.routes.get_backtest_deals_payload",
        return_value={
            "items": [],
            "total": 0,
            "page": 1,
            "page_size": 50,
        },
    ) as mock_get:
        response = client.get(
            "/api/backtests/9/deals?page=1&page_size=50&side=sell",
            headers={"X-API-Key": "test-api-key-pytest"},
        )

    assert response.status_code == 200
    mock_get.assert_called_once_with(
        mock_db,
        9,
        page=1,
        page_size=50,
        side="sell",
    )


def test_get_backtest_deals_rejects_invalid_side(mock_db):
    with patch(
        "trademachine.trading_monitor_dashboard.routes.get_backtest_deals_payload",
    ) as mock_get:
        response = client.get(
            "/api/backtests/9/deals?page=1&page_size=50&side=short",
            headers={"X-API-Key": "test-api-key-pytest"},
        )

    assert response.status_code == 422
    mock_get.assert_not_called()


def test_datamanager_settings_test_uses_integration_service(mock_db):
    with patch(
        "trademachine.trading_monitor_dashboard.routes.test_datamanager_connection",
        return_value={"ok": True, "databases_count": 3},
    ) as mock_test:
        response = client.post(
            "/api/settings/datamanager/test",
            headers={"X-API-Key": "test-api-key-pytest"},
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "databases_count": 3}
    mock_test.assert_called_once_with(mock_db)


def test_datamanager_settings_endpoint_returns_api_key(mock_db):
    with patch(
        "trademachine.trading_monitor_dashboard.routes.load_datamanager_settings",
        return_value=routes.DataManagerSettings(
            url="http://localhost:8686",
            api_key="dm-secret-key",
            api_key_configured=True,
            timeout=30.0,
        ),
    ) as mock_load:
        response = client.get(
            "/api/settings/datamanager",
            headers={"X-API-Key": "test-api-key-pytest"},
        )

    assert response.status_code == 200
    assert response.json()["api_key"] == "dm-secret-key"
    mock_load.assert_called_once_with(mock_db)


def test_list_benchmarks_uses_service_payloads(mock_db):
    with patch(
        "trademachine.trading_monitor_dashboard.routes.list_benchmark_payloads",
        return_value=[
            {
                "id": 1,
                "name": "S&P 500",
                "source": "OPENBB",
                "asset": "SPY",
                "timeframe": "D1",
                "description": None,
                "is_default": True,
                "enabled": True,
                "last_synced_at": None,
                "last_error": None,
                "local_points": 42,
                "latest_price_timestamp": None,
            }
        ],
    ) as mock_list:
        response = client.get(
            "/api/benchmarks",
            headers={"X-API-Key": "test-api-key-pytest"},
        )

    assert response.status_code == 200
    assert response.json()[0]["asset"] == "SPY"
    mock_list.assert_called_once_with(mock_db)


def test_strategy_metrics_endpoint_uses_dashboard_metrics_service(mock_db):
    with patch(
        "trademachine.trading_monitor_dashboard.routes.get_strategy_metrics_payload",
        return_value={"Profit": 12.5},
    ) as mock_metrics:
        response = client.get(
            "/api/strategies/strat1/metrics",
            headers={"X-API-Key": "test-api-key-pytest"},
        )

    assert response.status_code == 200
    assert response.json()["Profit"] == 12.5
    mock_metrics.assert_called_once_with(mock_db, "strat1", None)


def test_strategy_metrics_endpoint_passes_side_filter(mock_db):
    with patch(
        "trademachine.trading_monitor_dashboard.routes.get_strategy_metrics_payload",
        return_value={"Profit": 12.5},
    ) as mock_metrics:
        response = client.get(
            "/api/strategies/strat1/metrics?side=sell",
            headers={"X-API-Key": "test-api-key-pytest"},
        )

    assert response.status_code == 200
    mock_metrics.assert_called_once_with(mock_db, "strat1", "sell")


def test_portfolio_metrics_endpoint_returns_422_for_validation_errors(mock_db):
    with patch(
        "trademachine.trading_monitor_dashboard.routes.get_portfolio_metrics_payload",
        side_effect=routes.DashboardMetricsValidationError(
            "No strategies in this portfolio"
        ),
    ) as mock_metrics:
        response = client.get(
            "/api/portfolios/7/metrics",
            headers={"X-API-Key": "test-api-key-pytest"},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "No strategies in this portfolio"
    mock_metrics.assert_called_once_with(mock_db, 7)


def test_portfolio_metrics_endpoint_returns_500_for_unexpected_value_error(mock_db):
    with patch(
        "trademachine.trading_monitor_dashboard.routes.get_portfolio_metrics_payload",
        side_effect=ValueError("cannot reindex on an axis with duplicate labels"),
    ) as mock_metrics:
        response = client.get(
            "/api/portfolios/7/metrics",
            headers={"X-API-Key": "test-api-key-pytest"},
        )

    assert response.status_code == 500
    assert response.json()["detail"] == (
        "An internal error occurred during metrics calculation"
    )
    mock_metrics.assert_called_once_with(mock_db, 7)


def test_portfolio_equity_breakdown_endpoint_uses_dashboard_metrics_service(mock_db):
    with patch(
        "trademachine.trading_monitor_dashboard.routes.get_portfolio_equity_breakdown_payload",
        return_value={
            "total": [{"timestamp": datetime(2026, 1, 1, tzinfo=UTC), "equity": 150.0}],
            "strategies": {
                "s1": {
                    "name": "Alpha",
                    "points": [
                        {
                            "timestamp": datetime(2026, 1, 1, tzinfo=UTC),
                            "equity": 150.0,
                        }
                    ],
                }
            },
        },
    ) as mock_breakdown:
        response = client.get(
            "/api/portfolios/7/equity/breakdown",
            headers={"X-API-Key": "test-api-key-pytest"},
        )

    assert response.status_code == 200
    assert response.json()["total"][0]["equity"] == 150.0
    mock_breakdown.assert_called_once_with(mock_db, 7)


def test_list_portfolios_uses_dashboard_analysis_service(mock_db):
    with patch(
        "trademachine.trading_monitor_dashboard.routes.list_portfolios_payload",
        return_value=[
            {
                "id": 1,
                "name": "Main",
                "strategy_ids": ["s1"],
                "live": False,
                "real_account": False,
                "net_profit": 12.5,
            }
        ],
    ) as mock_list:
        response = client.get(
            "/api/portfolios?mode=real",
            headers={"X-API-Key": "test-api-key-pytest"},
        )

    assert response.status_code == 200
    assert response.json()[0]["net_profit"] == 12.5
    mock_list.assert_called_once_with(mock_db, "real")


def test_advanced_analysis_endpoint_uses_dashboard_analysis_service(mock_db):
    with patch(
        "trademachine.trading_monitor_dashboard.routes.get_advanced_analysis_payload",
        return_value={
            "metrics": {"Profit": 12.5},
            "equity_curve": [],
            "comparison_curve": [],
            "benchmark": None,
            "selected_strategies": ["s1"],
            "history_type": "real",
            "strategy_contributions": [],
        },
    ) as mock_analysis:
        response = client.get(
            "/api/advanced-analysis?strategy_ids=s1&history_type=real",
            headers={"X-API-Key": "test-api-key-pytest"},
        )

    assert response.status_code == 200
    assert response.json()["metrics"]["Profit"] == 12.5
    mock_analysis.assert_called_once_with(
        mock_db,
        strategy_ids=["s1"],
        history_type="real",
        date_from=None,
        date_to=None,
        initial_balance=None,
        benchmark_id=None,
        side=None,
    )


def test_list_strategy_backtests_uses_dashboard_analysis_service(mock_db):
    with patch(
        "trademachine.trading_monitor_dashboard.routes.list_strategy_backtests_payload",
        return_value=[
            {
                "id": 7,
                "strategy_id": "s1",
                "client_run_id": 123,
                "net_profit": 18.0,
            }
        ],
    ) as mock_list:
        response = client.get(
            "/api/strategies/s1/backtests",
            headers={"X-API-Key": "test-api-key-pytest"},
        )

    assert response.status_code == 200
    assert response.json()[0]["net_profit"] == 18.0
    mock_list.assert_called_once_with(mock_db, "s1")


def test_get_backtest_uses_dashboard_analysis_service(mock_db):
    with patch(
        "trademachine.trading_monitor_dashboard.routes.get_backtest_payload",
        return_value={
            "id": 9,
            "strategy_id": "s1",
            "client_run_id": 123,
            "net_profit": 22.0,
        },
    ) as mock_get:
        response = client.get(
            "/api/backtests/9",
            headers={"X-API-Key": "test-api-key-pytest"},
        )

    assert response.status_code == 200
    assert response.json()["net_profit"] == 22.0
    mock_get.assert_called_once_with(mock_db, 9)


def test_delete_symbol_returns_409_when_symbol_is_still_referenced(mock_db):
    symbol_query = MagicMock()
    strategy_query = MagicMock()

    mock_db.query.side_effect = [symbol_query, strategy_query]
    symbol_query.filter.return_value.first.return_value = SimpleNamespace(
        id=1, name="EURUSD"
    )
    strategy_query.filter.return_value.first.return_value = SimpleNamespace(id="s1")

    response = client.delete(
        "/api/symbols/1",
        headers={"X-API-Key": "test-api-key-pytest"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Symbol is still referenced by strategies"
