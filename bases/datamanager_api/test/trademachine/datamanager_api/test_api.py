from __future__ import annotations

from unittest.mock import MagicMock

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


def test_download_endpoint_runs_background_task(client, monkeypatch):
    manager = MagicMock()
    monkeypatch.setattr(router, "manager", manager)

    response = client.post(
        "/download",
        json={
            "source": "dukascopy",
            "asset": "EURUSD",
            "start_date": "2024-01-01T00:00:00",
            "end_date": "2024-01-31T00:00:00",
        },
        headers={"X-API-Key": "test-key"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert "idempotent" in response.json()["message"]
    manager.download_data.assert_called_once()


def test_download_endpoint_allows_existing_database(client, monkeypatch):
    manager = MagicMock()
    manager.storage.get_database_info.return_value = {"status": "exists"}
    monkeypatch.setattr(router, "manager", manager)

    response = client.post(
        "/download",
        json={
            "source": "dukascopy",
            "asset": "EURUSD",
            "start_date": "2024-01-01T00:00:00",
            "end_date": "2024-01-31T00:00:00",
        },
        headers={"X-API-Key": "test-key"},
    )

    assert response.status_code == 200
    manager.download_data.assert_called_once()
