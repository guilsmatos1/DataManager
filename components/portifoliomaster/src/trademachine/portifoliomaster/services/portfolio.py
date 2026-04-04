"""
Portfolio Manager Module
========================
Manages portfolio creation and strategy metric calculations.
Uses Polars (Rust) for high-performance processing.
Follows PEP8 standards and uses descriptive naming.
"""

import json
import logging
import os

import numpy as np
import pandas as pd
import polars as pl
from trademachine.core.logger import LOGGER_NAME
from trademachine.portifoliomaster.services.metrics import (
    clean_mt5_numeric_string,
    compute_vector_metrics,
)

logger = logging.getLogger(LOGGER_NAME)


class PortfolioManager:
    """Class to combine multiple strategies and manage metrics."""

    def __init__(self):
        self.strategies: dict[str, pl.DataFrame] = {}
        self.strategy_lots: dict[str, float] = {}
        self._lots_meta: dict = {}  # metadata persisted inside cache_lots.json

    @staticmethod
    def _lots_cache_path(cache_path: str) -> str:
        """Returns the path for the lots sidecar JSON file alongside the cache."""
        base = os.path.splitext(cache_path)[0]
        return f"{base}_lots.json"

    def save_lots_cache(self, cache_path: str) -> None:
        """Persists strategy_lots (and any metadata) to a JSON sidecar file."""
        if not self.strategy_lots:
            return
        lots_path = self._lots_cache_path(cache_path)
        try:
            data: dict = dict(self.strategy_lots)
            if self._lots_meta:
                data["__meta__"] = self._lots_meta
            with open(lots_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            logger.info(f"Lots cache saved to {os.path.abspath(lots_path)}")
        except Exception as e:
            logger.warning(f"Failed to write lots cache: {e}")

    def load_lots_cache(self, cache_path: str) -> None:
        """Loads strategy_lots (and metadata) from the JSON sidecar if it exists."""
        lots_path = self._lots_cache_path(cache_path)
        if not os.path.exists(lots_path):
            return
        try:
            with open(lots_path, encoding="utf-8") as f:
                raw: dict = json.load(f)
            self._lots_meta = raw.pop("__meta__", {})
            self.strategy_lots = raw
            logger.info(f"Lots cache loaded from {os.path.abspath(lots_path)}")
        except Exception as e:
            logger.warning(f"Could not load lots cache: {e}")

    def add_strategy(self, name: str, strategy_deals_df: pd.DataFrame) -> bool:
        """
        Cleans and adds a strategy's deals to the manager.
        """
        if strategy_deals_df.empty:
            logger.warning(f"Strategy '{name}' ignored: Empty DataFrame.")
            return False

        lazy_df = pl.from_pandas(strategy_deals_df)

        processed_df = (
            lazy_df.filter(pl.col("Horário").str.strip_chars() != "")
            .filter(pl.col("Tipo").is_in(["buy", "sell"]))
            .filter(pl.col("Direção").is_in(["out", "in/out"]))
            .with_columns(
                [
                    clean_mt5_numeric_string(pl.col("Lucro")).alias("Lucro"),
                    clean_mt5_numeric_string(pl.col("Comissão")).alias("Comissão"),
                    clean_mt5_numeric_string(pl.col("Swap")).alias("Swap"),
                    pl.col("Horário").str.to_datetime(
                        "%Y.%m.%d %H:%M:%S", strict=False
                    ),
                ]
            )
            .with_columns(
                [
                    (pl.col("Lucro") + pl.col("Comissão") + pl.col("Swap")).alias(
                        "Net_Profit"
                    )
                ]
            )
            .sort("Horário")
        )

        # We now keep all original columns (Ticket, Symbol, Type, Volume, Price, etc.)
        # plus the calculated Net_Profit and normalized Horário.
        self.strategies[name] = processed_df

        # Extract the representative lot size from the Volume column of closed trades.
        # Uses the median to be robust against variable-lot EAs.
        if "Volume" in processed_df.columns:
            try:
                cleaned_vol = clean_mt5_numeric_string(processed_df["Volume"])
                positive = cleaned_vol.filter(cleaned_vol > 0)
                if len(positive):
                    median_val = positive.median()
                    if median_val is not None:
                        self.strategy_lots[name] = float(median_val)
            except Exception:
                logger.debug(
                    f"Could not extract lot for '{name}'; will default to 1.0."
                )

        return True

    def calculate_strategy_metrics(self, strategy_name: str) -> dict | None:
        """Calculates performance metrics for an individual strategy."""
        if strategy_name not in self.strategies:
            return None

        strategy_df = self.strategies[strategy_name]
        metrics = compute_vector_metrics(strategy_df["Net_Profit"])

        return {
            "Profit": metrics["Profit"],
            "Trades": len(strategy_df),
            "MaxDD": metrics["MaxDD"],
            "RetDD": metrics["RetDD"],
        }

    def get_all_trades_long(self) -> pl.DataFrame:
        """
        Returns all trades from all strategies in a single long-format DataFrame.
        This is used for trade-by-trade portfolio calculation (matching QuantAnalyzer).
        """
        if not self.strategies:
            return pl.DataFrame()

        all_dfs = []
        for name, df in self.strategies.items():
            all_dfs.append(df.with_columns(pl.lit(name).alias("Strategy")))

        return pl.concat(all_dfs).sort("Horário")

    def get_returns_matrix(self) -> pl.DataFrame:
        """
        Generates a wide matrix where each column is a strategy and each row is a timestamp.
        Used for caching and plotting.
        """
        if not self.strategies:
            return pl.DataFrame()

        all_strategy_dfs = [
            df.with_columns(pl.lit(name).alias("strat_name"))
            for name, df in self.strategies.items()
        ]
        combined_long_df = pl.concat(all_strategy_dfs)

        return (
            combined_long_df.group_by(["Horário", "strat_name"])
            .agg(pl.col("Net_Profit").sum())
            .pivot(index="Horário", on="strat_name", values="Net_Profit")
            .sort("Horário")
            .fill_null(0.0)
        )

    def compute_periodic_correlation(
        self, long_df: pl.DataFrame, strategy_names: list[str], period: str
    ) -> np.ndarray:
        """Computes the pairwise correlation matrix grouped by time period.

        Nulls are intentionally kept before calling .corr() so that Polars
        calculates correlation only on periods where both strategies traded.
        Filling with 0.0 would dilute correlations toward zero for sparse
        strategies, producing values inconsistent with the optimization engine.

        Args:
            long_df: Long-format trades DataFrame with columns Horário, Net_Profit, Strategy.
            strategy_names: Ordered list of strategy names (defines matrix row/column order).
            period: Aggregation period — one of H, D, W, M.

        Returns:
            Square numpy float64 correlation matrix of shape (n, n).
        """
        period_map = {"H": "1h", "D": "1d", "W": "1w", "M": "1mo"}
        truncate_at = period_map.get(period.upper(), "1d")

        periodic = (
            long_df.with_columns(
                pl.col("Horário").dt.truncate(truncate_at).alias("_period")
            )
            .group_by(["_period", "Strategy"])
            .agg(pl.col("Net_Profit").sum())
            .pivot(
                index="_period",
                on="Strategy",
                values="Net_Profit",
                aggregate_function="sum",
            )
            .sort("_period")
            .select(strategy_names)
        )
        values = periodic.to_numpy().astype(np.float64)
        num_strategies = len(strategy_names)
        corr = np.full((num_strategies, num_strategies), np.nan, dtype=np.float64)

        for i in range(num_strategies):
            corr[i, i] = 1.0
            left = values[:, i]
            for j in range(i + 1, num_strategies):
                right = values[:, j]
                overlap = ~np.isnan(left) & ~np.isnan(right)
                if np.count_nonzero(overlap) < 2:
                    continue

                left_overlap = left[overlap]
                right_overlap = right[overlap]
                if np.std(left_overlap) == 0.0 or np.std(right_overlap) == 0.0:
                    continue

                pair_corr = float(np.corrcoef(left_overlap, right_overlap)[0, 1])
                corr[i, j] = pair_corr
        return corr

    @staticmethod
    def round_lot(lot: float) -> float:
        """Rounds a lot to the MT5 standard representation (usually 2 decimals, to nearest 0.01)."""
        return round(float(lot), 2)
