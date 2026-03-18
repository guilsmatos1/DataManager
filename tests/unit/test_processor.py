import numpy as np
import pandas as pd
import pytest

from datamanager.db.processor import DataProcessor


@pytest.fixture
def sample_m1_data():
    """Generates 60 minutes of M1 OHLC data."""
    dates = pd.date_range(start="2023-01-01 00:00:00", periods=60, freq="1min")
    data = {
        "Open": np.linspace(100, 110, 60),
        "High": np.linspace(105, 115, 60),
        "Low": np.linspace(95, 105, 60),
        "Close": np.linspace(102, 112, 60),
        "Volume": np.ones(60) * 100,
    }
    df = pd.DataFrame(data, index=dates)
    return df


def test_resample_m1_to_h1(sample_m1_data):
    """Tests if 60 minutes of M1 results in 1 row of H1."""
    processor = DataProcessor()
    df_h1 = processor.resample_ohlc(sample_m1_data, "H1")

    assert len(df_h1) == 1
    assert df_h1.index[0] == pd.Timestamp("2023-01-01 00:00:00")
    assert df_h1["Open"].iloc[0] == sample_m1_data["Open"].iloc[0]
    assert df_h1["High"].iloc[0] == sample_m1_data["High"].max()
    assert df_h1["Low"].iloc[0] == sample_m1_data["Low"].min()
    assert df_h1["Close"].iloc[0] == sample_m1_data["Close"].iloc[-1]
    assert df_h1["Volume"].iloc[0] == sample_m1_data["Volume"].sum()


def test_resample_m1_to_m5(sample_m1_data):
    """Tests if 60 minutes of M1 results in 12 rows of M5."""
    processor = DataProcessor()
    df_m5 = processor.resample_ohlc(sample_m1_data, "M5")

    assert len(df_m5) == 12
    # Check first candle of 5 min
    assert df_m5["Open"].iloc[0] == sample_m1_data["Open"].iloc[0]
    assert df_m5["Close"].iloc[0] == sample_m1_data["Close"].iloc[4]


def test_invalid_timeframe(sample_m1_data):
    """Tests if invalid timeframe raises ValueError."""
    processor = DataProcessor()
    with pytest.raises(ValueError, match="Target timeframe not supported"):
        processor.resample_ohlc(sample_m1_data, "INVALID")


def test_missing_columns():
    """Tests if missing OHLC columns raises ValueError."""
    dates = pd.date_range(start="2023-01-01", periods=5, freq="1min")
    df = pd.DataFrame({"Price": [1, 2, 3, 4, 5]}, index=dates)
    processor = DataProcessor()
    with pytest.raises(ValueError, match="The DataFrame does not contain valid OHLC columns"):
        processor.resample_ohlc(df, "H1")
