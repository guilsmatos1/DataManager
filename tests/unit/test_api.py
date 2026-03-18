"""Tests for the FastAPI REST endpoints (TestClient, no real network)."""

from unittest.mock import MagicMock

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from datamanager.api.router import app
from datamanager.db.storage import StorageManager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_df():
    dates = pd.date_range("2023-01-02", periods=60, freq="1min")
    return pd.DataFrame(
        {"Open": [1.0] * 60, "High": [2.0] * 60, "Low": [0.5] * 60, "Close": [1.5] * 60, "Volume": [100.0] * 60},
        index=dates,
    )


@pytest.fixture
def client(tmp_path, sample_df):
    """TestClient with isolated storage and a known API key."""
    from datamanager.api import router as router_module
    from datamanager.core.config import settings

    # Point storage to tmp_path
    storage = StorageManager(base_dir=tmp_path / "database")
    storage.catalog_path = tmp_path / "metadata" / "catalog.json"
    storage.catalog_path.parent.mkdir(parents=True, exist_ok=True)

    router_module.manager.storage = storage
    router_module.manager._fetchers = {}

    # Use a test API key
    settings.api_key = "test-key"

    # Reset rate-limit store between tests
    router_module._rate_store.clear()

    with TestClient(app) as c:
        yield c


HEADERS = {"X-API-Key": "test-key"}


# ---------------------------------------------------------------------------
# Dashboard & health (no auth required)
# ---------------------------------------------------------------------------


def test_dashboard_no_auth(client):
    r = client.get("/")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "timestamp" in data


def test_health_no_auth(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "databases_count" in data


# ---------------------------------------------------------------------------
# /list
# ---------------------------------------------------------------------------


def test_list_empty(client):
    r = client.get("/list", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["databases"] == []
    assert body["total"] == 0


def test_list_pagination(client, tmp_path, sample_df):
    from datamanager.api import router as router_module

    # Seed 3 entries
    for asset in ["AAA", "BBB", "CCC"]:
        router_module.manager.storage.save_data(sample_df, "test", asset, "M1")

    r = client.get("/list?skip=0&limit=2", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert len(body["databases"]) == 2

    r2 = client.get("/list?skip=2&limit=2", headers=HEADERS)
    assert len(r2.json()["databases"]) == 1


def test_list_requires_auth(client):
    r = client.get("/list")
    # FastAPI returns 403 (missing header) or 401 depending on version
    assert r.status_code in (401, 403)


# ---------------------------------------------------------------------------
# /download
# ---------------------------------------------------------------------------


def test_download_triggers_background_task(client):
    mock_fetcher = MagicMock()
    mock_fetcher.source_name = "MOCK"

    from datamanager.api import router as router_module

    router_module.manager._fetchers = {"MOCK": mock_fetcher}

    r = client.post(
        "/download",
        json={"source": "MOCK", "asset": "EURUSD", "start_date": "2023-01-02", "end_date": "2023-01-03"},
        headers=HEADERS,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "success"


def test_download_conflict_if_exists(client, sample_df):
    from datamanager.api import router as router_module

    router_module.manager.storage.save_data(sample_df, "mock", "EURUSD", "M1")

    r = client.post(
        "/download",
        json={"source": "mock", "asset": "EURUSD", "start_date": "2023-01-02", "end_date": "2023-01-03"},
        headers=HEADERS,
    )
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# /info
# ---------------------------------------------------------------------------


def test_info_not_found(client):
    r = client.get("/info/test/MISSING/M1", headers=HEADERS)
    assert r.status_code == 404


def test_info_returns_metadata(client, sample_df):
    from datamanager.api import router as router_module

    router_module.manager.storage.save_data(sample_df, "test", "AAPL", "M1")

    r = client.get("/info/test/AAPL/M1", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert data["asset"] == "AAPL"
    assert data["rows"] == 60


# ---------------------------------------------------------------------------
# /delete
# ---------------------------------------------------------------------------


def test_delete_existing(client, sample_df):
    from datamanager.api import router as router_module

    router_module.manager.storage.save_data(sample_df, "test", "AAPL", "M1")

    r = client.post("/delete", json={"source": "test", "asset": "AAPL", "timeframe": "M1"}, headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["status"] == "success"


def test_update_triggers_background_task(client):
    r = client.post("/update", json={"source": "test", "asset": "AAPL", "timeframe": "M1"}, headers=HEADERS)
    assert r.status_code == 200
    assert "started in background" in r.json()["message"]


def test_resample_triggers_background_task(client):
    r = client.post("/resample", json={"source": "test", "asset": "AAPL", "target_timeframe": "H1"}, headers=HEADERS)
    assert r.status_code == 200
    assert "Resample" in r.json()["message"]


# ---------------------------------------------------------------------------
# Scheduler endpoints
# ---------------------------------------------------------------------------


def test_schedule_job(client):
    r = client.post(
        "/schedule",
        json={"source": "test", "asset": "AAPL", "timeframe": "M1", "interval_minutes": 60},
        headers=HEADERS,
    )
    assert r.status_code == 200
    data = r.json()
    assert "job_id" in data
    assert data["asset"] == "AAPL"


def test_list_scheduled_jobs(client):
    client.post(
        "/schedule",
        json={"source": "test", "asset": "AAPL", "timeframe": "M1", "interval_minutes": 60},
        headers=HEADERS,
    )
    r = client.get("/schedule", headers=HEADERS)
    assert r.status_code == 200
    assert len(r.json()["jobs"]) >= 1


def test_remove_scheduled_job(client):
    res = client.post(
        "/schedule",
        json={"source": "test", "asset": "AAPL", "timeframe": "M1", "interval_minutes": 60},
        headers=HEADERS,
    )
    job_id = res.json()["job_id"]
    r = client.delete(f"/schedule/{job_id}", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["status"] == "success"


# ---------------------------------------------------------------------------
# /data stream
# ---------------------------------------------------------------------------


def test_stream_not_found(client):
    r = client.get("/data/test/MISSING/M1/stream", headers=HEADERS)
    assert r.status_code == 404


def test_stream_returns_csv(client, sample_df):
    from datamanager.api import router as router_module

    router_module.manager.storage.save_data(sample_df, "test", "STREAM", "M1")

    r = client.get("/data/test/STREAM/M1/stream", headers=HEADERS)
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    lines = r.text.strip().split("\n")
    # header + 60 data rows
    assert len(lines) == 61


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


def test_rate_limit_triggers_after_threshold():
    """Unit test: _check_rate_limit raises 429 when the window is full."""
    import time
    from collections import deque
    from unittest.mock import MagicMock

    from fastapi import HTTPException

    from datamanager.api.router import _RATE_LIMIT, _check_rate_limit, _rate_store

    ip = "rate-test-client"
    now = time.monotonic()
    _rate_store[ip] = deque([now] * _RATE_LIMIT)

    mock_req = MagicMock()
    mock_req.client.host = ip

    with pytest.raises(HTTPException) as exc_info:
        _check_rate_limit(mock_req)

    assert exc_info.value.status_code == 429
    _rate_store.pop(ip, None)
