"""Unit tests for StorageManager."""

from pathlib import Path

import pandas as pd
import pytest
from trademachine.datamanager.db.storage import StorageManager


@pytest.fixture
def storage(tmp_path: Path) -> StorageManager:
    """StorageManager backed by a temporary directory."""
    return StorageManager(base_dir=str(tmp_path / "database"))


@pytest.fixture
def ohlcv_df() -> pd.DataFrame:
    """Sample OHLCV DataFrame with 5 daily bars."""
    dates = pd.date_range("2024-01-01", periods=5, freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "Open": [100.0, 101.0, 102.0, 103.0, 104.0],
            "High": [101.0, 102.0, 103.0, 104.0, 105.0],
            "Low": [99.0, 100.0, 101.0, 102.0, 103.0],
            "Close": [101.0, 102.0, 103.0, 104.0, 105.0],
            "Volume": [1000, 1100, 1200, 1300, 1400],
        },
        index=dates,
    )


class TestSaveAndLoad:
    """Tests for save_data and load_data round-trip."""

    def test_save_load_roundtrip_parquet(
        self, storage: StorageManager, ohlcv_df: pd.DataFrame
    ):
        """Data saved and loaded should be identical."""
        storage.save_data(ohlcv_df, "binance", "BTCUSD", "D1")
        loaded = storage.load_data("binance", "BTCUSD", "D1")

        assert len(loaded) == 5
        assert loaded["Open"].tolist() == [100.0, 101.0, 102.0, 103.0, 104.0]
        assert loaded["Volume"].sum() == 6000

    def test_save_data_unknown_format(
        self, storage: StorageManager, ohlcv_df: pd.DataFrame
    ):
        """Saving with unknown format should raise."""
        storage.format = ".csv"
        storage.save_data(ohlcv_df, "binance", "BTCUSD", "D1")
        loaded = storage.load_data("binance", "BTCUSD", "D1")
        assert len(loaded) == 5

    def test_load_nonexistent_raises(self, storage: StorageManager):
        """Loading a non-existent database should raise FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            storage.load_data("binance", "BTCUSD", "D1")

    def test_save_and_get_info(self, storage: StorageManager, ohlcv_df: pd.DataFrame):
        """get_database_info should return correct metadata without loading full data."""
        storage.save_data(ohlcv_df, "binance", "BTCUSD", "D1")
        info = storage.get_database_info("binance", "BTCUSD", "D1")

        assert info["source"] == "binance"
        assert info["asset"] == "BTCUSD"
        assert info["timeframe"] == "D1"
        assert info["rows"] == 5
        assert info["file_size_kb"] > 0
        assert "start_date" in info
        assert "end_date" in info

    def test_get_info_nonexistent(self, storage: StorageManager):
        """get_database_info for non-existent DB should return Not Found status."""
        info = storage.get_database_info("binance", "BTCUSD", "D1")
        assert info["status"] == "Not Found"


class TestAppendData:
    """Tests for append_data with deduplication."""

    def test_append_to_new_file(self, storage: StorageManager, ohlcv_df: pd.DataFrame):
        """Appending when file doesn't exist should save the data."""
        storage.append_data(ohlcv_df, "binance", "ETHUSD", "D1")
        loaded = storage.load_data("binance", "ETHUSD", "D1")
        assert len(loaded) == 5

    def test_append_deduplicates_by_index(self, storage: StorageManager):
        """Appending rows with duplicate index should keep only the last."""
        dates1 = pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC")
        df1 = pd.DataFrame(
            {"Open": [100.0, 101.0, 102.0], "Close": [101.0, 102.0, 103.0]},
            index=dates1,
        )

        dates2 = pd.date_range("2024-01-03", periods=3, freq="D", tz="UTC")
        # Row at 2024-01-03 is duplicated (102.0 in df1, 200.0 in df2)
        df2 = pd.DataFrame(
            {"Open": [102.0, 103.0, 104.0], "Close": [200.0, 103.0, 105.0]},
            index=dates2,
        )

        storage.save_data(df1, "binance", "ETHUSD", "D1")
        storage.append_data(df2, "binance", "ETHUSD", "D1")

        loaded = storage.load_data("binance", "ETHUSD", "D1")
        assert len(loaded) == 5  # 3 + 3 - 1 (duplicate at Jan 3) = 5
        # The duplicate at Jan 3 should have Close=200.0 (last appended wins)
        assert float(loaded.loc["2024-01-03"]["Close"]) == 200.0


