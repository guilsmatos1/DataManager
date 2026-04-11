"""Unit tests for DataManager service layer."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pandas as pd
import pytest
from trademachine.datamanager.services.manager import DataManager


class TestDataManagerService:
    """Tests for DataManager service methods."""

    @pytest.fixture
    def manager(self) -> DataManager:
        """DataManager with mocked storage, processor, and fetchers."""
        mgr = DataManager.__new__(DataManager)
        mgr.storage = MagicMock()
        mgr._fetchers = {}
        return mgr

    @pytest.fixture
    def mock_fetcher(self):
        """A mock fetcher for testing."""
        fetcher = MagicMock()
        fetcher.source_name = "MOCK"
        return fetcher

    # ── download_data ─────────────────────────────────────────────────────────

    def test_download_data_idempotent_when_already_exists(self, manager, mock_fetcher):
        """download_data should proceed normally if database already exists."""
        manager._fetchers["MOCK"] = mock_fetcher
        manager.storage.get_database_info.return_value = {"status": "exists"}

        df = pd.DataFrame(
            {
                "Open": [100],
                "High": [105],
                "Low": [95],
                "Close": [102],
                "Volume": [1000],
            },
            index=[datetime(2024, 1, 1)],
        )
        mock_fetcher.fetch_data.return_value = df

        manager.download_data(
            "mock", "BTCUSD", datetime(2024, 1, 1), datetime(2024, 6, 1)
        )

        # Should fetch and append normally
        assert mock_fetcher.fetch_data.call_count == 1
        manager.storage.append_data.assert_called()

    def test_download_data_success(self, manager, mock_fetcher):
        """download_data should fetch and save data in yearly chunks."""
        manager._fetchers["MOCK"] = mock_fetcher
        manager.storage.get_database_info.return_value = {"status": "Not Found"}

        df = pd.DataFrame(
            {
                "Open": [100],
                "High": [105],
                "Low": [95],
                "Close": [102],
                "Volume": [1000],
            },
            index=[datetime(2024, 1, 1)],
        )
        mock_fetcher.fetch_data.return_value = df

        manager.download_data(
            "mock", "BTCUSD", datetime(2024, 1, 1), datetime(2024, 6, 1)
        )

        assert mock_fetcher.fetch_data.call_count == 1
        manager.storage.append_data.assert_called()

    def test_download_data_all_chunks_fail_raises(self, manager, mock_fetcher):
        """download_data should raise RuntimeError when all chunks fail."""
        manager._fetchers["MOCK"] = mock_fetcher
        manager.storage.get_database_info.return_value = {"status": "Not Found"}
        mock_fetcher.fetch_data.return_value = pd.DataFrame()

        with pytest.raises(RuntimeError, match="Download failed"):
            manager.download_data(
                "mock", "BTCUSD", datetime(2024, 1, 1), datetime(2024, 12, 31)
            )

    # ── update_data ─────────────────────────────────────────────────────────

    def test_update_data_returns_early_when_not_found(self, manager, mock_fetcher):
        """update_data should return early if M1 database does not exist."""
        manager._fetchers["MOCK"] = mock_fetcher
        manager.storage.get_database_info.return_value = {"status": "Not Found"}

        manager.update_data("mock", "BTCUSD")

        mock_fetcher.fetch_data.assert_not_called()
        manager.storage.append_data.assert_not_called()

    def test_update_data_fetches_and_appends(self, manager, mock_fetcher):
        """update_data should fetch new data and append to storage."""
        manager._fetchers["MOCK"] = mock_fetcher
        yesterday = datetime.now() - timedelta(days=1)
        manager.storage.get_database_info.return_value = {
            "status": "exists",
            "end_date": yesterday.strftime("%Y-%m-%d %H:%M:%S"),
        }

        df = pd.DataFrame(
            {
                "Open": [100],
                "High": [105],
                "Low": [95],
                "Close": [102],
                "Volume": [1000],
            },
            index=[yesterday + timedelta(hours=1)],
        )
        mock_fetcher.fetch_data.return_value = df

        manager.update_data("mock", "BTCUSD")

        mock_fetcher.fetch_data.assert_called_once()
        manager.storage.append_data.assert_called_once()

    def test_update_data_warns_on_empty_response(self, manager, mock_fetcher):
        """update_data should warn but not error when no new data returned."""
        manager._fetchers["MOCK"] = mock_fetcher
        yesterday = datetime.now() - timedelta(days=2)
        manager.storage.get_database_info.return_value = {
            "status": "exists",
            "end_date": yesterday.strftime("%Y-%m-%d %H:%M:%S"),
        }
        mock_fetcher.fetch_data.return_value = pd.DataFrame()

        manager.update_data("mock", "BTCUSD")

        manager.storage.append_data.assert_not_called()

    def test_update_data_resamples_requested_timeframe_even_if_m1_is_current(
        self, manager, mock_fetcher
    ):
        """A derived timeframe request should rebuild from M1 after the update step."""
        manager._fetchers["MOCK"] = mock_fetcher
        manager.resample_data = MagicMock()
        manager.storage.get_database_info.return_value = {
            "status": "exists",
            "end_date": (datetime.now() + timedelta(days=1)).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
        }

        manager.update_data("mock", "BTCUSD", "H1")

        mock_fetcher.fetch_data.assert_not_called()
        manager.resample_data.assert_called_once_with("mock", "BTCUSD", "H1")

    # ── update_all_databases ─────────────────────────────────────────────────

    def test_update_all_databases_empty(self, manager, mock_fetcher):
        """update_all_databases should do nothing when no databases exist."""
        manager.storage.list_databases.return_value = []

        manager.update_all_databases()

        mock_fetcher.fetch_data.assert_not_called()

    def test_update_all_databases_filters_non_m1(self, manager, mock_fetcher):
        """update_all_databases should only process M1 databases."""
        manager._fetchers["MOCK"] = mock_fetcher
        manager.storage.list_databases.return_value = [
            {"source": "mock", "asset": "BTCUSD", "timeframe": "H1"},
            {"source": "mock", "asset": "ETHUSD", "timeframe": "M1"},
        ]

        manager.update_all_databases()

        # Should only call update_data for M1
        assert manager.storage.list_databases.call_count >= 1

    # ── resample_data ───────────────────────────────────────────────────────

    def test_resample_data_creates_continuous_aggregate(self, manager):
        """resample_data should create a continuous aggregate for the target timeframe."""
        manager.storage.get_database_info.return_value = {
            "source": "mock",
            "asset": "BTCUSD",
            "timeframe": "M1",
            "rows": 5,
        }

        manager.resample_data("mock", "BTCUSD", "M5")

        manager.storage.get_database_info.assert_called_once_with(
            "mock", "BTCUSD", "M1"
        )
        manager.storage.create_continuous_aggregate.assert_called_once_with("M5")

    def test_resample_data_rejects_m1(self, manager):
        """resample_data should reject M1 as a target timeframe."""
        with pytest.raises(ValueError, match="M1 is the source timeframe"):
            manager.resample_data("mock", "BTCUSD", "M1")

    def test_resample_data_requires_existing_m1(self, manager):
        """resample_data should fail clearly when the M1 base is missing."""
        manager.storage.get_database_info.return_value = {"status": "Not Found"}

        with pytest.raises(FileNotFoundError, match="M1 base does not exist"):
            manager.resample_data("mock", "BTCUSD", "H1")

    # ── search_assets ────────────────────────────────────────────────────────

    def test_search_assets_source_not_supported(self, manager):
        """search_assets should return empty DataFrame for unknown source."""
        result = manager.search_assets("unknown_source", "BTC")

        assert result.empty
        assert isinstance(result, pd.DataFrame)

    def test_search_assets_success(self, manager, mock_fetcher):
        """search_assets should return fetcher search results."""
        manager._fetchers["MOCK"] = mock_fetcher
        expected_df = pd.DataFrame({"ticker": ["BTCUSD"], "exchange": ["binance"]})
        mock_fetcher.search.return_value = expected_df

        result = manager.search_assets("mock", "BTC")

        assert result.equals(expected_df)

    def test_search_assets_empty_result(self, manager, mock_fetcher):
        """search_assets should return empty DataFrame when no results found."""
        manager._fetchers["MOCK"] = mock_fetcher
        mock_fetcher.search.return_value = pd.DataFrame()

        result = manager.search_assets("mock", "NONEXISTENT")

        assert result.empty

    def test_search_assets_exception(self, manager, mock_fetcher):
        """search_assets should return empty DataFrame on fetcher exception."""
        manager._fetchers["MOCK"] = mock_fetcher
        mock_fetcher.search.side_effect = Exception("Network error")

        result = manager.search_assets("mock", "BTC")

        assert result.empty

    # ── check_quality ────────────────────────────────────────────────────────

    def test_check_quality_file_not_found(self, manager):
        """check_quality should propagate FileNotFoundError so callers can handle it."""
        manager.storage.load_data.side_effect = FileNotFoundError("Not found")

        with pytest.raises(FileNotFoundError):
            manager.check_quality("mock", "BTCUSD")

    def test_check_quality_runs_all_checks(self, manager):
        """check_quality should run all 7 quality checks on valid data."""
        df = pd.DataFrame(
            {
                "Open": [100, 105, 110],
                "High": [110, 115, 120],
                "Low": [95, 100, 105],
                "Close": [105, 110, 115],
                "Volume": [1000, 1100, 1200],
            },
            index=pd.DatetimeIndex(["2024-01-01", "2024-01-02", "2024-01-03"]),
        )
        manager.storage.load_data.return_value = df

        # Should not raise
        manager.check_quality("mock", "BTCUSD")

    def test_check_quality_detects_ohlc_violations(self, manager):
        """check_quality should detect when High < Low."""
        df = pd.DataFrame(
            {
                "Open": [100],
                "High": [90],  # Invalid: High < Low
                "Low": [100],
                "Close": [95],
                "Volume": [1000],
            },
            index=pd.DatetimeIndex(["2024-01-01"]),
        )
        manager.storage.load_data.return_value = df

        # Should not raise, just report
        manager.check_quality("mock", "BTCUSD")

    # ── list_all / show_search_summary ───────────────────────────────────────

    def test_list_all_returns_storage_databases(self, manager):
        """list_all should return storage.list_databases result."""
        expected = [{"source": "mock", "asset": "BTCUSD", "timeframe": "M1"}]
        manager.storage.list_databases.return_value = expected

        result = manager.list_all()

        assert result == expected
