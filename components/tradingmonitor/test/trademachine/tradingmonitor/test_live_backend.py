from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# We need to import the router after setting up environment variables if necessary,
# but conftest.py already sets API_KEY.
from trademachine.trading_monitor_dashboard.routes import router

# Create a test app and include the router
app = FastAPI()
app.include_router(router)
client = TestClient(app)


@pytest.fixture
def mock_facade():
    with patch("trademachine.trading_monitor_dashboard.routes.facade") as m:
        yield m


def test_kill_all_strategies(mock_facade):
    """Test the /strategies/kill-all endpoint."""
    # Setup mock
    mock_facade.strategies.get_real_strategies.return_value = [
        {"id": "strat1", "name": "Strategy 1"},
        {"id": "strat2", "name": "Strategy 2"},
    ]
    # First succeeds, second fails
    mock_facade.send_kill_command.side_effect = [True, False]

    response = client.post(
        "/api/strategies/kill-all", headers={"X-API-Key": "test-api-key-pytest"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "Kill command sent to 1 strategies. 1 failed to send." in data["message"]
    assert mock_facade.send_kill_command.call_count == 2


def test_kill_all_strategies_none(mock_facade):
    """Test /strategies/kill-all when no real strategies exist."""
    mock_facade.strategies.get_real_strategies.return_value = []

    response = client.post(
        "/api/strategies/kill-all", headers={"X-API-Key": "test-api-key-pytest"}
    )

    assert response.status_code == 200
    data = response.json()
    assert "No real strategies found to kill." in data["message"]


def test_get_real_overview_aggregated(mock_facade):
    """Test the /real endpoint for aggregated equity and last_update."""
    # Setup mock data for two strategies
    mock_facade.strategies.get_real_strategies.return_value = [
        {"id": "strat1", "name": "S1", "symbol": "EURUSD", "initial_balance": 1000},
        {"id": "strat2", "name": "S2", "symbol": "GBPUSD", "initial_balance": 2000},
    ]
    mock_facade.deals.get_net_profit_by_strategies.return_value = {
        "strat1": 100.0,
        "strat2": -50.0,
    }
    mock_facade.equity.get_latest_by_strategies.return_value = {
        "strat1": {"balance": 1000.0, "equity": 1100.0},
        "strat2": {"balance": 2000.0, "equity": 1950.0},
    }

    ts1 = "2024-01-01T12:00:00+00:00"
    ts2 = "2024-01-01T12:05:00+00:00"
    ts3 = "2024-01-01T12:10:00+00:00"

    mock_facade.equity.get_by_strategies.return_value = {
        "strat1": [
            {"timestamp": ts1, "equity": 1050.0},
            {"timestamp": ts2, "equity": 1100.0},
        ],
        "strat2": [
            {"timestamp": ts2, "equity": 2000.0},
            {"timestamp": ts3, "equity": 1950.0},
        ],
    }

    response = client.get("/api/real", headers={"X-API-Key": "test-api-key-pytest"})

    assert response.status_code == 200
    data = response.json()

    # Check strategies list
    assert len(data["strategies"]) == 2

    s1 = next(s for s in data["strategies"] if s["id"] == "strat1")
    assert s1["last_update"] == ts2

    s2 = next(s for s in data["strategies"] if s["id"] == "strat2")
    assert s2["last_update"] == ts3

    # Check totals
    assert data["totals"]["net_profit"] == 50.0  # 100 - 50

    # Check aggregated_equity
    assert "aggregated_equity" in data
    agg = data["aggregated_equity"]
    assert len(agg) > 0

    # Check last point of aggregated equity
    # Strat1 last point is at ts2 (1100), Strat2 last point is at ts3 (1950).
    # After ffill and sum, the point at ts3 should include both.
    last_agg_point = agg[-1]
    assert last_agg_point["equity"] == 3050.0  # 1100 (ffilled) + 1950


def test_get_real_overview_empty(mock_facade):
    """Test /real when no real strategies exist."""
    mock_facade.strategies.get_real_strategies.return_value = []

    response = client.get("/api/real", headers={"X-API-Key": "test-api-key-pytest"})

    assert response.status_code == 200
    data = response.json()
    assert data["strategies"] == []
    assert data["aggregated_equity"] == []
