"""Unit tests for DataProcessor (resample_ohlc, fill_gaps)."""

import pandas as pd
import pytest
from trademachine.datamanager.db.processor import DataProcessor


class TestResampleOhlc:
    """Tests for DataProcessor.resample_ohlc."""

    @pytest.fixture
    def ohlcv_df(self) -> pd.DataFrame:
        """Sample M1 OHLCV DataFrame covering 3 hourly bars."""
        dates = pd.date_range("2024-01-01 09:00", periods=3, freq="h", tz="UTC")
        return pd.DataFrame(
            {
                "Open": [100.0, 101.0, 102.0],
                "High": [101.5, 102.5, 103.5],
                "Low": [99.5, 100.5, 101.5],
                "Close": [101.0, 102.0, 103.0],
                "Volume": [1000, 1100, 1200],
            },
            index=dates,
        )

    def test_resample_h1_aggregates_correctly(self, ohlcv_df: pd.DataFrame):
        """H1 resample on 3 M1 bars (09:00, 10:00, 11:00) yields 3 H1 bars, one per hour."""
        result = DataProcessor.resample_ohlc(ohlcv_df, "H1")

        assert len(result) == 3
        # Each H1 bar should reflect its hourly M1 data (1 M1 bar per hour → same values)
        assert result["Open"].iloc[0] == 100.0
        assert result["High"].iloc[0] == 101.5
        assert result["Low"].iloc[0] == 99.5
        assert result["Close"].iloc[0] == 101.0
        assert result["Volume"].iloc[0] == 1000
        assert result["Open"].iloc[1] == 101.0
        assert result["Close"].iloc[1] == 102.0
        assert result["Volume"].iloc[1] == 1100

    def test_resample_d1_single_day(self, ohlcv_df: pd.DataFrame):
        """D1 should aggregate all hourly bars into one daily bar."""
        result = DataProcessor.resample_ohlc(ohlcv_df, "D1")

        assert len(result) == 1
        assert result["Open"].iloc[0] == 100.0
        assert result["High"].iloc[0] == 103.5
        assert result["Low"].iloc[0] == 99.5

    def test_resample_unknown_timeframe_raises(self, ohlcv_df: pd.DataFrame):
        """Unsupported timeframe should raise ValueError."""
        with pytest.raises(ValueError, match="not supported"):
            DataProcessor.resample_ohlc(ohlcv_df, "INVALID")

    def test_resample_no_ohlcv_columns_raises(self):
        """DataFrame without OHLCV columns should raise ValueError."""
        df = pd.DataFrame({"foo": [1, 2, 3]})
        with pytest.raises(ValueError, match="does not contain valid OHLC"):
            DataProcessor.resample_ohlc(df, "H1")

    def test_resample_partial_columns(self) -> pd.DataFrame:
        """Resample should work with only a subset of OHLCV columns."""
        dates = pd.date_range("2024-01-01 09:00", periods=3, freq="h", tz="UTC")
        df = pd.DataFrame(
            {"Open": [100.0, 101.0, 102.0], "Close": [101.0, 102.0, 103.0]},
            index=dates,
        )
        result = DataProcessor.resample_ohlc(df, "H1")
        # With freq='1h', each M1 bar becomes its own H1 bar (1 M1 bar per hour → 1 H1 bar)
        assert len(result) == 3
        assert result["Open"].iloc[0] == 100.0
        assert result["Close"].iloc[0] == 101.0

    def test_resample_drops_na_bars(self, ohlcv_df: pd.DataFrame):
        """Resampled bars with NaN values should be dropped."""
        result = DataProcessor.resample_ohlc(ohlcv_df, "H1")
        assert result.isna().sum().sum() == 0


class TestFillGaps:
    """Tests for DataProcessor.fill_gaps."""

    @pytest.fixture
    def gapped_df(self) -> pd.DataFrame:
        """M1 DataFrame with a weekend gap (Sat/Sun missing)."""
        dates = pd.date_range("2024-01-05 09:00", periods=5, freq="h", tz="UTC")
        # Simulate a 2-day gap by manually constructing with a gap
        df = pd.DataFrame(
            {
                "Open": [100.0, 101.0, 99.0, 100.5, 101.5],
                "High": [101.0, 102.0, 100.0, 101.5, 102.5],
                "Low": [99.5, 100.5, 98.5, 100.0, 101.0],
                "Close": [101.0, 102.0, 99.5, 101.0, 102.0],
                "Volume": [1000, 1100, 900, 1050, 1150],
            },
            index=dates,
        )
        return df

    def test_fill_gaps_ffill_price_cols(self, gapped_df: pd.DataFrame):
        """ffill should forward-fill price columns, zero-fill volume."""
        result = DataProcessor.fill_gaps(gapped_df, "M1", method="ffill")

        assert len(result) > len(gapped_df)
        assert result.loc[:, "Volume"].notna().all()

    def test_fill_gaps_drop(self, gapped_df: pd.DataFrame):
        """drop should remove rows with NaN (return original minus gaps)."""
        result = DataProcessor.fill_gaps(gapped_df, "M1", method="drop")

        assert len(result) <= len(gapped_df)
        assert result.isna().sum().sum() == 0

    def test_fill_gaps_none(self, gapped_df: pd.DataFrame):
        """none should reindex without filling, leaving NaN."""
        result = DataProcessor.fill_gaps(gapped_df, "M1", method="none")

        assert len(result) > len(gapped_df)
        assert result.isna().sum().sum() > 0

    def test_fill_gaps_unknown_timeframe_raises(self, gapped_df: pd.DataFrame):
        """Unknown timeframe should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown timeframe"):
            DataProcessor.fill_gaps(gapped_df, "INVALID")

    def test_fill_gaps_unknown_method_raises(self, gapped_df: pd.DataFrame):
        """Unknown fill method should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown fill method"):
            DataProcessor.fill_gaps(gapped_df, "M1", method="unknown")

    def test_fill_gaps_empty_df(self):
        """Empty DataFrame should be returned unchanged."""
        empty = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
        empty.index = pd.to_datetime(empty.index)
        result = DataProcessor.fill_gaps(empty, "M1")
        assert result.empty