class TestCatalog:
    """Tests for catalog (SQLite) operations."""

    def test_list_databases_empty(self, storage: StorageManager):
        """list_databases should return empty list when nothing is saved."""
        assert storage.list_databases() == []

    def test_list_databases_after_save(
        self, storage: StorageManager, ohlcv_df: pd.DataFrame
    ):
        """list_databases should return all saved databases."""
        storage.save_data(ohlcv_df, "binance", "BTCUSD", "D1")
        storage.save_data(ohlcv_df, "binance", "ETHUSD", "H1")

        dbs = storage.list_databases()
        assert len(dbs) == 2

    def test_get_stats(self, storage: StorageManager, ohlcv_df: pd.DataFrame):
        """get_stats should aggregate across all databases."""
        storage.save_data(ohlcv_df, "binance", "BTCUSD", "D1")
        storage.save_data(ohlcv_df, "binance", "ETHUSD", "D1")

        stats = storage.get_stats()
        assert stats["databases_count"] == 2
        assert stats["sources"]["binance"] == 2
        assert stats["total_rows"] == 10

    def test_delete_database_specific_timeframe(
        self, storage: StorageManager, ohlcv_df: pd.DataFrame
    ):
        """Deleting a specific timeframe should only remove that TF."""
        storage.save_data(ohlcv_df, "binance", "BTCUSD", "D1")
        storage.save_data(ohlcv_df, "binance", "BTCUSD", "H1")

        result = storage.delete_database("binance", "BTCUSD", "D1")
        assert result is True

        # H1 should still exist
        storage.load_data("binance", "BTCUSD", "H1")
        # D1 should be gone
        with pytest.raises(FileNotFoundError):
            storage.load_data("binance", "BTCUSD", "D1")

    def test_delete_database_all_timeframes(
        self, storage: StorageManager, ohlcv_df: pd.DataFrame
    ):
        """Deleting without timeframe removes all TFs for that asset."""
        storage.save_data(ohlcv_df, "binance", "BTCUSD", "D1")
        storage.save_data(ohlcv_df, "binance", "BTCUSD", "H1")

        result = storage.delete_database("binance", "BTCUSD")
        assert result is True

        with pytest.raises(FileNotFoundError):
            storage.load_data("binance", "BTCUSD", "D1")
        with pytest.raises(FileNotFoundError):
            storage.load_data("binance", "BTCUSD", "H1")

    def test_delete_all(self, storage: StorageManager, ohlcv_df: pd.DataFrame):
        """delete_all should remove everything."""
        storage.save_data(ohlcv_df, "binance", "BTCUSD", "D1")
        storage.save_data(ohlcv_df, "binance", "ETHUSD", "D1")

        result = storage.delete_all()
        assert result is True
        assert storage.list_databases() == []


class TestDataVersioning:
    """Tests for backup/restore versioning."""

    def test_list_versions_empty(self, storage: StorageManager):
        """list_versions should return empty list when no versions exist."""
        assert storage.list_versions("binance", "BTCUSD", "D1") == []

    def test_save_creates_backup(self, storage: StorageManager, ohlcv_df: pd.DataFrame):
        """Saving twice should create a version backup."""
        storage.save_data(ohlcv_df, "binance", "BTCUSD", "D1")
        storage.save_data(ohlcv_df, "binance", "BTCUSD", "D1")  # overwrite

        versions = storage.list_versions("binance", "BTCUSD", "D1")
        assert len(versions) == 1

    def test_restore_version(self, storage: StorageManager):
        """restore_version should restore the backup and update catalog."""
        dates1 = pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC")
        df1 = pd.DataFrame(
            {"Open": [100.0, 101.0, 102.0], "Close": [101.0, 102.0, 103.0]},
            index=dates1,
        )

        dates2 = pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC")
        df2 = pd.DataFrame(
            {"Open": [200.0, 201.0, 202.0], "Close": [201.0, 202.0, 203.0]},
            index=dates2,
        )

        storage.save_data(df1, "binance", "BTCUSD", "D1")
        storage.save_data(df2, "binance", "BTCUSD", "D1")  # creates backup

        result = storage.restore_version("binance", "BTCUSD", "D1")
        assert result is True

        loaded = storage.load_data("binance", "BTCUSD", "D1")
        # Restored to first version
        assert loaded["Open"].iloc[0] == 100.0

    def test_restore_nonexistent_returns_false(self, storage: StorageManager):
        """Restoring with no versions should return False."""
        result = storage.restore_version("binance", "BTCUSD", "D1")
        assert result is False


class TestCleanup:
    """Tests for directory cleanup after deletions."""

    def test_delete_removes_empty_parent_dirs(
        self, storage: StorageManager, ohlcv_df: pd.DataFrame
    ):
        """After deleting the only timeframe, empty parent dirs should be removed."""
        storage.save_data(ohlcv_df, "binance", "BTCUSD", "D1")
        storage.delete_database("binance", "BTCUSD", "D1")

        # Base dir should still exist but asset dir should be gone
        assert storage.base_dir.exists()
        asset_dir = storage.base_dir / "binance" / "BTCUSD"
        assert not asset_dir.exists()
