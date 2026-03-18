import pandas as pd
import pytest

from datamanager.db.storage import StorageManager


@pytest.fixture
def temp_storage(tmp_path):
    """Provides a StorageManager pointing to a temporary directory."""
    storage = StorageManager(base_dir=tmp_path / "database")
    # Redirect catalog to temp path as well
    storage.catalog_path = tmp_path / "metadata" / "catalog.json"
    storage.catalog_path.parent.mkdir(parents=True, exist_ok=True)
    return storage


@pytest.fixture
def sample_df():
    """Simple OHLC DataFrame."""
    dates = pd.date_range("2023-01-01", periods=10, freq="1min")
    return pd.DataFrame(
        {"Open": [100.0] * 10, "High": [105.0] * 10, "Low": [95.0] * 10, "Close": [102.0] * 10}, index=dates
    )


def test_save_and_load_data(temp_storage, sample_df):
    """Tests if data is saved and loaded correctly (Atomic Swap)."""
    temp_storage.save_data(sample_df, "TEST_SOURCE", "TEST_ASSET", "M1")

    loaded_df = temp_storage.load_data("TEST_SOURCE", "TEST_ASSET", "M1")
    assert len(loaded_df) == 10
    assert list(loaded_df.columns) == ["Open", "High", "Low", "Close"]
    assert loaded_df.index[0] == pd.Timestamp("2023-01-01 00:00:00")


def test_append_data(temp_storage, sample_df):
    """Tests if new data is appended correctly without duplicates."""
    temp_storage.save_data(sample_df, "TEST_SOURCE", "TEST_ASSET", "M1")

    # New data with some overlap
    new_dates = pd.date_range("2023-01-01 00:05:00", periods=10, freq="1min")
    new_df = pd.DataFrame(
        {"Open": [200.0] * 10, "High": [205.0] * 10, "Low": [195.0] * 10, "Close": [202.0] * 10}, index=new_dates
    )

    temp_storage.append_data(new_df, "TEST_SOURCE", "TEST_ASSET", "M1")

    combined_df = temp_storage.load_data("TEST_SOURCE", "TEST_ASSET", "M1")
    # 10 initial + 5 new unique rows = 15
    assert len(combined_df) == 15
    # Overlapping row (00:05:00) should have new data (keep='last' in append_data)
    assert combined_df.loc["2023-01-01 00:05:00", "Open"] == 200.0


def test_delete_database(temp_storage, sample_df):
    """Tests if specific timeframe or whole asset is deleted."""
    temp_storage.save_data(sample_df, "TEST_SOURCE", "TEST_ASSET", "M1")
    temp_storage.save_data(sample_df, "TEST_SOURCE", "TEST_ASSET", "H1")

    # Delete only M1
    temp_storage.delete_database("TEST_SOURCE", "TEST_ASSET", "M1")
    with pytest.raises(FileNotFoundError):
        temp_storage.load_data("TEST_SOURCE", "TEST_ASSET", "M1")

    # H1 should still exist
    assert temp_storage.load_data("TEST_SOURCE", "TEST_ASSET", "H1") is not None

    # Delete whole asset
    temp_storage.delete_database("TEST_SOURCE", "TEST_ASSET")
    with pytest.raises(FileNotFoundError):
        temp_storage.load_data("TEST_SOURCE", "TEST_ASSET", "H1")


def test_catalog_updates(temp_storage, sample_df):
    """Tests if catalog.json is updated when data is saved/deleted."""
    temp_storage.save_data(sample_df, "TEST_SOURCE", "TEST_ASSET", "M1")
    catalog = temp_storage.list_databases()
    assert len(catalog) == 1
    assert catalog[0]["asset"] == "TEST_ASSET"

    temp_storage.delete_database("TEST_SOURCE", "TEST_ASSET", "M1")
    catalog = temp_storage.list_databases()
    assert len(catalog) == 0


def test_atomic_swap_integrity(temp_storage, sample_df, monkeypatch):
    """Simulates a crash during save to check if original file is safe."""
    temp_storage.save_data(sample_df, "TEST_SOURCE", "TEST_ASSET", "M1")
    original_data = temp_storage.load_data("TEST_SOURCE", "TEST_ASSET", "M1")

    def mock_to_parquet(*args, **kwargs):
        raise IOError("Simulated Crash during write")

    # Inject failure into pandas.DataFrame.to_parquet
    monkeypatch.setattr(pd.DataFrame, "to_parquet", mock_to_parquet)

    with pytest.raises(IOError, match="Simulated Crash"):
        temp_storage.save_data(sample_df, "TEST_SOURCE", "TEST_ASSET", "M1")

    # Original data should remain unchanged and healthy
    healthy_data = temp_storage.load_data("TEST_SOURCE", "TEST_ASSET", "M1")
    pd.testing.assert_frame_equal(original_data, healthy_data)

    # Temp file should have been cleaned up
    file_path = temp_storage._get_path("TEST_SOURCE", "TEST_ASSET", "M1")
    temp_path = file_path.with_suffix(".tmp.parquet")
    assert not temp_path.exists()
