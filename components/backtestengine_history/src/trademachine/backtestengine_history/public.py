"""Public API for historical data loading and tick generation."""

from __future__ import annotations

import glob
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import polars as pl
from trademachine.backtestengine_broker.public import (
    STRING2TIMEFRAME_MAP,
    TIMEFRAME2STRING_MAP,
    SymbolInfo,
    Tick,
    ensure_utc,
    make_tick,
    month_bounds,
)


def _log(logger: logging.Logger | None, level: int, message: str) -> None:
    if logger is not None:
        logger.log(level, message)


def bars_to_polars(bars: Any) -> pl.DataFrame:
    """Normalizes MT5 bars into the expected Polars schema."""
    return pl.DataFrame(
        {
            "time": bars["time"],
            "open": bars["open"],
            "high": bars["high"],
            "low": bars["low"],
            "close": bars["close"],
            "tick_volume": bars["tick_volume"],
            "spread": bars["spread"],
            "real_volume": bars["real_volume"],
        }
    )


def ticks_to_polars(ticks: Any) -> pl.DataFrame:
    """Normalizes MT5 ticks into the expected Polars schema."""
    return pl.DataFrame(
        {
            "time": ticks["time"],
            "bid": ticks["bid"],
            "ask": ticks["ask"],
            "last": ticks["last"],
            "volume": ticks["volume"],
            "time_msc": ticks["time_msc"],
            "flags": ticks["flags"],
            "volume_real": ticks["volume_real"],
        }
    )


def _normalize_timestamp_index(frame: pd.DataFrame) -> pd.DataFrame:
    """Ensures market data uses a DatetimeIndex named timestamp."""
    df = frame.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        for column in ("timestamp", "datetime", "date", "time"):
            if column in df.columns:
                df[column] = pd.to_datetime(df[column], utc=True)
                df = df.set_index(column)
                break
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError(
            "DataManager payload must include a datetime index or timestamp column"
        )
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    df.index.name = "timestamp"
    return df.sort_index()


