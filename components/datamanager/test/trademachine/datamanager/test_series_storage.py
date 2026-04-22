from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
from trademachine.datamanager.db.series_storage import SeriesStorageManager


def _series_df() -> pd.DataFrame:
    return pd.DataFrame(
        {"Value": [3.1, 3.2, 3.4]},
        index=pd.date_range("2024-01-01", periods=3, freq="MS", tz=UTC),
    )


def test_save_load_and_info_series(db_session):
    storage = SeriesStorageManager()

    rows = storage.save_series_data(
        _series_df(),
        "fred",
        "CPIAUCSL",
        metadata={
            "title": "Consumer Price Index",
            "frequency": "Monthly",
            "units": "Index 1982-1984=100",
        },
    )
    loaded = storage.load_series_data("fred", "cpiaucsl")
    info = storage.get_series_info("fred", "CPIAUCSL")

    assert rows == 3
    assert loaded["Value"].tolist() == [3.1, 3.2, 3.4]
    assert info["series_id"] == "CPIAUCSL"
    assert info["title"] == "Consumer Price Index"
    assert info["native_frequency"] == "Monthly"
    assert info["rows"] == 3


def test_list_and_delete_series(db_session):
    storage = SeriesStorageManager()
    storage.save_series_data(
        _series_df(),
        "fred",
        "DFF",
        metadata={"title": "Federal Funds Effective Rate"},
    )

    items = storage.list_series()
    deleted = storage.delete_series("fred", "dff")

    assert len(items) == 1
    assert items[0]["series_id"] == "DFF"
    assert items[0]["title"] == "Federal Funds Effective Rate"
    assert deleted is True
    assert storage.list_series() == []


def test_save_series_metadata_serializes_dates(db_session):
    storage = SeriesStorageManager()
    rows = storage.save_series_data(
        _series_df(),
        "fred",
        "DFF",
        metadata={
            "title": "Federal Funds Effective Rate",
            "frequency": "Daily, 7-Day",
            "released_at": datetime(2024, 1, 2, tzinfo=UTC),
            "observed_on": date(2024, 1, 2),
            "nested": {"as_of": date(2024, 1, 3)},
            "series_id": "DFF",
        },
    )

    info = storage.get_series_info("fred", "DFF")

    assert rows == 3
    assert info["metadata"]["released_at"] == "2024-01-02T00:00:00+00:00"
    assert info["metadata"]["observed_on"] == "2024-01-02"
    assert info["metadata"]["nested"]["as_of"] == "2024-01-03"
