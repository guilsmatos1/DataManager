"""
Tests for GeneticEngine
========================
Covers construction, constraint compliance, output format, and basic convergence.
"""

import pandas as pd
import polars as pl
import pytest
from trademachine.portfoliomaster.services.genetic import GeneticEngine
from trademachine.portfoliomaster.services.optimization import BruteForceEngine


def _make_long_df(strategy_data: dict, n_dates: int = 20) -> pl.DataFrame:
    """Builds a long-format DataFrame for GeneticEngine from {name: [profit values]}."""
    import datetime

    base = datetime.datetime(2023, 1, 1)
    dates = [base + datetime.timedelta(days=i) for i in range(n_dates)]
    rows = []
    for name, values in strategy_data.items():
        for dt, val in zip(dates, values, strict=False):
            rows.append({"Horário": dt, "Strategy": name, "Net_Profit": float(val)})
    return pl.from_pandas(pd.DataFrame(rows))


def _make_uncorrelated_strategies(n: int = 8, n_dates: int = 20) -> dict:
    """Returns n strategies with alternating returns designed to be uncorrelated."""
    import random

    rng = random.Random(42)
    data = {}
    for i in range(n):
        # Each strategy has unique pattern to reduce correlation
        values = [
            rng.choice([-5.0, 5.0, 10.0, -3.0]) * (1 + i * 0.1) for _ in range(n_dates)
        ]
        data[f"S{i + 1}"] = values
    return data


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_genetic_engine_initializes():
    """GeneticEngine constructs without errors with minimal data."""
    long_df = _make_long_df({"A": [1.0, 2.0, 3.0], "B": [2.0, -1.0, 1.0]})
    engine = GeneticEngine(long_df, correlation_period="D")
    assert engine.strategy_names == ["A", "B"]
    assert engine.correlation_matrix.shape == (2, 2)


def test_genetic_engine_accepts_precomputed_correlation():
    """GeneticEngine skips correlation computation when matrix is provided."""
    import numpy as np

    long_df = _make_long_df({"A": [1.0, 2.0], "B": [2.0, -1.0]})
    corr = np.array([[1.0, 0.1], [0.1, 1.0]])
    engine = GeneticEngine(long_df, correlation_matrix=corr)
    assert (engine.correlation_matrix == corr).all()


# ---------------------------------------------------------------------------
# Output format
# ---------------------------------------------------------------------------


def test_run_returns_list_of_dicts():
    """run() returns a non-empty list of dicts with required keys."""
    data = _make_uncorrelated_strategies(n=6, n_dates=20)
    long_df = _make_long_df(data)
    engine = GeneticEngine(long_df)
    results = engine.run(
        min_assets=2,
        max_assets=3,
        top_n=3,
        max_corr=0.99,
        population_size=30,
        generations=5,
        enrich_details=False,
    )
    assert isinstance(results, list)
    assert len(results) > 0
    required_keys = {"Combo", "Net_Profit", "RetDD", "Maximum_Drawdown"}
    for r in results:
        assert required_keys.issubset(r.keys()), f"Missing keys in result: {r.keys()}"


def test_run_returns_at_most_top_n():
    """run() never returns more portfolios than top_n."""
    data = _make_uncorrelated_strategies(n=6, n_dates=15)
    long_df = _make_long_df(data)
    engine = GeneticEngine(long_df)
    results = engine.run(
        min_assets=2,
        max_assets=2,
        top_n=3,
        max_corr=0.99,
        population_size=20,
        generations=5,
        enrich_details=False,
    )
    assert len(results) <= 3


# ---------------------------------------------------------------------------
# Constraint compliance
# ---------------------------------------------------------------------------


def test_all_results_respect_min_max_assets():
    """Every returned portfolio has between min_assets and max_assets strategies."""
    data = _make_uncorrelated_strategies(n=7, n_dates=20)
    long_df = _make_long_df(data)
    engine = GeneticEngine(long_df)
    min_a, max_a = 2, 4
    results = engine.run(
        min_assets=min_a,
        max_assets=max_a,
        top_n=5,
        max_corr=0.99,
        population_size=40,
        generations=10,
        enrich_details=False,
    )
    for r in results:
        combo_size = len(r["Combo"])
        assert min_a <= combo_size <= max_a, (
            f"Portfolio size {combo_size} outside [{min_a}, {max_a}]: {r['Combo']}"
        )


def test_all_results_respect_max_correlation():
    """Every returned portfolio satisfies the max pairwise correlation constraint."""
    import numpy as np

    data = _make_uncorrelated_strategies(n=6, n_dates=30)
    long_df = _make_long_df(data)
    engine = GeneticEngine(long_df, correlation_period="D")
    max_corr = 0.99

    results = engine.run(
        min_assets=2,
        max_assets=3,
        top_n=5,
        max_corr=max_corr,
        population_size=40,
        generations=10,
        enrich_details=False,
    )

    name_to_idx = {name: i for i, name in enumerate(engine.strategy_names)}
    for r in results:
        selected = [name_to_idx[name] for name in r["Combo"]]
        for i in range(len(selected)):
            for j in range(i + 1, len(selected)):
                val = engine.correlation_matrix[selected[i], selected[j]]
                if not np.isnan(val):
                    assert val <= max_corr + 1e-9, (
                        f"Pair ({r['Combo'][i]}, {r['Combo'][j]}) correlation "
                        f"{val:.4f} exceeds max_corr={max_corr}"
                    )


