"""
Cache Commands Module
=====================
Cache management subcommands for PortfolioCLI.
"""

import glob
import logging
import os
from typing import TYPE_CHECKING, Any

from tqdm import tqdm
from trademachine.core.logger import LOGGER_NAME
from trademachine.portfolio_master_cli.loader import _parse_mt5_report_file
from trademachine.portfoliomaster.public import (
    CacheService,
    PortfolioManager,
    ValidationError,
)

logger = logging.getLogger(LOGGER_NAME)


class CacheMixin:
    """Cache management functionality for PortfolioCLI."""

    if TYPE_CHECKING:
        portfolio_manager: Any
        loaded_expert_names: list[str]
        default_config: dict[str, Any]

    def _cache_service(self, cache_path: str | None = None) -> CacheService:
        """Returns a cache service bound to the active cache path."""
        return CacheService(
            cache_path or self.default_config.get("cache_path", "cache.parquet")
        )

    def _persist_current_cache(self) -> None:
        """Writes the current in-memory strategies back to cache and lots sidecar."""
        self._cache_service().persist_manager(
            self.portfolio_manager, self.loaded_expert_names
        )

    def _remove_selected_strategies(self, strategy_names: list[str]) -> list[str]:
        """Removes strategies from memory and persists the updated cache state."""
        removed: list[str] = []
        for name in strategy_names:
            existed = False
            if name in self.portfolio_manager.strategies:
                del self.portfolio_manager.strategies[name]
                existed = True
            if name in self.portfolio_manager.strategy_lots:
                del self.portfolio_manager.strategy_lots[name]
                existed = True
            if name in self.loaded_expert_names:
                self.loaded_expert_names.remove(name)
                existed = True
            if existed:
                removed.append(name)

        if removed:
            self._correlation_cache.clear()  # type: ignore[attr-defined]
            self._persist_current_cache()
            logger.info(
                f"Removed {len(removed)} selected strategies from cache: {', '.join(removed)}"
            )
        return removed

    # ------------------------------------------------------------------
    # cache subcommands
    # ------------------------------------------------------------------

    def cache_info(self, cache_path: str | None = None) -> None:
        """Displays metadata about the current cache file."""
        path = cache_path or self.default_config.get("cache_path", "cache.parquet")
        try:
            info = self._cache_service(path).read_info()
        except Exception as e:
            print(f"Cache exists but could not be read: {e}")
            return
        if info is None:
            print(f"No cache found at: {os.path.abspath(path)}")
            return

        sep = "─" * 44
        print(f"\nCache: {info.path}")
        print(sep)
        print(f"{'Size:':<16}{info.size_str}")
        print(f"{'Strategies:':<16}{info.strategy_count}")
        print(f"{'Date range:':<16}{info.date_range}")
        print(f"{'Modified:':<16}{info.modified}")

    def cache_rebuild(self, directory: str, cache_path: str | None = None) -> None:
        """Forces re-parse of HTML reports and overwrites the cache."""
        if cache_path:
            self.default_config["cache_path"] = cache_path
        self._reset_loaded_state()  # type: ignore[attr-defined]
        self.load_reports(directory_path=directory, use_cache=False)  # type: ignore[attr-defined]

    def cache_clear(self, cache_path: str | None = None) -> None:
        """Deletes the cache file and its lots sidecar."""
        path = cache_path or self.default_config.get("cache_path", "cache.parquet")
        if not os.path.exists(path):
            print(f"Nothing to clear — no cache at: {os.path.abspath(path)}")
            return
        lots_path = CacheService.lots_cache_path(path)
        had_lots = os.path.exists(lots_path)
        try:
            self._cache_service(path).clear()
            print(f"Cache deleted: {os.path.abspath(path)}")
        except Exception as e:
            logger.error(f"Failed to delete cache: {e}")
        if not had_lots:
            return
        print(f"Lots cache deleted: {os.path.abspath(lots_path)}")

    def cache_save(self, destination: str, cache_path: str | None = None) -> None:
        """Copies the active cache file and lots sidecar to a target path."""
        source = cache_path or self.default_config.get("cache_path", "cache.parquet")
        abs_destination = os.path.abspath(destination)

        try:
            self._cache_service(source).save_snapshot(destination)
        except FileNotFoundError as e:
            print(f"No cache found to save: {e}")
            return
        print(f"Cache saved to: {abs_destination}")

        source_lots = CacheService.lots_cache_path(source)
        destination_lots = CacheService.lots_cache_path(destination)
        if os.path.exists(source_lots):
            print(f"Lots cache saved to: {os.path.abspath(destination_lots)}")

    def cache_load(self, source: str, cache_path: str | None = None) -> None:
        """Loads a saved cache file into the active cache location and memory."""
        target = cache_path or self.default_config.get("cache_path", "cache.parquet")
        try:
            abs_target, loaded_lots_path = self._cache_service(target).load_snapshot(
                source
            )
        except FileNotFoundError as e:
            print(f"Cache file not found: {e}")
            return
        print(f"Cache loaded to: {abs_target}")

        target_lots = CacheService.lots_cache_path(target)
        if loaded_lots_path is not None:
            print(f"Lots cache loaded to: {loaded_lots_path}")
        elif not os.path.exists(target_lots):
            print(f"Lots cache cleared: {os.path.abspath(target_lots)}")

        self._reset_loaded_state()  # type: ignore[attr-defined]
        try:
            self.loaded_expert_names = self._cache_service(target).load_into_manager(
                self.portfolio_manager
            )
        except Exception as e:
            print(f"Loaded cache is incompatible: {e}")
            self._reset_loaded_state()  # type: ignore[attr-defined]

    def cache_merge(self, left: str, right: str, destination: str) -> None:
        """Merges two saved cache files into a destination file."""
        if (
            len(
                {
                    os.path.abspath(left),
                    os.path.abspath(right),
                    os.path.abspath(destination),
                }
            )
            < 3
        ):
            raise ValidationError(
                "cache merge requires distinct left, right and destination paths."
            )
        abs_destination = os.path.abspath(destination)
        if not os.path.exists(left):
            print(f"Left cache file not found: {os.path.abspath(left)}")
            return
        if not os.path.exists(right):
            print(f"Right cache file not found: {os.path.abspath(right)}")
            return

        try:
            duplicate_strategies, written_lots_path = CacheService.merge_snapshots(
                left, right, destination
            )
        except Exception as e:
            print(str(e))
            return
        print(f"Merged cache saved to: {abs_destination}")
        if written_lots_path is not None:
            print(f"Merged lots cache saved to: {written_lots_path}")

        if duplicate_strategies:
            print(
                "Duplicate strategies overridden from right cache: "
                + ", ".join(duplicate_strategies)
            )

    def cache_list(self, cache_path: str | None = None) -> None:
        """Lists all strategies currently stored in the cache."""
        target = cache_path or self.default_config.get("cache_path", "cache.parquet")

        temp_manager = PortfolioManager()
        try:
            names = self._cache_service(target).load_into_manager(temp_manager)
        except Exception as e:
            print(f"Could not read cache: {e}")
            return

        if not names:
            print(f"No strategies found in cache: {os.path.abspath(target)}")
            return

        orig_manager = self.portfolio_manager
        orig_names = self.loaded_expert_names
        self.portfolio_manager = temp_manager
        self.loaded_expert_names = names
        try:
            self.list_loaded_strategies()  # type: ignore[attr-defined]
        finally:
            self.portfolio_manager = orig_manager
            self.loaded_expert_names = orig_names

    def cache_delete(self, names: list[str], cache_path: str | None = None) -> None:
        """Deletes specific strategies from the cache by name."""
        target = cache_path or self.default_config.get("cache_path", "cache.parquet")

        # Load current cache
        self._reset_loaded_state()  # type: ignore[attr-defined]
        try:
            self.loaded_expert_names = self._cache_service(target).load_into_manager(
                self.portfolio_manager
            )
        except Exception as e:
            print(f"Could not load cache for deletion: {e}")
            return

        removed = self._remove_selected_strategies(names)
        if removed:
            print(
                f"Successfully deleted {len(removed)} strategies: {', '.join(removed)}"
            )
        else:
            print("No matching strategies found in cache to delete.")

    def cache_add(
        self, names: list[str], directory: str, cache_path: str | None = None
    ) -> None:
        """Adds specific strategies by name from a directory to the cache."""
        target = cache_path or self.default_config.get("cache_path", "cache.parquet")

        # Ensure we have the current cache loaded so we append to it
        self._reset_loaded_state()  # type: ignore[attr-defined]
        try:
            self.loaded_expert_names = self._cache_service(target).load_into_manager(
                self.portfolio_manager
            )
        except Exception:
            pass

        if not os.path.exists(directory):
            logger.error(f"Directory '{directory}' does not exist.")
            return

        report_files = sorted(glob.glob(os.path.join(directory, "*.html")))
        if not report_files:
            logger.error(f"No MT5 HTML reports found in '{directory}'.")
            return

        added: list[str] = []
        names_set = set(names)

        for filepath in tqdm(report_files, desc="Searching and Parsing"):
            missing = names_set - set(added)
            if not missing:
                break

            result = _parse_mt5_report_file(filepath)
            if result.get("ok"):
                expert_name = str(result["expert_name"])
                if expert_name in missing:
                    deals_df = result["deals_df"]
                    if self.portfolio_manager.add_strategy(expert_name, deals_df):
                        if expert_name not in self.loaded_expert_names:
                            self.loaded_expert_names.append(expert_name)
                        added.append(expert_name)

        if added:
            self._cache_service(target).persist_manager(
                self.portfolio_manager, self.loaded_expert_names
            )
            print(f"Successfully added {len(added)} strategies: {', '.join(added)}")
        else:
            print(f"No matching strategies found in '{directory}' for the given names.")
