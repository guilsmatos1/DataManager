"""
Cache Service
=============
Centralizes cache.parquet and cache_lots.json operations.
"""

import json
import logging
import os
import shutil
import time
from dataclasses import dataclass

import polars as pl
from trademachine.core.logger import LOGGER_NAME
from trademachine.portifoliomaster.core.exceptions import DataError
from trademachine.portifoliomaster.services.portfolio import PortfolioManager

logger = logging.getLogger(LOGGER_NAME)


@dataclass(slots=True)
class CacheInfo:
    path: str
    size_str: str
    strategy_count: int
    date_range: str
    modified: str


class CacheService:
    """Encapsulates cache file operations for parquet and lots sidecar files."""

    def __init__(self, cache_path: str):
        self.cache_path = cache_path

    @staticmethod
    def lots_cache_path(cache_path: str) -> str:
        """Returns the lots sidecar path for a cache file."""
        return PortfolioManager._lots_cache_path(cache_path)

    @property
    def active_lots_path(self) -> str:
        return self.lots_cache_path(self.cache_path)

    def load_into_manager(self, portfolio_manager: PortfolioManager) -> list[str]:
        """Loads active cache data into the provided portfolio manager."""
        cached_df = pl.read_parquet(self.cache_path)
        if "Horário" not in cached_df.columns:
            raise DataError("Cache file is incompatible (missing 'Horário' column).")

        loaded_names = [col for col in cached_df.columns if col != "Horário"]
        portfolio_manager.strategies = {}
        portfolio_manager.strategy_lots = {}
        portfolio_manager._lots_meta = {}
        for name in loaded_names:
            portfolio_manager.strategies[name] = (
                cached_df.select(["Horário", name])
                .rename({name: "Net_Profit"})
                .filter(pl.col("Net_Profit") != 0.0)
            )
        portfolio_manager.load_lots_cache(self.cache_path)
        return loaded_names

    def persist_manager(
        self, portfolio_manager: PortfolioManager, loaded_names: list[str]
    ) -> None:
        """Writes in-memory strategies to the active cache or deletes it when empty."""
        if loaded_names:
            try:
                portfolio_manager.get_returns_matrix().write_parquet(self.cache_path)
                logger.info(f"Cache updated: {os.path.abspath(self.cache_path)}")
            except Exception as e:
                logger.error(f"Failed to update cache: {e}")
            portfolio_manager.save_lots_cache(self.cache_path)
            return

        self.clear()

    def read_info(self) -> CacheInfo | None:
        """Reads metadata from the active cache file."""
        abs_path = os.path.abspath(self.cache_path)
        if not os.path.exists(self.cache_path):
            return None

        size_bytes = os.path.getsize(self.cache_path)
        size_str = (
            f"{size_bytes / 1_048_576:.1f} MB"
            if size_bytes >= 1_048_576
            else f"{size_bytes / 1024:.1f} KB"
        )
        modified = time.strftime(
            "%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(self.cache_path))
        )

        df = pl.read_parquet(self.cache_path)
        strats = [c for c in df.columns if c != "Horário"]
        if "Horário" in df.columns and strats:
            dates = df["Horário"].drop_nulls()
            date_min = str(dates.min())[:10] if len(dates) > 0 else "N/A"
            date_max = str(dates.max())[:10] if len(dates) > 0 else "N/A"
            date_range = f"{date_min} → {date_max}"
        else:
            date_range = "N/A"

        return CacheInfo(
            path=abs_path,
            size_str=size_str,
            strategy_count=len(strats),
            date_range=date_range,
            modified=modified,
        )

    def clear(self) -> None:
        """Deletes the active cache and sidecar files."""
        if os.path.exists(self.cache_path):
            os.remove(self.cache_path)
            logger.info(f"Cache deleted: {os.path.abspath(self.cache_path)}")
        if os.path.exists(self.active_lots_path):
            os.remove(self.active_lots_path)
            logger.info(f"Lots cache deleted: {os.path.abspath(self.active_lots_path)}")

    def save_snapshot(self, destination: str) -> None:
        """Copies the active cache and sidecar to a destination path."""
        if not os.path.exists(self.cache_path):
            raise FileNotFoundError(os.path.abspath(self.cache_path))

        abs_destination = os.path.abspath(destination)
        os.makedirs(os.path.dirname(abs_destination) or ".", exist_ok=True)
        shutil.copy2(self.cache_path, destination)

        if os.path.exists(self.active_lots_path):
            destination_lots = self.lots_cache_path(destination)
            os.makedirs(os.path.dirname(os.path.abspath(destination_lots)) or ".", exist_ok=True)
            shutil.copy2(self.active_lots_path, destination_lots)

    def load_snapshot(self, source: str) -> tuple[str, str | None]:
        """Loads a snapshot into the active cache location."""
        if not os.path.exists(source):
            raise FileNotFoundError(os.path.abspath(source))

        abs_target = os.path.abspath(self.cache_path)
        os.makedirs(os.path.dirname(abs_target) or ".", exist_ok=True)
        shutil.copy2(source, self.cache_path)

        source_lots = self.lots_cache_path(source)
        loaded_lots_path: str | None = None
        if os.path.exists(source_lots):
            os.makedirs(os.path.dirname(os.path.abspath(self.active_lots_path)) or ".", exist_ok=True)
            shutil.copy2(source_lots, self.active_lots_path)
            loaded_lots_path = os.path.abspath(self.active_lots_path)
        elif os.path.exists(self.active_lots_path):
            os.remove(self.active_lots_path)

        return abs_target, loaded_lots_path

    @classmethod
    def merge_snapshots(
        cls, left: str, right: str, destination: str
    ) -> tuple[list[str], str | None]:
        """Merges two cache snapshots into a destination file."""
        left_df = pl.read_parquet(left)
        right_df = pl.read_parquet(right)
        for label, df in (("left", left_df), ("right", right_df)):
            if "Horário" not in df.columns:
                raise DataError(f"Invalid {label} cache: missing 'Horário' column.")

        left_strategies = [c for c in left_df.columns if c != "Horário"]
        right_strategies = [c for c in right_df.columns if c != "Horário"]
        duplicate_strategies = sorted(set(left_strategies) & set(right_strategies))

        left_unique_columns = [
            "Horário",
            *[name for name in left_strategies if name not in duplicate_strategies],
        ]
        merged_df = (
            left_df.select(left_unique_columns)
            .join(right_df, on="Horário", how="full", coalesce=True)
            .sort("Horário")
        )

        abs_destination = os.path.abspath(destination)
        os.makedirs(os.path.dirname(abs_destination) or ".", exist_ok=True)
        merged_df.write_parquet(destination)

        merged_lots: dict[str, float] = {}
        for source_path in (left, right):
            lots_path = cls.lots_cache_path(source_path)
            if not os.path.exists(lots_path):
                continue
            with open(lots_path, encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, dict):
                merged_lots.update(
                    {
                        str(k): round(float(v), 2)
                        for k, v in payload.items()
                        if k != "__meta__" and isinstance(v, (int, float))
                    }
                )

        destination_lots = cls.lots_cache_path(destination)
        written_lots_path: str | None = None
        if merged_lots:
            with open(destination_lots, "w", encoding="utf-8") as f:
                json.dump(merged_lots, f, indent=2)
            written_lots_path = os.path.abspath(destination_lots)

        return duplicate_strategies, written_lots_path
