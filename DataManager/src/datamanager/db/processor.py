import pandas as pd


class DataProcessor:
    """Utility class for converting and repairing OHLC timeframes."""

    TF_MAPPING = {
        "M1": "1min",
        "M2": "2min",
        "M5": "5min",
        "M10": "10min",
        "M15": "15min",
        "M30": "30min",
        "H1": "1h",
        "H2": "2h",
        "H3": "3h",
        "H4": "4h",
        "H6": "6h",
        "D1": "D",
        "W1": "W",
    }

    @classmethod
    def resample_ohlc(cls, df: pd.DataFrame, target_timeframe: str) -> pd.DataFrame:
        """Takes an OHLCV DataFrame (lower TF) and converts it to a higher timeframe."""
        if target_timeframe.upper() not in cls.TF_MAPPING:
            raise ValueError(f"Target timeframe not supported: {target_timeframe}. Use {list(cls.TF_MAPPING.keys())}")

        rule = cls.TF_MAPPING[target_timeframe.upper()]
        cols = {c.lower(): c for c in df.columns}

        agg_dict = {}
        if "open" in cols:
            agg_dict[cols["open"]] = "first"
        if "high" in cols:
            agg_dict[cols["high"]] = "max"
        if "low" in cols:
            agg_dict[cols["low"]] = "min"
        if "close" in cols:
            agg_dict[cols["close"]] = "last"
        if "volume" in cols:
            agg_dict[cols["volume"]] = "sum"

        if not agg_dict:
            raise ValueError("The DataFrame does not contain valid OHLC columns for resampling.")

        resampled_df = df.resample(rule).agg(agg_dict).dropna()
        return resampled_df

    @classmethod
    def fill_gaps(cls, df: pd.DataFrame, timeframe: str, method: str = "ffill") -> pd.DataFrame:
        """Fill gaps in OHLCV data caused by weekends, holidays, or missing M1 candles.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.
            timeframe: Timeframe string (e.g. "M1", "H1"). Used to infer expected frequency.
            method: Gap-filling strategy:
                - "ffill": forward-fill prices, zero-fill volume (default).
                - "drop": drop all rows with NaN (returns original minus gaps).
                - "none": reindex without filling (leaves NaN for upstream handling).

        Returns:
            DataFrame with gaps handled according to the chosen method.
        """
        if timeframe.upper() not in cls.TF_MAPPING:
            raise ValueError(f"Unknown timeframe: {timeframe}. Use {list(cls.TF_MAPPING.keys())}")

        if df.empty:
            return df

        freq = cls.TF_MAPPING[timeframe.upper()]
        full_index = pd.date_range(df.index.min(), df.index.max(), freq=freq)
        df_full = df.reindex(full_index)
        df_full.index.name = df.index.name

        if method == "ffill":
            price_cols = [c for c in df_full.columns if c.lower() != "volume"]
            df_full[price_cols] = df_full[price_cols].ffill()
            if "Volume" in df_full.columns:
                df_full["Volume"] = df_full["Volume"].fillna(0.0)
        elif method == "drop":
            df_full = df_full.dropna()
        elif method == "none":
            pass
        else:
            raise ValueError(f"Unknown fill method: '{method}'. Use 'ffill', 'drop', or 'none'.")

        return df_full
