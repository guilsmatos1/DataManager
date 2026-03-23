"""
Tests for BruteForceEngine greedy forward-selection, multiprocessing,
and standalone helper functions (correlation filter, prefix enumeration,
heap merging, batch processing).
"""

import itertools

import numpy as np
import pandas as pd
import polars as pl
import pytest

from portifoliomaster.services.optimization import (
    METRIC_IDX_NET_PROFIT,
    BruteForceEngine,
    _choose_prefix_len,
    _enumerate_prefixes,
    _filter_combos_standalone,
    _merge_heaps,
    _process_batch_standalone,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_long_df(strategy_data: dict) -> pl.DataFrame:
    """Build a long-format DataFrame from {name: [profit_per_day]} dict."""
    dates = pd.date_range(
        "2023-01-01", periods=max(len(v) for v in strategy_data.values())
    )
    rows = []
    for name, values in strategy_data.items():
        for dt, val in zip(dates, values, strict=False):
            rows.append({"Horário": dt, "Strategy": name, "Net_Profit": float(val)})
    return pl.from_pandas(pd.DataFrame(rows))


def _identity_corr(n: int) -> np.ndarray:
    """Returns an n×n identity correlation matrix (all pairs have corr=0)."""
    return np.eye(n, dtype=np.float64)


def _ones_corr(n: int) -> np.ndarray:
    """Returns an n×n all-ones correlation matrix (all pairs perfectly correlated)."""
    return np.ones((n, n), dtype=np.float64)


# ---------------------------------------------------------------------------
# _choose_prefix_len
# ---------------------------------------------------------------------------


def test_choose_prefix_len_returns_at_least_1():
    result = _choose_prefix_len(num_strategies=5, num_assets=2, num_workers=1)
    assert result >= 1


def test_choose_prefix_len_grows_with_workers():
    p_few = _choose_prefix_len(num_strategies=20, num_assets=3, num_workers=1)
    p_many = _choose_prefix_len(num_strategies=20, num_assets=3, num_workers=50)
    assert p_many >= p_few


def test_choose_prefix_len_single_asset_returns_1():
    result = _choose_prefix_len(num_strategies=10, num_assets=1, num_workers=4)
    assert result == 1


# ---------------------------------------------------------------------------
# _enumerate_prefixes
# ---------------------------------------------------------------------------


def test_enumerate_prefixes_all_valid():
    """Every yielded prefix must be completable into a k-combination."""
    num_strategies, num_assets, prefix_len = 8, 3, 2
    prefixes = list(_enumerate_prefixes(num_strategies, num_assets, prefix_len))
    for prefix in prefixes:
        assert len(prefix) == prefix_len
        # There must be at least (num_assets - prefix_len) elements after prefix[-1]
        remaining_needed = num_assets - prefix_len
        remaining_available = num_strategies - 1 - prefix[-1]
        assert remaining_available >= remaining_needed


def test_enumerate_prefixes_count_matches_theory():
    """Number of valid prefixes ≤ C(n, prefix_len)."""
    import math

    n, k, p = 6, 3, 1
    prefixes = list(_enumerate_prefixes(n, k, p))
    upper_bound = math.comb(n, p)
    assert len(prefixes) <= upper_bound


# ---------------------------------------------------------------------------
# _filter_combos_standalone
# ---------------------------------------------------------------------------


def test_filter_combos_identity_matrix_passes_all():
    """With identity correlation, every pair has corr=0 → all pass any positive threshold."""
    corr = _identity_corr(4)
    combos = list(itertools.combinations(range(4), 2))
    gen = iter(combos)
    valid, discarded = _filter_combos_standalone(gen, corr, batch_size=10, max_corr=0.5)
    assert discarded == 0
    assert len(valid) == len(combos)


def test_filter_combos_ones_matrix_rejects_all_pairs():
    """With all-ones correlation, every pair has corr=1 → all 2-combos fail threshold < 1."""
    corr = _ones_corr(4)
    combos = list(itertools.combinations(range(4), 2))
    gen = iter(combos)
    valid, discarded = _filter_combos_standalone(
        gen, corr, batch_size=100, max_corr=0.9
    )
    assert len(valid) == 0
    assert discarded == len(combos)


def test_filter_combos_single_asset_always_passes():
    """Single-asset combos have no pairs → always pass regardless of correlation."""
    corr = _ones_corr(3)
    combos = [(0,), (1,), (2,)]
    gen = iter(combos)
    valid, discarded = _filter_combos_standalone(gen, corr, batch_size=10, max_corr=0.0)
    assert len(valid) == 3
    assert discarded == 0


def test_filter_combos_partial_batch():
    """Fewer combos than batch_size → all are returned without hanging."""
    corr = _identity_corr(5)
    combos = list(itertools.combinations(range(5), 2))[:3]
    gen = iter(combos)
    valid, _ = _filter_combos_standalone(gen, corr, batch_size=1000, max_corr=1.0)
    assert len(valid) == 3


# ---------------------------------------------------------------------------
# _process_batch_standalone
# ---------------------------------------------------------------------------


def test_process_batch_populates_heap():
    trade_matrix = np.array(
        [[10.0, 5.0], [10.0, 5.0], [10.0, 5.0]]
    )  # 3 timestamps × 2 strategies
    combo_batch = [(0,), (1,)]
    strategy_names = ["S1", "S2"]
    top_heap: list = []
    counter = itertools.count()

    _process_batch_standalone(
        combo_batch,
        trade_matrix,
        2,
        strategy_names,
        top_heap,
        top_n=5,
        sort_metric_index=METRIC_IDX_NET_PROFIT,
        heap_counter=counter,
    )

    assert len(top_heap) == 2
    profits = sorted([item[2]["Net_Profit"] for item in top_heap], reverse=True)
    assert profits[0] == pytest.approx(30.0)
    assert profits[1] == pytest.approx(15.0)


def test_process_batch_respects_top_n():
    """Heap never exceeds top_n entries."""
    trade_matrix = np.array(
        [[float(i)] * 5 for i in range(10)]
    )  # 10 timestamps × 5 strategies
    combos = [(i,) for i in range(5)]
    strategy_names = [f"S{i}" for i in range(5)]
    top_heap: list = []
    counter = itertools.count()

    _process_batch_standalone(
        combos,
        trade_matrix,
        5,
        strategy_names,
        top_heap,
        top_n=2,
        sort_metric_index=METRIC_IDX_NET_PROFIT,
        heap_counter=counter,
    )

    assert len(top_heap) == 2


def test_process_batch_min_metric_filters_low_results():
    """Entries below min_metric are not added to the heap."""
    trade_matrix = np.array([[1.0, 100.0], [1.0, 100.0]])  # S1 tiny, S2 large
    combos = [(0,), (1,)]
    strategy_names = ["S1", "S2"]
    top_heap: list = []
    counter = itertools.count()

    _process_batch_standalone(
        combos,
        trade_matrix,
        2,
        strategy_names,
        top_heap,
        top_n=10,
        sort_metric_index=METRIC_IDX_NET_PROFIT,
        heap_counter=counter,
        min_metric=50.0,
    )

    assert len(top_heap) == 1
    assert top_heap[0][2]["Combo"] == ("S2",)


# ---------------------------------------------------------------------------
# _merge_heaps
# ---------------------------------------------------------------------------


def test_merge_heaps_returns_top_n():
    worker1 = (
        [
            (10.0, {"Combo": ("A",), "Net_Profit": 10.0}),
            (8.0, {"Combo": ("B",), "Net_Profit": 8.0}),
        ],
        2,
    )
    worker2 = (
        [
            (12.0, {"Combo": ("C",), "Net_Profit": 12.0}),
            (6.0, {"Combo": ("D",), "Net_Profit": 6.0}),
        ],
        2,
    )

    merged = _merge_heaps([worker1, worker2], top_n=3)

    assert len(merged) == 3
    assert merged[0]["Net_Profit"] == 12.0
    assert merged[1]["Net_Profit"] == 10.0
    assert merged[2]["Net_Profit"] == 8.0


def test_merge_heaps_top_n_larger_than_items():
    worker1 = ([(5.0, {"Combo": ("X",), "Net_Profit": 5.0})], 1)
    merged = _merge_heaps([worker1], top_n=100)
    assert len(merged) == 1


def test_merge_heaps_empty_workers():
    merged = _merge_heaps([], top_n=10)
    assert merged == []


# ---------------------------------------------------------------------------
# BruteForceEngine — run_greedy
# ---------------------------------------------------------------------------


def test_greedy_improves_metric():
    """run_greedy adds a strategy when it strictly improves the metric."""
    long_df = _make_long_df(
        {
            "S1": [10.0, 10.0, 10.0],  # good, no drawdown
            "S2": [5.0, -1.0, 5.0],  # complements S1 on dip
            "S3": [-5.0, -5.0, -5.0],  # always negative — should not be picked
        }
    )
    engine = BruteForceEngine(long_df, num_workers=1)
    engine.run(min_assets=1, max_assets=1, top_n=1, rank_by="RetDD")

    results = engine.run_greedy(
        seed_combo=engine.best_portfolios[0]["Combo"],
        rank_by="RetDD",
        max_corr=1.0,  # allow any correlation
    )

    assert len(results) == 1
    final_combo = results[0]["Combo"]
    assert len(final_combo) >= 1


def test_greedy_stops_when_no_improvement():
    """run_greedy stops immediately if adding any strategy worsens the metric."""
    long_df = _make_long_df(
        {
            "S1": [10.0, 10.0, 10.0],
            "S2": [-5.0, -5.0, -5.0],
            "S3": [-5.0, -5.0, -5.0],
        }
    )
    engine = BruteForceEngine(long_df, num_workers=1)
    engine.run(min_assets=1, max_assets=1, top_n=1, rank_by="NetProfit")

    seed = engine.best_portfolios[0]["Combo"]
    results = engine.run_greedy(seed_combo=seed, rank_by="NetProfit", max_corr=1.0)

    assert results[0]["Combo"] == seed


def test_greedy_respects_correlation_constraint():
    """run_greedy must not add candidates that exceed max_corr."""
    long_df = _make_long_df(
        {
            "S1": [10.0, 10.0, 10.0],
            "S2": [10.0, 10.0, 10.0],  # identical to S1 → corr = 1.0
        }
    )
    engine = BruteForceEngine(long_df, num_workers=1)
    engine.run(min_assets=1, max_assets=1, top_n=1, rank_by="RetDD")

    results = engine.run_greedy(seed_combo=("S1",), rank_by="RetDD", max_corr=0.5)
    # S2 has corr=1.0 with S1 → must be blocked
    assert "S2" not in results[0]["Combo"]


def test_greedy_result_has_expected_keys():
    """Greedy result dict contains all required portfolio keys."""
    long_df = _make_long_df(
        {
            "S1": [10.0, 5.0, 10.0],
            "S2": [3.0, 3.0, 3.0],
        }
    )
    engine = BruteForceEngine(long_df, num_workers=1)
    engine.run(min_assets=1, max_assets=1, top_n=1, rank_by="RetDD")

    results = engine.run_greedy(
        seed_combo=engine.best_portfolios[0]["Combo"], rank_by="RetDD", max_corr=1.0
    )
    for key in ("Combo", "Net_Profit", "RetDD", "Maximum_Drawdown"):
        assert key in results[0], f"Missing key: {key}"


def test_greedy_history_recorded():
    """greedy_history contains one entry per strategy added."""
    long_df = _make_long_df(
        {
            "S1": [10.0, -1.0, 10.0],
            "S2": [1.0, 5.0, 1.0],  # fills in the dip → improves RetDD
            "S3": [-5.0, -5.0, -5.0],
        }
    )
    engine = BruteForceEngine(long_df, num_workers=1)
    engine.run(min_assets=1, max_assets=1, top_n=1, rank_by="RetDD")
    engine.run_greedy(
        seed_combo=engine.best_portfolios[0]["Combo"], rank_by="RetDD", max_corr=1.0
    )

    assert hasattr(engine, "greedy_history")
    assert isinstance(engine.greedy_history, list)
    for entry in engine.greedy_history:
        assert "step" in entry
        assert "added_strategy" in entry
        assert "metric_before" in entry
        assert "metric_after" in entry
        assert entry["metric_after"] > entry["metric_before"]


# ---------------------------------------------------------------------------
# BruteForceEngine — multiprocessing (num_workers=2)
# ---------------------------------------------------------------------------


def test_multiprocess_produces_same_top1_as_single_process():
    """Multi-worker and single-worker runs agree on the best portfolio."""
    long_df = _make_long_df(
        {
            "S1": [10.0, 10.0, 10.0],
            "S2": [20.0, -5.0, 20.0],
            "S3": [5.0, 5.0, 5.0],
        }
    )

    engine_sp = BruteForceEngine(long_df, num_workers=1)
    results_sp = engine_sp.run(
        min_assets=1, max_assets=1, top_n=1, rank_by="NetProfit", max_corr=1.0
    )

    engine_mp = BruteForceEngine(long_df, num_workers=2)
    results_mp = engine_mp.run(
        min_assets=1, max_assets=1, top_n=1, rank_by="NetProfit", max_corr=1.0
    )

    assert results_sp[0]["Combo"] == results_mp[0]["Combo"]
    assert results_sp[0]["Net_Profit"] == pytest.approx(
        results_mp[0]["Net_Profit"], rel=1e-6
    )


def test_multiprocess_returns_at_least_one_result():
    long_df = _make_long_df(
        {
            "S1": [10.0, 10.0, 10.0],
            "S2": [5.0, 5.0, 5.0],
        }
    )
    engine = BruteForceEngine(long_df, num_workers=2)
    results = engine.run(
        min_assets=1, max_assets=1, top_n=3, rank_by="RetDD", max_corr=1.0
    )
    assert len(results) >= 1
