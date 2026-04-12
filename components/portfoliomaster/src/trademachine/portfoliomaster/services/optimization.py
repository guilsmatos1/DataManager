import heapq
import itertools
import logging
import math
import multiprocessing
import os
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd
import polars as pl
from tqdm import tqdm
from trademachine.core.logger import LOGGER_NAME
from trademachine.portfoliomaster.core.constants import MT5_TIMESTAMP_FORMAT
from trademachine.portfoliomaster.services.metrics import calculate_metrics_from_deals
from trademachine.portfoliomaster.services.portfolio import PortfolioManager

logger = logging.getLogger(LOGGER_NAME)

# Column indices in the metrics matrix returned by compute_batch_performance
METRIC_IDX_NET_PROFIT = 0
METRIC_IDX_MAX_DRAWDOWN = 1
METRIC_IDX_RET_DD = 2

# Batch sizes tuned for memory/speed on typical hardware (16 GB RAM).
# CORRELATION: 10 000 combos × ~100 strategies × 4 bytes (int32) ≈ 4 MB per chunk.
# MATRIX: 1 000 combos × ~100 strategies × N timestamps × 8 bytes (float64).
#   At 10 000 timestamps that is ~800 MB — reduce if OOM errors occur.
CORRELATION_FILTER_BATCH_SIZE = 10000
MATRIX_ALGEBRA_BATCH_SIZE = 1000


@dataclass
class BenchmarkResult:
    total_combinations: int
    processed_combinations: int
    valid_combinations: int
    discarded_combinations: int
    elapsed_seconds: float
    combinations_per_second: float
    estimated_combinations_in_target: int
    estimated_completion_seconds: float | None
    completed_search: bool
    sample_seconds: float
    target_seconds: float
    num_workers: int


def compute_batch_performance(returns_matrix: np.ndarray) -> np.ndarray:
    """
    Computes Profit, Maximum Drawdown, and RetDD for a batch of portfolios.
    Optimized for QA consistency using float64 and in-place operations.
    Always uses 100% of the provided data.
    """
    profits = np.sum(returns_matrix, axis=0, dtype=np.float64)

    equity_matrix = np.cumsum(returns_matrix, axis=0)

    historical_peaks = np.maximum.accumulate(equity_matrix, axis=0)
    historical_peaks = np.maximum(historical_peaks, 0.0)
    max_drawdowns = np.max(historical_peaks - equity_matrix, axis=0)

    ret_dd_values = np.divide(
        profits, max_drawdowns, out=np.zeros_like(profits), where=max_drawdowns != 0
    )

    return np.stack([profits, max_drawdowns, ret_dd_values], axis=1)


# ---------------------------------------------------------------------------
# Module-level functions: picklable by multiprocessing workers
# ---------------------------------------------------------------------------


def _choose_prefix_len(num_strategies: int, num_assets: int, num_workers: int) -> int:
    """Returns the smallest prefix length that yields >= num_workers*100 tasks.

    Number of valid prefixes of length p = C(num_strategies - num_assets + p, p).
    More tasks → finer work-stealing → higher core utilization.
    """
    target = num_workers * 100
    for p in range(1, num_assets):
        num_tasks = math.comb(num_strategies - num_assets + p, p)
        if num_tasks >= target:
            return p
    return max(1, num_assets - 1)


def _enumerate_prefixes(num_strategies: int, num_assets: int, prefix_len: int):
    """Yields all valid combination prefixes of length prefix_len.

    A prefix (a0,...,a_{p-1}) is valid when there are enough remaining
    indices to complete the k-combination:
      num_strategies - 1 - a_{p-1} >= num_assets - prefix_len
    """
    max_last = num_strategies - num_assets + prefix_len - 1
    for prefix in itertools.combinations(range(num_strategies), prefix_len):
        if prefix[-1] <= max_last:
            yield prefix


def _generate_combos_for_prefix(num_strategies: int, num_assets: int, prefix: tuple):
    """Yields all k-combinations of range(num_strategies) that start with prefix."""
    remaining = num_assets - len(prefix)
    if remaining == 0:
        yield prefix
        return
    for rest in itertools.combinations(
        range(prefix[-1] + 1, num_strategies), remaining
    ):
        yield prefix + rest