def test_combo_strategies_are_unique():
    """No strategy appears twice in the same portfolio."""
    data = _make_uncorrelated_strategies(n=6, n_dates=15)
    long_df = _make_long_df(data)
    engine = GeneticEngine(long_df)
    results = engine.run(
        min_assets=2,
        max_assets=3,
        top_n=5,
        max_corr=0.99,
        population_size=30,
        generations=5,
        enrich_details=False,
    )
    for r in results:
        assert len(set(r["Combo"])) == len(r["Combo"]), (
            f"Duplicate strategy in combo: {r['Combo']}"
        )


# ---------------------------------------------------------------------------
# Metric values
# ---------------------------------------------------------------------------


def test_net_profit_matches_sum_of_returns():
    """Net_Profit in the result equals the sum of all strategy returns in the combo."""
    data = {
        "A": [10.0] * 10,
        "B": [5.0] * 10,
        "C": [-2.0] * 10,
    }
    long_df = _make_long_df(data, n_dates=10)
    engine = GeneticEngine(long_df)
    results = engine.run(
        min_assets=2,
        max_assets=2,
        top_n=5,
        max_corr=0.99,
        population_size=50,
        generations=20,
        enrich_details=False,
    )
    # Find result containing A+B (expected Net_Profit = 150)
    ab_result = next((r for r in results if set(r["Combo"]) == {"A", "B"}), None)
    if ab_result is not None:
        assert abs(ab_result["Net_Profit"] - 150.0) < 1e-6


# ---------------------------------------------------------------------------
# best_portfolios attribute
# ---------------------------------------------------------------------------


def test_best_portfolios_attribute_populated():
    """After run(), engine.best_portfolios matches the return value."""
    data = _make_uncorrelated_strategies(n=5, n_dates=15)
    long_df = _make_long_df(data)
    engine = GeneticEngine(long_df)
    results = engine.run(
        min_assets=2,
        max_assets=2,
        top_n=3,
        max_corr=0.99,
        population_size=20,
        generations=5,
        enrich_details=False,
    )
    assert engine.best_portfolios is results


# ---------------------------------------------------------------------------
# Consistency with BruteForceEngine (small search space)
# ---------------------------------------------------------------------------


def test_genetic_finds_best_portfolio_vs_brute_force():
    """For a small deterministic search space, GA finds the optimal portfolio."""
    # Use non-constant values so correlation is computable (no zero-std strategies).
    # A+B has the highest combined net profit and low correlation.
    data = {
        "A": [10.0, 12.0, 9.0, 11.0, 10.0, 11.0, 10.0, 12.0, 9.0, 11.0],
        "B": [8.0, 7.0, 9.0, 8.0, 7.0, 8.0, 9.0, 7.0, 8.0, 9.0],
        "C": [-5.0, -4.0, -6.0, -5.0, -4.0, -5.0, -6.0, -4.0, -5.0, -6.0],
        "D": [1.0, -1.0, 2.0, -1.0, 1.0, -2.0, 1.0, -1.0, 2.0, -1.0],
    }
    long_df = _make_long_df(data, n_dates=10)

    # BruteForce reference
    bf_engine = BruteForceEngine(long_df, correlation_period="D")
    bf_results = bf_engine.run(min_assets=2, max_assets=2, top_n=1, max_corr=0.99)
    bf_best_combo = set(bf_results[0]["Combo"])

    # Genetic (generous params for small space)
    ga_engine = GeneticEngine(long_df, correlation_period="D")
    ga_results = ga_engine.run(
        min_assets=2,
        max_assets=2,
        top_n=1,
        max_corr=0.99,
        population_size=50,
        generations=30,
        enrich_details=False,
    )
    ga_best_combo = set(ga_results[0]["Combo"])

    assert ga_best_combo == bf_best_combo, (
        f"GA found {ga_best_combo}, brute force found {bf_best_combo}"
    )


# ---------------------------------------------------------------------------
# ensure_detailed_metrics
# ---------------------------------------------------------------------------


def test_ensure_detailed_metrics_adds_total_trades():
    """ensure_detailed_metrics() adds Total_Trades to each portfolio."""
    data = _make_uncorrelated_strategies(n=5, n_dates=15)
    long_df = _make_long_df(data)
    engine = GeneticEngine(long_df)
    engine.run(
        min_assets=2,
        max_assets=2,
        top_n=2,
        max_corr=0.99,
        population_size=20,
        generations=5,
        enrich_details=False,
    )
    assert all("Total_Trades" not in r for r in engine.best_portfolios)
    engine.ensure_detailed_metrics()
    assert all("Total_Trades" in r for r in engine.best_portfolios)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_min_equals_max_assets():
    """min_assets == max_assets works correctly."""
    data = _make_uncorrelated_strategies(n=5, n_dates=10)
    long_df = _make_long_df(data)
    engine = GeneticEngine(long_df)
    results = engine.run(
        min_assets=3,
        max_assets=3,
        top_n=3,
        max_corr=0.99,
        population_size=30,
        generations=5,
        enrich_details=False,
    )
    for r in results:
        assert len(r["Combo"]) == 3


@pytest.mark.parametrize("rank_by", ["RetDD", "NetProfit"])
def test_run_with_different_rank_metrics(rank_by: str):
    """run() completes without error for both supported rank_by values."""
    data = _make_uncorrelated_strategies(n=5, n_dates=10)
    long_df = _make_long_df(data)
    engine = GeneticEngine(long_df)
    results = engine.run(
        min_assets=2,
        max_assets=2,
        top_n=2,
        max_corr=0.99,
        rank_by=rank_by,
        population_size=20,
        generations=5,
        enrich_details=False,
    )
    assert isinstance(results, list)
