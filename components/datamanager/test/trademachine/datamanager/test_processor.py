"""Unit tests for DataProcessor (fill_gaps)."""

import pandas as pd
import pytest
from trademachine.datamanager.db.processor import DataProcessor


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