def _filter_combos_standalone(
    combo_generator, correlation_matrix: np.ndarray, batch_size: int, max_corr: float
) -> tuple[list[tuple[int, ...]], int]:
    """Draws from combo_generator until batch_size valid combos are collected
    or the generator is exhausted. Returns (valid_combos, num_discarded)."""
    valid_combos: list[tuple[int, ...]] = []
    total_discarded = 0
    chunk_size = batch_size * 5

    while len(valid_combos) < batch_size:
        chunk = list(itertools.islice(combo_generator, chunk_size))
        if not chunk:
            break

        if len(chunk[0]) < 2:
            valid_combos.extend(chunk)
            continue

        combos_array = np.array(chunk, dtype=np.int32)
        num_assets_in_chunk = combos_array.shape[1]
        # Use max pairwise correlation, not mean. Industry standard: each
        # pair of strategies must be independently diversified. A high-
        # correlation pair (e.g. 0.47) is a real risk regardless of how
        # low the other pairs are — they will co-drawdown in tail events.
        max_pair_correlations = np.full(len(chunk), -np.inf, dtype=np.float64)

        for i in range(num_assets_in_chunk):
            for j in range(i + 1, num_assets_in_chunk):
                pair_corr = correlation_matrix[combos_array[:, i], combos_array[:, j]]
                np.maximum(max_pair_correlations, pair_corr, out=max_pair_correlations)

        passes_filter = max_pair_correlations <= max_corr
        filtered_chunk = [
            chunk[idx] for idx, is_valid in enumerate(passes_filter) if is_valid
        ]

        total_discarded += len(chunk) - len(filtered_chunk)
        # Extend with all filtered combos — truncating here would silently
        # discard valid combinations already consumed from the generator.
        valid_combos.extend(filtered_chunk)

    return valid_combos, total_discarded


def _process_batch_standalone(
    combo_batch: list[tuple[int, ...]],
    trade_matrix: np.ndarray,
    num_strategies: int,
    strategy_names: list[str],
    top_heap: list,
    top_n: int,
    sort_metric_index: int,
    heap_counter,
    min_metric: float = 0.0,
):
    """Computes metrics for a batch of combos and updates the top-N heap."""
    num_combos = len(combo_batch)
    strategy_mask = np.zeros((num_strategies, num_combos), dtype=np.float64)
    for combo_position, strategy_indices in enumerate(combo_batch):
        strategy_mask[list(strategy_indices), combo_position] = 1.0

    batch_returns = trade_matrix @ strategy_mask
    metrics_matrix = compute_batch_performance(batch_returns)

    for combo_idx in range(num_combos):
        metric_value = float(metrics_matrix[combo_idx, sort_metric_index])
        if metric_value < min_metric:
            continue
        if len(top_heap) < top_n or metric_value > top_heap[0][0]:
            result = {
                "Combo": tuple(strategy_names[idx] for idx in combo_batch[combo_idx]),
                "Net_Profit": float(metrics_matrix[combo_idx, METRIC_IDX_NET_PROFIT]),
                "RetDD": float(metrics_matrix[combo_idx, METRIC_IDX_RET_DD]),
                "Maximum_Drawdown": float(
                    metrics_matrix[combo_idx, METRIC_IDX_MAX_DRAWDOWN]
                ),
            }
            tiebreaker = next(heap_counter)
            if len(top_heap) < top_n:
                heapq.heappush(top_heap, (metric_value, tiebreaker, result))
            else:
                heapq.heapreplace(top_heap, (metric_value, tiebreaker, result))

    del batch_returns, metrics_matrix, strategy_mask


def _worker_process_partition(args: tuple) -> tuple[list[tuple[float, dict]], int]:
    """Worker: processes a partition of combinations and returns local top-N heap.

    Runs in a separate process. All data is passed via args (picklable).
    Returns (heap_items, total_processed) where heap_items is a list of
    (metric_value, result_dict) pairs representing the worker's local top-N.
    """
    (
        trade_matrix,
        correlation_matrix,
        strategy_names,
        num_strategies,
        num_assets,
        prefix,
        top_n,
        sort_metric_index,
        max_corr,
        min_metric,
    ) = args

    local_heap: list = []
    heap_counter = itertools.count()
    total_processed = 0

    combo_gen = _generate_combos_for_prefix(num_strategies, num_assets, prefix)

    running = True
    while running:
        valid_combos, discarded = _filter_combos_standalone(
            combo_gen, correlation_matrix, CORRELATION_FILTER_BATCH_SIZE, max_corr
        )
        total_processed += discarded

        if not valid_combos:
            running = False
            continue

        for batch_start in range(0, len(valid_combos), MATRIX_ALGEBRA_BATCH_SIZE):
            batch_slice = valid_combos[
                batch_start : batch_start + MATRIX_ALGEBRA_BATCH_SIZE
            ]
            _process_batch_standalone(
                batch_slice,
                trade_matrix,
                num_strategies,
                strategy_names,
                local_heap,
                top_n,
                sort_metric_index,
                heap_counter,
                min_metric,
            )
            total_processed += len(batch_slice)

    # Strip the tiebreaker (index 1) before returning — not needed for merge
    heap_items = [(item[0], item[2]) for item in local_heap]  # vulture: ignore
    return heap_items, total_processed


