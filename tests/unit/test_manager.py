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


def test_download_data_chunking(manager, mock_fetcher):
    """If range is > 1 year, multiple chunks must be requested."""
    # From 2020 to 2023 -> 3 chunks
    manager.download_data("MOCK", "CHUNKY", datetime(2020, 1, 1), datetime(2023, 1, 1))
    assert mock_fetcher.fetch_data.call_count >= 3


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


# ---------------------------------------------------------------------------
# Global and Search methods
# ---------------------------------------------------------------------------


def test_update_all_databases_orchestration(manager, mock_fetcher, sample_m1_df):
    """Verifies that update_all_databases calls update_data for M1 and resample for others."""
    # Setup: one M1 and one H1 database
    manager.storage.save_data(sample_m1_df, "MOCK", "A1", "M1")
    manager.storage.save_data(sample_m1_df, "MOCK", "A2", "H1")

    with (
        patch.object(manager, "update_data") as mock_update,
        patch.object(manager, "resample_database") as mock_resample,
    ):
        manager.update_all_databases()
        # Should update the M1 one (storage lowers the source name)
        mock_update.assert_any_call("mock", "A1", "M1")
        # Should resample the H1 one
        mock_resample.assert_any_call("mock", "A2", "H1")


def test_show_search_summary(manager, mock_fetcher):
    """Simple smoke test for search summary log."""
    mock_fetcher.search.return_value = pd.DataFrame({"ticker": ["A", "B"]})
    manager.show_search_summary()  # Should not raise


def test_search_assets_success(manager, mock_fetcher):
    """Verifies search_assets calls fetcher.search and prints results."""
    mock_fetcher.search.return_value = pd.DataFrame({"symbol": ["AAPL"], "name": ["Apple Inc"], "exchange": ["NASDAQ"]})
    # Testing search for OPENBB source (which our mock_fetcher is mapped to in manager fixture)
    with patch("builtins.print") as mock_print:
        manager.search_assets(source="MOCK", query="AAPL")
        mock_fetcher.search.assert_called_with(query="AAPL", exchange=None)
        mock_print.assert_any_call("Found 1 results. Displaying the first 20:")
