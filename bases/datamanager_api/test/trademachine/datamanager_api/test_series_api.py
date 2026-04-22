from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from trademachine.datamanager_api import router


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(router.scheduler, "start", lambda: None)
    monkeypatch.setattr(router.scheduler, "shutdown", lambda: None)
    monkeypatch.setattr(router.settings, "api_key", "test-key")
    with TestClient(router.app) as test_client:
        yield test_client


def test_search_series_endpoint(client, monkeypatch):
    manager = MagicMock()
    manager.search_series.return_value = pd.DataFrame(
        [{"series_id": "CPIAUCSL", "title": "Inflation"}]
    )
    monkeypatch.setattr(router, "series_manager", manager)

    response = client.get(
        "/series/search",
        params={"source": "fred", "query": "inflation"},
        headers={"X-API-Key": "test-key"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "series": [{"index": 0, "series_id": "CPIAUCSL", "title": "Inflation"}]
    }
    manager.search_series.assert_called_once_with(source="fred", query="inflation")


def test_download_series_endpoint_runs_background_task(client, monkeypatch):
    manager = MagicMock()
    monkeypatch.setattr(router, "series_manager", manager)

    response = client.post(
        "/series/download",
        json={"source": "fred", "series_id": "CPIAUCSL", "frequency": "m"},
        headers={"X-API-Key": "test-key"},
    )

    assert response.status_code == 200
    manager.download_series.assert_called_once_with(
        "fred",
        "CPIAUCSL",
        None,
        None,
        "m",
    )


def test_get_series_data_endpoint_returns_parquet(client, monkeypatch):
    manager = MagicMock()
    manager.load_series_data.return_value = pd.DataFrame(
        {"Value": [1.0, 2.0]},
        index=pd.date_range("2024-01-01", periods=2, freq="D"),
    )
    monkeypatch.setattr(router, "series_manager", manager)

    response = client.get(
        "/series/data/fred/CPIAUCSL",
        headers={"X-API-Key": "test-key"},
    )

    payload = pd.read_parquet(BytesIO(response.content), engine="pyarrow")

    assert response.status_code == 200
    assert payload["Value"].tolist() == [1.0, 2.0]


def test_series_info_and_delete_endpoints(client, monkeypatch):
    manager = MagicMock()
    manager.info_series.return_value = {
        "source": "fred",
        "series_id": "DFF",
        "title": "Federal Funds Effective Rate",
        "frequency": "Daily, 7-Day",
        "rows": 10,
    }
    manager.delete_series.return_value = True
    monkeypatch.setattr(router, "series_manager", manager)

    info_response = client.get(
        "/series/info/fred/DFF",
        headers={"X-API-Key": "test-key"},
    )
    delete_response = client.post(
        "/series/delete",
        json={"source": "fred", "series_id": "DFF"},
        headers={"X-API-Key": "test-key"},
    )

    assert info_response.status_code == 200
    assert info_response.json()["series_id"] == "DFF"
    assert delete_response.status_code == 200
    assert delete_response.json()["status"] == "success"
    manager.info_series.assert_called_once_with("fred", "DFF")
    manager.delete_series.assert_called_once_with("fred", "DFF")


def test_resample_endpoint_queues_background_tasks(client, monkeypatch):
    mock_manager = MagicMock()
    monkeypatch.setattr(router, "manager", mock_manager)

    response = client.post(
        "/resample",
        json={"source": "dukascopy", "asset": "EURUSD,GBPUSD", "timeframes": "M5,H1"},
        headers={"X-API-Key": "test-key"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "EURUSD,GBPUSD" in data["message"]
    assert "M5,H1" in data["message"]


def test_quality_endpoint_returns_report(client, monkeypatch):
    mock_manager = MagicMock()
    mock_manager.check_quality.return_value = {
        "source": "dukascopy",
        "asset": "EURUSD",
        "timeframe": "M1",
        "total_rows": 1000,
        "ohlc_relation_errors": 0,
        "non_positive_price_errors": 0,
        "spike_errors": 0,
        "frozen_bar_errors": 0,
        "duplicate_index_errors": 0,
        "ordering_errors": 0,
        "gap_count": 2,
        "first_failure_timestamps": [],
        "first_gap_timestamps": ["2024-01-02 00:00:00"],
    }
    monkeypatch.setattr(router, "manager", mock_manager)

    response = client.get(
        "/quality/dukascopy/EURUSD/M1",
        headers={"X-API-Key": "test-key"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total_rows"] == 1000
    assert data["gap_count"] == 2
    mock_manager.check_quality.assert_called_once_with("dukascopy", "EURUSD", "M1")


def test_quality_endpoint_returns_404_when_not_found(client, monkeypatch):
    mock_manager = MagicMock()
    mock_manager.check_quality.side_effect = FileNotFoundError("not found")
    monkeypatch.setattr(router, "manager", mock_manager)

    response = client.get(
        "/quality/dukascopy/UNKNOWN/M1",
        headers={"X-API-Key": "test-key"},
    )

    assert response.status_code == 404