def _merge_heaps(worker_results: list[tuple[list, int]], top_n: int) -> list[dict]:
    """Merges top-N local heaps from workers into a global top-N ranking.

    Each worker returns at most top_n items. Sorting each small list first and
    using heapq.merge yields O(k*top_n * log k) instead of O(k*top_n * log(k*top_n)).
    """
    sorted_lists = [
        sorted(heap_items, key=lambda x: x[0], reverse=True)
        for heap_items, _ in worker_results
    ]
    merged = heapq.merge(*sorted_lists, key=lambda x: x[0], reverse=True)
    return [item[1] for item in itertools.islice(merged, top_n)]


# ---------------------------------------------------------------------------
# BruteForceEngine
# ---------------------------------------------------------------------------


class BruteForceEngine:
    """
    Optimization engine using optimized matrix multiplication for speed.
    Calculates metrics on 100% of loaded data.
    Supports parallel execution via multiprocessing when num_workers > 1.
    """

    def __init__(
        self,
        all_trades_df: pl.DataFrame,
        correlation_period: str = "D",
        num_workers: int = 0,
        corr_filter_batch_size: int = 10000,
        matrix_algebra_batch_size: int = 1000,
        initial_balance: float = 100_000.0,
        correlation_matrix: np.ndarray | None = None,
    ):
        # Align strategy returns on a 1-hour grid for QA Consistency
        self.all_trades_raw = all_trades_df.sort("Horário")
        self.strategy_names = sorted(self.all_trades_raw["Strategy"].unique().to_list())
        self.corr_filter_batch_size = corr_filter_batch_size
        self.matrix_algebra_batch_size = matrix_algebra_batch_size

        self.wide_trades = (
            self.all_trades_raw.pivot(
                index="Horário",
                on="Strategy",
                values="Net_Profit",
                aggregate_function="sum",
            )
            .fill_null(0.0)
            .sort("Horário")
            .select(
                ["Horário"] + self.strategy_names
            )  # enforce alphabetical column order
        )

        # Pre-compute trade matrix once; reused by run() and run_greedy()
        self.trade_matrix = (
            self.wide_trades.drop("Horário").to_numpy().astype(np.float64)
        )

        self.initial_balance = initial_balance
        self.best_portfolios: list[dict] = []
        self.greedy_history: list[dict] = []

        if correlation_matrix is not None:
            self.correlation_matrix = correlation_matrix
        else:
            self.correlation_matrix = self._compute_correlation(correlation_period)

        # 0 = auto-detect (use all physical CPUs)
        self.num_workers = num_workers if num_workers >= 1 else (os.cpu_count() or 1)

    def _compute_correlation(self, period: str) -> np.ndarray:
        logger.info(f"Computing correlation matrix (Period: {period})...")
        pm = PortfolioManager()
        corr_matrix = pm.compute_periodic_correlation(
            self.all_trades_raw, self.strategy_names, period
        )
        upper = corr_matrix[np.triu_indices_from(corr_matrix, k=1)]
        valid = upper[~np.isnan(upper)]
        if len(valid) > 0:
            logger.info(
                f"Pairwise correlation — min: {valid.min():.3f} | "
                f"max: {valid.max():.3f} | mean: {valid.mean():.3f}"
            )
        else:
            logger.info("Pairwise correlation — no valid pairs (single strategy?).")
        return corr_matrix  # type: ignore[no-any-return]

    def _filter_combos_by_correlation(
        self, combo_generator, batch_size: int, max_corr: float
    ) -> tuple[list[tuple[int, ...]], int]:
        """Wrapper around standalone filter using instance correlation matrix."""
        return _filter_combos_standalone(
            combo_generator, self.correlation_matrix, batch_size, max_corr
        )

    def run(
        self,
        min_assets: int = 5,
        max_assets: int = 5,
        top_n: int = 10,
        rank_by: str = "RetDD",
        max_corr: float = 0.3,
        min_metric: float = 0.0,
    ):
        """Executes trade-by-trade brute force optimization on the entire dataset."""
        trade_matrix = self.trade_matrix
        num_strategies = len(self.strategy_names)
        total_combos = sum(
            math.comb(num_strategies, k) for k in range(min_assets, max_assets + 1)
        )
        sort_metric_index = (
            METRIC_IDX_RET_DD if rank_by == "RetDD" else METRIC_IDX_NET_PROFIT
        )

        filter_info = f" | Min {rank_by}: {min_metric}" if min_metric > 0 else ""
        logger.info(
            f"Optimization: {total_combos:,} variations | Rank by: {rank_by}"
            f"{filter_info} | Workers: {self.num_workers}"
        )

        if self.num_workers == 1:
            winners = self._run_single_process_loop(
                trade_matrix,
                num_strategies,
                min_assets,
                max_assets,
                top_n,
                total_combos,
                sort_metric_index,
                max_corr,
                min_metric,
            )
        else:
            winners = self._run_multiprocess_loop(
                trade_matrix,
                num_strategies,
                min_assets,
                max_assets,
                top_n,
                total_combos,
                sort_metric_index,
                max_corr,
                min_metric,
            )

        logger.info("Calculating detailed metrics for top portfolios...")
        self._enrich_with_detailed_metrics(winners)

        self.best_portfolios = winners
        return self.best_portfolios

    def _run_single_process_loop(
        self,
        trade_matrix: np.ndarray,
        num_strategies: int,
        min_assets: int,
        max_assets: int,
        top_n: int,
        total_combos: int,
        sort_metric_index: int,
        max_corr: float,
        min_metric: float = 0.0,
    ) -> list[dict]:
        """Single-process path: original sequential loop."""
        top_heap: list[tuple] = []
        heap_counter = itertools.count()
        start_time = time.time()

        progress_bar = tqdm(total=total_combos, desc="Optimizing", unit="portfolio")

        for num_assets in range(min_assets, max_assets + 1):
            combo_generator = itertools.combinations(range(num_strategies), num_assets)
            while True:
                valid_combos, discarded_count = self._filter_combos_by_correlation(
                    combo_generator, self.corr_filter_batch_size, max_corr
                )

                if not valid_combos:
                    progress_bar.update(discarded_count)
                    break

                for batch_start in range(
                    0, len(valid_combos), self.matrix_algebra_batch_size
                ):
                    batch_slice = valid_combos[
                        batch_start : batch_start + self.matrix_algebra_batch_size
                    ]
                    _process_batch_standalone(
                        batch_slice,
                        trade_matrix,
                        num_strategies,
                        self.strategy_names,
                        top_heap,
                        top_n,
                        sort_metric_index,
                        heap_counter,
                        min_metric,
                    )
                    progress_bar.update(len(batch_slice))

                progress_bar.update(discarded_count)

        progress_bar.close()
        logger.info(f"Finished in {time.time() - start_time:.2f}s.")

        return [item[2] for item in sorted(top_heap, key=lambda x: x[0], reverse=True)]

    def _run_multiprocess_loop(
        self,
        trade_matrix: np.ndarray,
        num_strategies: int,
        min_assets: int,
        max_assets: int,
        top_n: int,
        total_combos: int,
        sort_metric_index: int,
        max_corr: float,
        min_metric: float = 0.0,
    ) -> list[dict]:
        """Multi-process path: partitions combinations across workers."""
        start_time = time.time()
        all_worker_results: list[tuple[list, int]] = []

        progress_bar = tqdm(total=total_combos, desc="Optimizing", unit="portfolio")

        with multiprocessing.Pool(processes=self.num_workers) as pool:
            for num_assets in range(min_assets, max_assets + 1):
                # Adaptive prefix length: choose the smallest p such that
                # C(n-k+p, p) >= num_workers * 100 tasks. More tasks than
                # workers enables work-stealing — idle workers pick up new
                # tasks immediately instead of waiting for slow peers.
                prefix_len = _choose_prefix_len(
                    num_strategies, num_assets, self.num_workers
                )
                all_prefixes = list(
                    _enumerate_prefixes(num_strategies, num_assets, prefix_len)
                )
                logger.info(
                    f"k={num_assets}: {len(all_prefixes):,} tasks "
                    f"(prefix_len={prefix_len}) across {self.num_workers} workers"
                )

                args_list = [
                    (
                        trade_matrix,
                        self.correlation_matrix,
                        self.strategy_names,
                        num_strategies,
                        num_assets,
                        prefix,
                        top_n,
                        sort_metric_index,
                        max_corr,
                        min_metric,
                    )
                    for prefix in all_prefixes
                ]

                # chunksize=1: each idle worker picks exactly one task at a time,
                # maximizing work-stealing and minimizing end-of-batch idle time.
                for worker_result in pool.imap_unordered(
                    _worker_process_partition, args_list, chunksize=1
                ):
                    _, processed = worker_result
                    all_worker_results.append(worker_result)
                    progress_bar.update(processed)

        progress_bar.close()
        logger.info(f"Finished in {time.time() - start_time:.2f}s.")

        return _merge_heaps(all_worker_results, top_n)

    def _enrich_with_detailed_metrics(self, portfolios: list[dict]):
        """Calculates full MT5-style metrics for each portfolio and merges them in-place."""
        for portfolio_result in tqdm(portfolios, desc="Finalizing"):
            combo = portfolio_result["Combo"]
            deals_df = self._build_portfolio_deals_df(combo)
            detailed_metrics = calculate_metrics_from_deals(deals_df)
            for key, value in detailed_metrics.items():
                # Preserve the higher-precision values already computed
                if key not in ("Net_Profit", "RetDD", "Maximum_Drawdown"):
                    portfolio_result[key] = value

    def _build_portfolio_deals_df(self, combo: tuple[str, ...]) -> pd.DataFrame:
        """Constructs a mock MT5 deals DataFrame for the combined portfolio trades."""
        initial_balance = self.initial_balance

        portfolio_trades = self.all_trades_raw.filter(
            pl.col("Strategy").is_in(combo)
        ).sort("Horário")

        if not portfolio_trades.is_empty():
            first_timestamp = portfolio_trades["Horário"][0].strftime(
                MT5_TIMESTAMP_FORMAT
            )
        else:
            first_timestamp = "2000.01.01 00:00:00"

        mock_data = {
            "Horário": [first_timestamp],
            "Tipo": ["balance"],
            "Direção": [""],
            "Lucro": [0.0],
            "Comissão": [0.0],
            "Swap": [0.0],
            "Saldo": [initial_balance],
        }

        if not portfolio_trades.is_empty():
            num_trades = len(portfolio_trades)
            timestamps = (
                portfolio_trades["Horário"].dt.strftime(MT5_TIMESTAMP_FORMAT).to_list()
            )
            profits = portfolio_trades["Net_Profit"].to_list()
            cumulative_balance = (
                portfolio_trades["Net_Profit"].cum_sum() + initial_balance
            ).to_list()

            mock_data["Horário"].extend(timestamps)
            mock_data["Tipo"].extend(["buy"] * num_trades)
            mock_data["Direção"].extend(["out"] * num_trades)
            mock_data["Lucro"].extend(profits)
            zeros = [0.0] * num_trades
            mock_data["Comissão"].extend(zeros)
            mock_data["Swap"].extend(zeros)
            mock_data["Saldo"].extend(cumulative_balance)

        return pd.DataFrame(mock_data)

    def run_greedy(
        self,
        seed_combo: tuple[str, ...],
        rank_by: str = "RetDD",
        max_corr: float = 0.3,
    ) -> list[dict]:
        """Greedy forward-selection: expands seed_combo one strategy at a time
        as long as the ranking metric strictly improves and correlation holds."""
        sort_metric_index = (
            METRIC_IDX_RET_DD if rank_by == "RetDD" else METRIC_IDX_NET_PROFIT
        )
        metric_label = rank_by

        trade_matrix = self.trade_matrix
        name_to_idx = {name: idx for idx, name in enumerate(self.strategy_names)}

        current_indices = [name_to_idx[name] for name in seed_combo]
        current_set = set(current_indices)
        available = np.array(
            [idx for idx in range(len(self.strategy_names)) if idx not in current_set],
            dtype=np.int64,
        )

        base_returns = trade_matrix[:, current_indices].sum(axis=1)
        seed_metrics = compute_batch_performance(base_returns[:, None])
        current_metric = float(seed_metrics[0, sort_metric_index])

        self.greedy_history = []
        logger.info(
            f"Greedy forward-selection started | seed: {len(current_indices)} strategies"
            f" | {metric_label}: {current_metric:.2f}"
        )

        step = 0
        while len(available) > 0:
            # Vectorized correlation filter: max pairwise corr with current portfolio
            corr_with_current = self.correlation_matrix[
                np.ix_(available, np.array(current_indices))
            ]
            max_corr_per_candidate = corr_with_current.max(axis=1)
            valid_mask = max_corr_per_candidate <= max_corr
            valid_candidates = available[valid_mask]

            if len(valid_candidates) == 0:
                logger.info("Greedy: no candidates pass correlation filter. Stopping.")
                break

            # Vectorized metric computation for all valid candidates in one batch
            candidate_returns = (
                base_returns[:, None] + trade_matrix[:, valid_candidates]
            )
            metrics = compute_batch_performance(candidate_returns)
            best_local_idx = int(np.argmax(metrics[:, sort_metric_index]))
            best_metric = float(metrics[best_local_idx, sort_metric_index])

            if best_metric <= current_metric:
                logger.info(
                    f"Greedy: best candidate ({best_metric:.4f}) "
                    f"<= current ({current_metric:.4f}). Stopping."
                )
                break

            best_global_idx = int(valid_candidates[best_local_idx])
            added_name = self.strategy_names[best_global_idx]
            step += 1

            self.greedy_history.append(
                {
                    "step": step,
                    "added_strategy": added_name,
                    "metric_before": current_metric,
                    "metric_after": best_metric,
                }
            )
            logger.info(
                f"Greedy step {step}: +'{added_name}' | "
                f"{metric_label}: {current_metric:.4f} → {best_metric:.4f}"
            )

            current_indices.append(best_global_idx)
            base_returns = base_returns + trade_matrix[:, best_global_idx]
            current_metric = best_metric
            available = available[available != best_global_idx]

        reason = "no further improvement" if step > 0 else "no improvement found"
        print(f"  Final: {len(current_indices)} strategies ({reason})")
        print(f"{'═' * 40}\n")

        final_combo = tuple(self.strategy_names[idx] for idx in current_indices)
        final_metrics = compute_batch_performance(base_returns[:, None])
        final_result = {
            "Combo": final_combo,
            "Net_Profit": float(final_metrics[0, METRIC_IDX_NET_PROFIT]),
            "RetDD": float(final_metrics[0, METRIC_IDX_RET_DD]),
            "Maximum_Drawdown": float(final_metrics[0, METRIC_IDX_MAX_DRAWDOWN]),
        }

        logger.info("Calculating detailed metrics for greedy portfolio...")
        self._enrich_with_detailed_metrics([final_result])
        self.best_portfolios = [final_result]
        return self.best_portfolios

    def print_results(self, _columns: list[str] | None = None):
        """Prints the top optimization results to the terminal in a concise table."""
        if not self.best_portfolios:
            return

        # User requested specific columns and labels for terminal output:
        # Rank, Combo, # of trades, Net profit, RetDD.
        # We use a fixed column set for the terminal to ensure brevity,
        # ignoring 'columns' (which usually contains the full set from config.json).
        print("\n🏆 TOP PORTFOLIOS:")

        header = f"{'Rank':<4} | {'Combo':<45} | {'# of Trades':>12} | {'Net Profit':>12} | {'RetDD':>8}"
        print("=" * len(header))
        print(header)
        print("-" * len(header))

        for rank, res in enumerate(self.best_portfolios, 1):
            # Format Combo list as a string
            combo_str = ", ".join(res["Combo"])
            if len(combo_str) > 45:
                combo_str = combo_str[:42] + "..."

            row = (
                f"{rank:<4} | "
                f"{combo_str:<45} | "
                f"{res.get('Total_Trades', 0):>12} | "
                f"{res.get('Net_Profit', 0.0):>12.2f} | "
                f"{res.get('RetDD', 0.0):>8.2f}"
            )
            print(row)

        print("=" * len(header))
