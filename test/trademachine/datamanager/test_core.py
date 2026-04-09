"""Unit tests for DataManager core orchestrator (DataManager class)."""

from unittest.mock import MagicMock

import pytest
from trademachine.datamanager.services.manager import DataManager


class TestDataManager:
    """Tests for DataManager — the main orchestrator."""

    @pytest.fixture
    def manager(self) -> DataManager:
        """DataManager with mocked storage, processor, and fetchers."""
        mgr = DataManager.__new__(DataManager)
        mgr.storage = MagicMock()
        mgr.processor = MagicMock()
        mgr._fetchers = {}
        return mgr

    def test_get_fetcher_valid(self, manager: DataManager):
        """_get_fetcher should return the correct fetcher for a valid source."""
        mock_fetcher = MagicMock()
        mock_fetcher.source_name = "BINANCE"
        manager._fetchers = {"BINANCE": mock_fetcher}
        fetcher = manager._get_fetcher("binance")
        assert fetcher.source_name == "BINANCE"

    def test_get_fetcher_invalid(self, manager: DataManager):
        """_get_fetcher should raise ValueError for an unsupported source."""
        with pytest.raises(ValueError, match="not supported"):
            manager._get_fetcher("nonexistent")

    def test_delete_database_calls_storage(self, manager: DataManager):
        """delete_database should delegate to storage.delete_database."""
        manager.storage.delete_database.return_value = True
        manager.delete_database("binance", "BTCUSD", "D1")
        manager.storage.delete_database.assert_called_once_with(
            "binance", "BTCUSD", "D1"
        )

    def test_delete_all_databases_calls_storage(self, manager: DataManager):
        """delete_all_databases should delegate to storage.delete_all."""
        manager.storage.delete_all.return_value = True
        manager.delete_all_databases()
        manager.storage.delete_all.assert_called_once()

    def test_info_returns_storage_info(self, manager: DataManager):
        """info should return storage.get_database_info result."""
        expected = {
            "source": "binance",
            "asset": "BTCUSD",
            "timeframe": "D1",
            "rows": 100,
        }
        manager.storage.get_database_info.return_value = expected
        result = manager.info("binance", "BTCUSD", "D1")
        assert result == expected
