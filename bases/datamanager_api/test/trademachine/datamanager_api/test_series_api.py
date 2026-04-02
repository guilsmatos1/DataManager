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

    payload = pd.read_parquet(BytesIO(response.content), engine="fastparquet")

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
