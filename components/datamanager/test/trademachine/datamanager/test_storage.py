"""Unit tests for StorageManager with TimescaleDB."""

from datetime import UTC

import pandas as pd
import pytest
from sqlalchemy import create_engine, text
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
        """list_databases should return entries for all TFs (since they are views)."""
        storage.save_data(ohlcv_df, "binance", "BTCUSD", "M1")

        dbs = storage.list_databases()
        # Filter for the specific asset we just saved
        asset_dbs = [d for d in dbs if d["asset"] == "BTCUSD"]

        # We now only return explicitly saved M1 entries to avoid cluttering the list
        assert len(asset_dbs) == 1
        assert asset_dbs[0]["timeframe"] == "M1"

        # Verify one entry
        m1_entry = next(d for d in asset_dbs if d["timeframe"] == "M1")
        assert m1_entry["asset"] == "BTCUSD"
        assert m1_entry["rows"] == 5

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
    """Tests for TimescaleDB Continuous Aggregates (M1 -> higher TFs)."""

    def test_continuous_aggregate_read(self, storage: StorageManager, db_session):
        """Data inserted in M1 should be visible in M5 view (after refresh)."""
        # Create 10 minutes of data (2 bars of M5)
        dates = pd.date_range("2024-01-01 00:00:00", periods=10, freq="min", tz=UTC)
        df = pd.DataFrame(
            {"Open": 100.0, "High": 110.0, "Low": 90.0, "Close": 105.0, "Volume": 10.0},
            index=dates,
        )
        storage.save_data(df, "binance", "BTCUSD", "M1")

        # TimescaleDB continuous aggregates are refreshed in the background or manually.
        # refresh_continuous_aggregate() cannot run inside a transaction block.
        # We use a separate engine with autocommit.
        from trademachine.datamanager.db.database import DATABASE_URL

        autocommit_engine = create_engine(DATABASE_URL, isolation_level="AUTOCOMMIT")
        with autocommit_engine.connect() as conn:
            conn.execute(
                text("CALL refresh_continuous_aggregate('ohlcv_m5', NULL, NULL);")
            )

        # Load from M5
        df_m5 = storage.load_data("binance", "BTCUSD", "M5")

        assert len(df_m5) == 2
        # Use close to ensure indexing worked
        assert df_m5["Volume"].iloc[0] == 50.0  # 5 minutes * 10.0 volume
