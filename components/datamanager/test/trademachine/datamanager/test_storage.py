"""Unit tests for StorageManager with TimescaleDB."""

from datetime import UTC

import pandas as pd
import pytest
from trademachine.datamanager.db.storage import StorageManager


@pytest.fixture
def storage() -> StorageManager:
    """StorageManager instance."""
    return StorageManager()


@pytest.fixture
def ohlcv_df() -> pd.DataFrame:
    """Sample OHLCV DataFrame with 5 minute bars."""
    dates = pd.date_range("2024-01-01 12:00:00", periods=5, freq="min", tz=UTC)
    return pd.DataFrame(
        {
            "Open": [100.0, 101.0, 102.0, 103.0, 104.0],
            "High": [101.0, 102.0, 103.0, 104.0, 105.0],
            "Low": [99.0, 100.0, 101.0, 102.0, 103.0],
            "Close": [101.0, 102.0, 103.0, 104.0, 105.0],
            "Volume": [1000.0, 1100.0, 1200.0, 1300.0, 1400.0],
        },
        index=dates,
    )


class TestSaveAndLoad:
    """Tests for save_data and load_data round-trip with TimescaleDB."""

    def test_save_load_roundtrip(
        self, storage: StorageManager, ohlcv_df: pd.DataFrame, db_session
    ):
        """Data saved to Postgres and loaded should be identical."""
        storage.save_data(ohlcv_df, "binance", "BTCUSD", "M1")
        loaded = storage.load_data("binance", "BTCUSD", "M1")

        assert len(loaded) == 5
        assert loaded["Open"].tolist() == [100.0, 101.0, 102.0, 103.0, 104.0]
        assert loaded["Volume"].sum() == 6000.0
        # Postgres returns timezone-aware timestamps if we requested them or if stored as TIMESTAMPTZ
        assert isinstance(loaded.index, pd.DatetimeIndex)

    def test_load_nonexistent_raises(self, storage: StorageManager, db_session):
        """Loading a non-existent database should raise FileNotFoundError or similar."""
        # Source doesn't exist
        with pytest.raises(FileNotFoundError):
            storage.load_data("nonexistent", "BTCUSD", "M1")

    def test_save_and_get_info(
        self, storage: StorageManager, ohlcv_df: pd.DataFrame, db_session
    ):
        """get_database_info should return correct metadata from the database."""
        storage.save_data(ohlcv_df, "binance", "BTCUSD", "M1")
        info = storage.get_database_info("binance", "BTCUSD", "M1")

        assert info["source"] == "binance"
        assert info["asset"] == "BTCUSD"
        assert info["timeframe"] == "M1"
        assert info["rows"] == 5
        assert "start_date" in info
        assert "end_date" in info

    def test_get_info_nonexistent(self, storage: StorageManager, db_session):
        """get_database_info for non-existent DB should return Not Found status."""
        info = storage.get_database_info("binance", "BTCUSD", "M1")
        assert info.get("status") == "Not Found"


class TestAppendData:
    """Tests for append_data (which uses UPSERT)."""

    def test_append_deduplicates_by_timestamp(
        self, storage: StorageManager, db_session
    ):
        """Appending rows with duplicate timestamp should update existing records."""
        dates1 = pd.date_range("2024-01-01 10:00:00", periods=3, freq="min", tz=UTC)
        df1 = pd.DataFrame(
            {
                "Open": [100.0, 101.0, 102.0],
                "High": [101.0, 102.0, 103.0],
                "Low": [99.0, 100.0, 101.0],
                "Close": [101.0, 102.0, 103.0],
                "Volume": [100.0, 100.0, 100.0],
            },
            index=dates1,
        )

        # Row at 10:02 is duplicated but with different Close
        dates2 = pd.date_range("2024-01-01 10:02:00", periods=2, freq="min", tz=UTC)
        df2 = pd.DataFrame(
            {
                "Open": [102.0, 103.0],
                "High": [103.0, 104.0],
                "Low": [101.0, 102.0],
                "Close": [200.0, 104.0],
                "Volume": [100.0, 100.0],
            },
            index=dates2,
        )

        storage.save_data(df1, "binance", "ETHUSD", "M1")
        storage.append_data(df2, "binance", "ETHUSD", "M1")

        loaded = storage.load_data("binance", "ETHUSD", "M1")
        assert len(loaded) == 4  # 3 original + 1 new (the other was updated)

        # Normalize the target_ts to be UTC aware for comparison if needed,
        # or ensure loaded index matches.
        target_ts = pd.Timestamp("2024-01-01 10:02:00", tz=UTC)
        # Check if index is TZ aware or naive
        if loaded.index.tz is None:
            target_ts = target_ts.tz_localize(None)

        assert float(loaded.loc[target_ts]["Close"]) == 200.0


