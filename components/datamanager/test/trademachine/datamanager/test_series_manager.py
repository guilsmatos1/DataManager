from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pandas as pd
import pytest
from trademachine.datamanager.services.series_manager import SeriesManager


@pytest.fixture
def series_manager() -> SeriesManager:
    storage = MagicMock()
    fetcher = MagicMock()
    return SeriesManager(storage=storage, fetcher=fetcher)


def test_download_series_parses_inputs_and_persists(series_manager: SeriesManager):
    df = pd.DataFrame(
        {"Value": [1.0, 2.0]},
        index=pd.date_range("2024-01-01", periods=2, freq="D"),
    )
    series_manager.fetcher.fetch_metadata.return_value = {"title": "Inflation"}
    series_manager.fetcher.fetch_data.return_value = df
    series_manager.storage.save_series_data.return_value = 2

    result = series_manager.download_series(
        "fred",
        "CPIAUCSL",
        "2024-01-01",
        "2024-01-31",
        frequency="m",
    )

    fetch_args = series_manager.fetcher.fetch_data.call_args
    assert fetch_args.args[0] == "CPIAUCSL"
    assert fetch_args.args[1] == datetime(2024, 1, 1, tzinfo=UTC)
    assert fetch_args.args[2] == datetime(2024, 1, 31, tzinfo=UTC)
    assert fetch_args.kwargs["frequency"] == "m"
    series_manager.storage.save_series_data.assert_called_once_with(
        df,
        "fred",
        "CPIAUCSL",
        metadata={"title": "Inflation"},
        update_stats=True,
    )
    assert result == {"status": "ok", "series_id": "CPIAUCSL", "rows": 2}


def test_update_series_uses_overlap_window(series_manager: SeriesManager):
    series_manager.storage.get_series_info.return_value = {
        "status": "ok",
        "source": "fred",
        "series_id": "CPIAUCSL",
        "observation_end": "2024-03-31T00:00:00+00:00",
    }
    series_manager.fetcher.fetch_metadata.return_value = {"title": "Inflation"}
    series_manager.fetcher.fetch_data.return_value = pd.DataFrame(
        {"Value": [1.0]},
        index=pd.date_range("2024-03-01", periods=1, freq="D"),
    )
    series_manager.storage.save_series_data.return_value = 1

    series_manager.update_series("fred", "CPIAUCSL", lookback_period="30D")

    fetch_args = series_manager.fetcher.fetch_data.call_args
    assert fetch_args.args[1] == datetime(2024, 3, 1, tzinfo=UTC)
    assert fetch_args.kwargs["frequency"] is None


def test_info_series_maps_storage_payload(series_manager: SeriesManager):
    series_manager.storage.get_series_info.return_value = {
        "status": "ok",
        "source": "fred",
        "series_id": "CPIAUCSL",
        "title": "Inflation",
        "native_frequency": "Monthly",
        "last_fetched_at": "2026-04-02T10:00:00+00:00",
        "rows": 12,
        "metadata": {"units": "Index"},
    }

    result = series_manager.info_series("fred", "CPIAUCSL")

    assert result["frequency"] == "Monthly"
    assert result["last_updated"] == "2026-04-02T10:00:00+00:00"
    assert result["metadata"] == {"units": "Index"}


def test_invalid_source_is_rejected(series_manager: SeriesManager):
    with pytest.raises(ValueError, match="Only the FRED source"):
        series_manager.search_series(source="openbb", query="inflation")