def persist_market_data_as_history(
    frame: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
    history_dir: str = "History",
) -> Path:
    """Converts a DataManager OHLCV dataframe into the StrategyTester history layout."""
    df = _normalize_timestamp_index(frame)
    normalized = df.rename(columns=str.lower)
    required_columns = {"open", "high", "low", "close", "volume"}
    missing = required_columns - set(normalized.columns)
    if missing:
        raise ValueError(f"Missing OHLCV columns: {sorted(missing)}")

    normalized = normalized.assign(
        time=(normalized.index.view("int64") // 10**9).astype("int64"),
        tick_volume=normalized["volume"].astype(float),
        spread=normalized["close"].astype(float) * 0,
        real_volume=normalized["volume"].astype(float),
        year=normalized.index.year.astype("int64"),
        month=normalized.index.month.astype("int64"),
    )
    bars = pl.from_pandas(
        normalized[
            [
                "time",
                "open",
                "high",
                "low",
                "close",
                "tick_volume",
                "spread",
                "real_volume",
                "year",
                "month",
            ]
        ],
        include_index=False,
    )

    output_dir = Path(history_dir) / "Bars" / symbol.upper() / timeframe.upper()
    output_dir.mkdir(parents=True, exist_ok=True)
    bars.write_parquet(
        str(output_dir),
        partition_by=["year", "month"],
        mkdir=True,
    )
    return output_dir


def get_bars_from_mt5(
    which_mt5: Any,
    symbol: str,
    timeframe: int | str,
    start_datetime: datetime,
    end_datetime: datetime,
    logger: logging.Logger | None = None,
    hist_dir: str = "History",
    return_df: bool = False,
) -> pl.DataFrame:
    """Fetches bars from MT5 and optionally persists them in the legacy layout."""
    start_datetime = ensure_utc(start_datetime)
    end_datetime = ensure_utc(end_datetime)
    current = start_datetime.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    frames: list[pl.DataFrame] = []

    if isinstance(timeframe, str):
        timeframe_name = timeframe
        timeframe_value = STRING2TIMEFRAME_MAP[timeframe]
    else:
        timeframe_name = TIMEFRAME2STRING_MAP[timeframe]
        timeframe_value = timeframe

    while current <= end_datetime:
        month_start, month_end = month_bounds(current)
        if (
            month_start.year == end_datetime.year
            and month_start.month == end_datetime.month
        ):
            month_end = end_datetime

        _log(
            logger,
            logging.INFO,
            f"Processing bars for {symbol} ({timeframe_name}): {month_start} -> {month_end}",
        )
        rates = which_mt5.copy_rates_range(
            symbol, timeframe_value, month_start, month_end
        )
        if rates is None or len(rates) == 0:
            current = (month_start + timedelta(days=32)).replace(day=1)
            continue

        frame = bars_to_polars(rates).with_columns(
            pl.from_epoch("time", time_unit="s")
            .dt.replace_time_zone("utc")
            .alias("time_dt")
        )
        frame = frame.with_columns(
            pl.col("time_dt").dt.year().alias("year"),
            pl.col("time_dt").dt.month().alias("month"),
        ).drop("time_dt")
        frame.write_parquet(
            str(Path(hist_dir) / "Bars" / symbol / timeframe_name),
            partition_by=["year", "month"],
            mkdir=True,
        )
        if return_df:
            frames.append(frame)
        current = (month_start + timedelta(days=32)).replace(day=1)

    return pl.concat(frames, how="vertical") if frames else pl.DataFrame()


def get_bars_from_history(
    symbol: str,
    timeframe: int | str,
    start_datetime: datetime,
    end_datetime: datetime,
    POLARS_COLLECT_ENGINE: str = "auto",
    logger: logging.Logger | None = None,
    hist_dir: str = "History",
) -> pl.DataFrame:
    """Loads bars from the StrategyTester5-compatible parquet layout."""
    start_dt = ensure_utc(start_datetime)
    end_dt = ensure_utc(end_datetime)

    timeframe_name = (
        timeframe
        if isinstance(timeframe, str)
        else TIMEFRAME2STRING_MAP[int(timeframe)]
    )
    pattern = str(
        Path(hist_dir) / "Bars" / symbol / timeframe_name / "**" / "*.parquet"
    )
    files = glob.glob(pattern, recursive=True)
    if not files:
        _log(
            logger,
            logging.ERROR,
            f"Failed to obtain bars history for {symbol} {timeframe_name}: {pattern}",
        )
        return pl.DataFrame()

    return (
        pl.scan_parquet(
            files,
            cast_options=pl.ScanCastOptions(integer_cast="allow-float"),
        )
        .filter(
            (pl.col("time") >= int(start_dt.timestamp()))
            & (pl.col("time") <= int(end_dt.timestamp()))
        )
        .sort("time")
        .select(
            "time",
            pl.col("open").cast(pl.Float64),
            pl.col("high").cast(pl.Float64),
            pl.col("low").cast(pl.Float64),
            pl.col("close").cast(pl.Float64),
            pl.col("tick_volume").cast(pl.Float64),
            pl.col("spread").cast(pl.Float64),
            pl.col("real_volume").cast(pl.Float64),
        )
        .collect(engine=POLARS_COLLECT_ENGINE)
    )


def get_ticks_from_mt5(
    which_mt5: Any,
    start_datetime: datetime,
    end_datetime: datetime,
    symbol: str,
    logger: logging.Logger | None = None,
    return_df: bool = False,
    hist_dir: str = "History",
) -> pl.DataFrame:
    """Fetches ticks from MT5 and optionally persists them in the legacy layout."""
    start_datetime = ensure_utc(start_datetime)
    end_datetime = ensure_utc(end_datetime)
    current = start_datetime.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    frames: list[pl.DataFrame] = []

    while current <= end_datetime:
        month_start, month_end = month_bounds(current)
        if (
            month_start.year == end_datetime.year
            and month_start.month == end_datetime.month
        ):
            month_end = end_datetime

        _log(
            logger,
            logging.INFO,
            f"Processing ticks for {symbol}: {month_start} -> {month_end}",
        )
        ticks = which_mt5.copy_ticks_range(
            symbol,
            month_start,
            month_end,
            which_mt5.COPY_TICKS_ALL,
        )
        if ticks is None or len(ticks) == 0:
            current = (month_start + timedelta(days=32)).replace(day=1)
            continue

        frame = ticks_to_polars(ticks).with_columns(
            pl.col("time").cast(pl.Int64),
            pl.col("time_msc").cast(pl.Int64),
        )
        frame = (
            frame.with_columns(
                pl.from_epoch(pl.col("time"), time_unit="s")
                .dt.replace_time_zone("utc")
                .alias("time_dt")
            )
            .with_columns(
                pl.col("time_dt").dt.year().alias("year"),
                pl.col("time_dt").dt.month().alias("month"),
            )
            .drop("time_dt")
        )
        frame.write_parquet(
            str(Path(hist_dir) / "Ticks" / symbol),
            partition_by=["year", "month"],
            mkdir=True,
        )
        if return_df:
            frames.append(frame)
        current = (month_start + timedelta(days=32)).replace(day=1)

    return pl.concat(frames, how="vertical") if frames else pl.DataFrame()


def get_ticks_from_history(
    symbol: str,
    start_datetime: datetime,
    end_datetime: datetime,
    POLARS_COLLECT_ENGINE: str = "auto",
    logger: logging.Logger | None = None,
    hist_dir: str = "History",
) -> pl.DataFrame:
    """Loads ticks from the StrategyTester5-compatible parquet layout."""
    start_dt = ensure_utc(start_datetime)
    end_dt = ensure_utc(end_datetime)
    pattern = str(Path(hist_dir) / "Ticks" / symbol / "**" / "*.parquet")
    files = glob.glob(pattern, recursive=True)
    if not files:
        _log(logger, logging.ERROR, f"Failed to obtain ticks for {symbol}: {pattern}")
        return pl.DataFrame()

    return (
        pl.scan_parquet(
            files,
            cast_options=pl.ScanCastOptions(integer_cast="allow-float"),
        )
        .filter(
            (pl.col("time") >= int(start_dt.timestamp()))
            & (pl.col("time") <= int(end_dt.timestamp()))
        )
        .filter(
            (pl.col("time_msc") >= int(start_dt.timestamp() * 1000))
            & (pl.col("time_msc") <= int(end_dt.timestamp() * 1000))
        )
        .sort(["time", "time_msc"])
        .select(
            pl.col("time").cast(pl.Int64),
            pl.col("bid").cast(pl.Float64),
            pl.col("ask").cast(pl.Float64),
            pl.col("last").cast(pl.Float64),
            pl.col("volume").cast(pl.Float64),
            pl.col("time_msc").cast(pl.Int64),
            pl.col("flags").cast(pl.Int64),
            pl.col("volume_real").cast(pl.Float64),
        )
        .collect(engine=POLARS_COLLECT_ENGINE)
    )


def _support_points(bar: dict[str, Any]) -> list[float]:
    open_price = float(bar["open"])
    high = float(bar["high"])
    low = float(bar["low"])
    close = float(bar["close"])
    if close >= open_price:
        return [open_price, low, high, close]
    return [open_price, high, low, close]


def _resolve_tick_count(bar: dict[str, Any]) -> int:
    tick_volume = int(bar.get("tick_volume", 1))
    return max(1, min(tick_volume, 20))


def generate_ticks_from_bar(bar: dict[str, Any], symbol_point: float) -> list[Tick]:
    """Builds synthetic ticks from a single OHLC bar."""
    tick_count = _resolve_tick_count(bar)
    spread = float(bar.get("spread", 0))
    base_time = int(bar["time"])
    base_time_msc = base_time * 1000
    step = max(1, 1000 // tick_count)

    if tick_count == 1:
        return [
            make_tick(
                time=base_time,
                bid=float(bar["close"]),
                ask=float(bar["close"]) + spread * symbol_point,
                last=float(bar["close"]),
                time_msc=base_time_msc,
            )
        ]

    support_points = _support_points(bar)
    segments = len(support_points) - 1
    ticks: list[Tick] = []
    tick_index = 0

    ticks_per_segment = tick_count // segments
    remainder = tick_count % segments
    for segment_index in range(segments):
        start = support_points[segment_index]
        end = support_points[segment_index + 1]
        steps = ticks_per_segment + (1 if segment_index < remainder else 0)
        steps = max(1, steps)

        if steps == 1:
            prices = [end]
        else:
            prices = [
                start + (end - start) * (idx / (steps - 1)) for idx in range(steps)
            ]

        for price in prices:
            ticks.append(
                make_tick(
                    time=base_time,
                    bid=price,
                    ask=price + spread * symbol_point,
                    last=price,
                    time_msc=base_time_msc + tick_index * step,
                )
            )
            tick_index += 1
    return ticks[:tick_count]


def generate_ticks_from_bars(
    bars: pl.DataFrame,
    symbol: str,
    symbol_point: float,
    logger: logging.Logger | None = None,
    hist_dir: str = "History",
    return_df: bool = False,
) -> pl.DataFrame:
    """Generates synthetic ticks and persists them in the legacy layout."""
    frames: list[pl.DataFrame] = []

    if bars.is_empty():
        return pl.DataFrame()

    bars_frame = (
        bars.with_columns(
            pl.from_epoch(pl.col("time"), time_unit="s")
            .dt.replace_time_zone("utc")
            .alias("time_dt")
        )
        .with_columns(
            pl.col("time_dt").dt.year().alias("year"),
            pl.col("time_dt").dt.month().alias("month"),
        )
        .sort("time")
    )

    for (year, month), chunk in bars_frame.group_by(
        ["year", "month"], maintain_order=True
    ):
        rows: list[dict[str, Any]] = []
        for bar in chunk.iter_rows(named=True):
            rows.extend(
                tick._asdict() for tick in generate_ticks_from_bar(bar, symbol_point)
            )
        if not rows:
            continue
        frame = (
            pl.DataFrame(rows)
            .with_columns(
                pl.col("time").cast(pl.Int64),
                pl.col("time_msc").cast(pl.Int64),
            )
            .with_columns(
                pl.lit(int(year)).alias("year"),
                pl.lit(int(month)).alias("month"),
            )
            .sort(["time", "time_msc"])
        )
        frame.write_parquet(
            str(Path(hist_dir) / "Simulated Ticks" / symbol),
            partition_by=["year", "month"],
            mkdir=True,
        )
        if return_df:
            frames.append(frame.drop("year", "month"))
        _log(logger, logging.INFO, f"Generated ticks for {symbol}: {year}-{month:02d}")

    return pl.concat(frames, how="vertical") if frames else pl.DataFrame()


def _bars_to_close_ticks(
    bars: pl.DataFrame,
    symbol: str,
    symbol_point: float,
    hist_dir: str,
) -> pl.DataFrame:
    rows = []
    for bar in bars.iter_rows(named=True):
        close = float(bar["close"])
        spread = float(bar.get("spread", 0))
        rows.append(
            make_tick(
                time=int(bar["time"]),
                bid=close,
                ask=close + spread * symbol_point,
                last=close,
                time_msc=int(bar["time"]) * 1000,
            )._asdict()
        )
    frame = pl.DataFrame(rows) if rows else pl.DataFrame()
    if not frame.is_empty():
        frame = frame.sort(["time", "time_msc"])
        output_path = Path(hist_dir) / "Ticks" / symbol / "synthetic.parquet"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        frame.write_parquet(str(output_path))
    return frame


@dataclass(slots=True)
class HistoryManager:
    """Orchestrates historical data loading for the engine."""

    mt5_instance: Any
    symbols: list[str]
    start_dt: datetime
    end_dt: datetime
    timeframe: int | str
    POLARS_COLLECT_ENGINE: str = "auto"
    logger: logging.Logger | None = None
    max_fetch_workers: int | None = None
    mt5_source: bool = False
    history_dir: str = "History"

    def _get_bars_df(self, symbol: str, timeframe: int | str) -> pl.DataFrame:
        if self.mt5_source:
            return get_bars_from_mt5(
                which_mt5=self.mt5_instance,
                symbol=symbol,
                timeframe=timeframe,
                start_datetime=self.start_dt,
                end_datetime=self.end_dt,
                logger=self.logger,
                hist_dir=self.history_dir,
                return_df=True,
            )
        return get_bars_from_history(
            symbol=symbol,
            timeframe=timeframe,
            start_datetime=self.start_dt,
            end_datetime=self.end_dt,
            POLARS_COLLECT_ENGINE=self.POLARS_COLLECT_ENGINE,
            logger=self.logger,
            hist_dir=self.history_dir,
        )

    def _get_ticks_df(self, symbol: str) -> pl.DataFrame:
        if self.mt5_source:
            return get_ticks_from_mt5(
                which_mt5=self.mt5_instance,
                symbol=symbol,
                start_datetime=self.start_dt,
                end_datetime=self.end_dt,
                logger=self.logger,
                hist_dir=self.history_dir,
                return_df=True,
            )
        return get_ticks_from_history(
            symbol=symbol,
            start_datetime=self.start_dt,
            end_datetime=self.end_dt,
            POLARS_COLLECT_ENGINE=self.POLARS_COLLECT_ENGINE,
            logger=self.logger,
            hist_dir=self.history_dir,
        )

    def fetch_history(
        self,
        modelling: str,
        symbol_info_func: Callable[[str], SymbolInfo],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Returns bar/tick payloads keyed by symbol."""
        all_bars_info: list[dict[str, Any]] = []
        all_ticks_info: list[dict[str, Any]] = []

        for symbol in self.symbols:
            if modelling == "real_ticks":
                ticks = self._get_ticks_df(symbol)
                all_ticks_info.append(
                    {
                        "symbol": symbol,
                        "ticks": ticks,
                        "size": ticks.height,
                        "counter": 0,
                    }
                )
                continue

            if modelling == "new_bar":
                bars = self._get_bars_df(symbol, self.timeframe)
                point = float(symbol_info_func(symbol).point)
                ticks = _bars_to_close_ticks(
                    bars=bars,
                    symbol=symbol,
                    symbol_point=point,
                    hist_dir=self.history_dir,
                )
                all_bars_info.append(
                    {"symbol": symbol, "bars": bars, "size": bars.height, "counter": 0}
                )
                all_ticks_info.append(
                    {
                        "symbol": symbol,
                        "ticks": ticks,
                        "size": ticks.height,
                        "counter": 0,
                    }
                )
                continue

            bars = self._get_bars_df(symbol, "M1")
            point = float(symbol_info_func(symbol).point)
            ticks = generate_ticks_from_bars(
                bars=bars,
                symbol=symbol,
                symbol_point=point,
                logger=self.logger,
                hist_dir=self.history_dir,
                return_df=True,
            )
            all_bars_info.append(
                {"symbol": symbol, "bars": bars, "size": bars.height, "counter": 0}
            )
            all_ticks_info.append(
                {"symbol": symbol, "ticks": ticks, "size": ticks.height, "counter": 0}
            )

        return all_bars_info, all_ticks_info

    def synchronize_timeframes(self) -> None:
        """Compatibility no-op for the legacy API."""
        return None


__all__ = [
    "HistoryManager",
    "bars_to_polars",
    "generate_ticks_from_bar",
    "generate_ticks_from_bars",
    "persist_market_data_as_history",
    "get_bars_from_history",
    "get_bars_from_mt5",
    "get_ticks_from_history",
    "get_ticks_from_mt5",
    "ticks_to_polars",
]
