from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from datamanager.db.storage import StorageManager
from datamanager.services.manager import DataManager


@pytest.fixture
def sample_m1_df():
    """60 rows of M1 OHLCV data."""
    dates = pd.date_range("2023-01-02 00:00", periods=60, freq="1min")
    return pd.DataFrame(
        {
            "Open": [100.0] * 60,
            "High": [105.0] * 60,
            "Low": [95.0] * 60,
            "Close": [102.0] * 60,
            "Volume": [1000.0] * 60,
        },
        index=dates,
    )


@pytest.fixture
def mock_fetcher(sample_m1_df):
    """A fake fetcher that always returns sample_m1_df."""
    fetcher = MagicMock()
    fetcher.source_name = "MOCK"
    fetcher.fetch_data.return_value = sample_m1_df
    return fetcher


@pytest.fixture
def manager(tmp_path, mock_fetcher):
    """DataManager with mocked fetchers and isolated storage."""
    with patch("datamanager.fetchers.get_all_fetchers", return_value=[]):
        dm = DataManager()

    # Redirect storage to tmp_path
    dm.storage = StorageManager(base_dir=tmp_path / "database")
    dm.storage.catalog_path = tmp_path / "metadata" / "catalog.json"
    dm.storage.catalog_path.parent.mkdir(parents=True, exist_ok=True)

    dm._fetchers = {"MOCK": mock_fetcher}
    return dm


# ---------------------------------------------------------------------------
# download_data
# ---------------------------------------------------------------------------


def test_download_data_success(manager, mock_fetcher):
    manager.download_data("MOCK", "ASSET", datetime(2023, 1, 1), datetime(2023, 1, 3))
    mock_fetcher.fetch_data.assert_called()
    info = manager.storage.get_database_info("MOCK", "ASSET", "M1")
    assert info.get("status") != "Not Found"
    assert info["rows"] > 0


def test_download_data_already_exists_raises(manager, sample_m1_df):
    manager.storage.save_data(sample_m1_df, "MOCK", "ASSET", "M1")
    with pytest.raises(Exception, match="already exists"):
        manager.download_data("MOCK", "ASSET", datetime(2023, 1, 1), datetime(2023, 1, 3))


def test_download_data_passes_asset_to_fetcher(manager, mock_fetcher):
    """Regression: asset argument must be forwarded to fetch_data."""
    manager.download_data("MOCK", "EURUSD", datetime(2023, 1, 2), datetime(2023, 1, 3))
    args, _ = mock_fetcher.fetch_data.call_args
    assert args[0] == "EURUSD"


# ---------------------------------------------------------------------------
# update_data
# ---------------------------------------------------------------------------


def test_update_data_success(manager, mock_fetcher, sample_m1_df):
    manager.storage.save_data(sample_m1_df, "MOCK", "ASSET", "M1")
    manager.update_data("MOCK", "ASSET", "M1")
    mock_fetcher.fetch_data.assert_called()


def test_update_data_not_found_returns_without_raising(manager):
    # Should log and return, not raise
    manager.update_data("MOCK", "NONEXISTENT", "M1")


def test_update_data_already_up_to_date(manager, mock_fetcher):
    """If end_date is within the last hour, skip the fetch."""
    dates = pd.date_range(datetime.now().strftime("%Y-%m-%d %H:%M"), periods=5, freq="1min")
    fresh_df = pd.DataFrame(
        {"Open": [1.0] * 5, "High": [1.0] * 5, "Low": [1.0] * 5, "Close": [1.0] * 5, "Volume": [1.0] * 5},
        index=dates,
    )
    manager.storage.save_data(fresh_df, "MOCK", "ASSET", "M1")
    manager.update_data("MOCK", "ASSET", "M1")
    mock_fetcher.fetch_data.assert_not_called()


# ---------------------------------------------------------------------------
# resample_database
# ---------------------------------------------------------------------------


def test_resample_database_success(manager, sample_m1_df):
    manager.storage.save_data(sample_m1_df, "MOCK", "ASSET", "M1")
    manager.resample_database("MOCK", "ASSET", "H1")
    df_h1 = manager.storage.load_data("MOCK", "ASSET", "H1")
    assert len(df_h1) == 1


def test_resample_database_no_m1_returns_without_raising(manager):
    manager.resample_database("MOCK", "MISSING", "H1")


# ---------------------------------------------------------------------------
# check_quality
# ---------------------------------------------------------------------------


def test_check_quality_clean_data(manager, sample_m1_df):
    manager.storage.save_data(sample_m1_df, "MOCK", "ASSET", "M1")
    manager.check_quality("MOCK", "ASSET", "M1")  # Should not raise


def test_check_quality_not_found_returns_without_raising(manager):
    manager.check_quality("MOCK", "MISSING", "M1")


# ---------------------------------------------------------------------------
# delete_database
# ---------------------------------------------------------------------------


def test_delete_specific_timeframe(manager, sample_m1_df):
    manager.storage.save_data(sample_m1_df, "MOCK", "ASSET", "M1")
    manager.storage.save_data(sample_m1_df, "MOCK", "ASSET", "H1")

    manager.delete_database("MOCK", "ASSET", "M1")

    with pytest.raises(FileNotFoundError):
        manager.storage.load_data("MOCK", "ASSET", "M1")
    assert manager.storage.load_data("MOCK", "ASSET", "H1") is not None


def test_delete_all_timeframes(manager, sample_m1_df):
    manager.storage.save_data(sample_m1_df, "MOCK", "ASSET", "M1")
    manager.storage.save_data(sample_m1_df, "MOCK", "ASSET", "H1")

    manager.delete_database("MOCK", "ASSET")

    with pytest.raises(FileNotFoundError):
        manager.storage.load_data("MOCK", "ASSET", "M1")
    with pytest.raises(FileNotFoundError):
        manager.storage.load_data("MOCK", "ASSET", "H1")
