from datetime import datetime

import polars as pl
from trademachine.backtestengine_history.public import (
    generate_ticks_from_bars,
    get_bars_from_history,
)


def test_get_bars_from_history_reads_legacy_layout(tmp_path):
    base_dir = tmp_path / "History" / "Bars" / "EURUSD" / "M1" / "year=2024" / "month=1"
    base_dir.mkdir(parents=True)
    bars = pl.DataFrame(
        {
            "time": [1704067200, 1704067260],
            "open": [1.1000, 1.1005],
            "high": [1.1010, 1.1015],
            "low": [1.0995, 1.1000],
            "close": [1.1005, 1.1010],
            "tick_volume": [5, 4],
            "spread": [10, 10],
            "real_volume": [0, 0],
        }
    )
    bars.write_parquet(base_dir / "chunk.parquet")

    result = get_bars_from_history(
        symbol="EURUSD",
        timeframe="M1",
        start_datetime=datetime(2024, 1, 1, 0, 0),
        end_datetime=datetime(2024, 1, 1, 0, 2),
        hist_dir=str(tmp_path / "History"),
    )

    assert result.height == 2
    assert result["close"].to_list() == [1.1005, 1.1010]


def test_generate_ticks_from_bars_builds_non_empty_frame(tmp_path):
    bars = pl.DataFrame(
        {
            "time": [1704067200],
            "open": [1.1000],
            "high": [1.1010],
            "low": [1.0990],
            "close": [1.1005],
            "tick_volume": [4],
            "spread": [10],
            "real_volume": [0],
        }
    )

    ticks = generate_ticks_from_bars(
        bars=bars,
        symbol="EURUSD",
        symbol_point=0.0001,
        hist_dir=str(tmp_path / "History"),
        return_df=True,
    )

    assert ticks.height >= 4
    assert ticks["bid"].min() <= 1.0990
    assert ticks["ask"].max() >= 1.1000