class TestCatalog:
    """Tests for catalog (Postgres) operations."""

    def test_list_databases_empty(self, storage: StorageManager, db_session):
        """list_databases should return empty list when nothing is saved."""
        assert storage.list_databases() == []

    def test_list_databases_after_save(
        self, storage: StorageManager, ohlcv_df: pd.DataFrame, db_session
    ):
        """list_databases should return M1 hypertable and active continuous aggregates."""
        storage.save_data(ohlcv_df, "binance", "BTCUSD", "M1")
        storage.create_continuous_aggregate("H1")
        storage.refresh_continuous_aggregate("H1")

        dbs = storage.list_databases()
        # Filter for the specific asset we just saved
        asset_dbs = [d for d in dbs if d["asset"] == "BTCUSD"]

        assert len(asset_dbs) == 2
        m1_entry = next(d for d in asset_dbs if d["timeframe"] == "M1")
        h1_entry = next(d for d in asset_dbs if d["timeframe"] == "H1")
        assert m1_entry["asset"] == "BTCUSD"
        assert m1_entry["rows"] == 5
        assert h1_entry["rows"] == 1

    def test_get_stats(
        self, storage: StorageManager, ohlcv_df: pd.DataFrame, db_session
    ):
        """get_stats should aggregate across all assets in Postgres."""
        storage.save_data(ohlcv_df, "binance", "BTCUSD", "M1")
        storage.save_data(ohlcv_df, "binance", "ETHUSD", "M1")

        stats = storage.get_stats()
        assert stats["assets_count"] == 2
        assert stats["sources"]["binance"] == 2
        assert stats["total_rows"] == 10

    def test_delete_database(
        self, storage: StorageManager, ohlcv_df: pd.DataFrame, db_session
    ):
        """Deleting an asset should remove its data and metadata."""
        storage.save_data(ohlcv_df, "binance", "BTCUSD", "M1")

        result = storage.delete_database("binance", "BTCUSD")
        assert result is True
        assert storage.list_databases() == []

    def test_delete_all(
        self, storage: StorageManager, ohlcv_df: pd.DataFrame, db_session
    ):
        """delete_all should truncate everything."""
        storage.save_data(ohlcv_df, "binance", "BTCUSD", "M1")
        storage.save_data(ohlcv_df, "binance", "ETHUSD", "M1")

        result = storage.delete_all()
        assert result is True
        assert storage.list_databases() == []


class TestContinuousAggregates:
    """Tests for persisted derived timeframes."""

    def test_save_and_load_resampled_timeframe(
        self, storage: StorageManager, db_session
    ):
        """M5 continuous aggregate should reflect aggregated M1 source data."""
        dates = pd.date_range("2024-01-01 00:00:00", periods=10, freq="min", tz=UTC)
        m1_df = pd.DataFrame(
            {"Open": 100.0, "High": 110.0, "Low": 90.0, "Close": 105.0, "Volume": 10.0},
            index=dates,
        )

        storage.save_data(m1_df, "binance", "BTCUSD", "M1")
        storage.create_continuous_aggregate("M5")
        storage.refresh_continuous_aggregate("M5")

        loaded = storage.load_data("binance", "BTCUSD", "M5")
        info = storage.get_database_info("binance", "BTCUSD", "M5")

        assert len(loaded) == 2
        assert loaded["Volume"].tolist() == [50.0, 50.0]
        assert info["rows"] == 2

    def test_aggregate_reflects_m1_data(
        self, storage: StorageManager, ohlcv_df: pd.DataFrame, db_session
    ):
        """H1 continuous aggregate should correctly reflect the aggregated M1 source data."""
        storage.save_data(ohlcv_df, "binance", "BTCUSD", "M1")
        storage.create_continuous_aggregate("H1")
        storage.refresh_continuous_aggregate("H1")

        loaded = storage.load_data("binance", "BTCUSD", "H1")
        assert len(loaded) == 1
        assert loaded["Open"].iloc[0] == 100.0
        assert loaded["High"].iloc[0] == 105.0
        assert loaded["Low"].iloc[0] == 99.0
        assert loaded["Close"].iloc[0] == 105.0
        assert loaded["Volume"].iloc[0] == 6000.0

    def test_delete_specific_resampled_timeframe_keeps_m1(
        self, storage: StorageManager, ohlcv_df: pd.DataFrame, db_session
    ):
        """Deleting a derived timeframe drops the aggregate entirely."""
        storage.save_data(ohlcv_df, "binance", "BTCUSD", "M1")
        storage.create_continuous_aggregate("H1")
        storage.refresh_continuous_aggregate("H1")

        storage.delete_database("binance", "BTCUSD", "H1")
        assert not storage.aggregate_exists("H1")

        m1_loaded = storage.load_data("binance", "BTCUSD", "M1")
        assert len(m1_loaded) == 5

    def test_m1_delete_keeps_persisted_resampled_timeframe(
        self, storage: StorageManager, ohlcv_df: pd.DataFrame, db_session
    ):
        """Deleting M1 alone should keep the materialized aggregate and hide the M1 catalog entry."""
        storage.save_data(ohlcv_df, "binance", "BTCUSD", "M1")
        storage.create_continuous_aggregate("H1")
        storage.refresh_continuous_aggregate("H1")

        assert storage.delete_database("binance", "BTCUSD", "M1") is True
        assert storage.get_database_info("binance", "BTCUSD", "M1") == {
            "status": "Not Found"
        }

        h1_info = storage.get_database_info("binance", "BTCUSD", "H1")
        assert h1_info["rows"] == 1
