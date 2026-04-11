import numpy as np
import pandas as pd
import polars as pl
from trademachine.portfoliomaster.services.optimization import (
    BruteForceEngine,
    compute_batch_performance,
)
from trademachine.portfoliomaster.services.portfolio import PortfolioManager


def test_compute_batch_performance_profit_and_maxdd():
    """compute_batch_performance correctly calculates Profit and MaxDD."""
    # P1: [10, -5, 10] -> Profit 15, equity [10, 5, 15], MaxDD 5 (peak 10 - min 5)
    # P2: [5, 5, 5]    -> Profit 15, equity [5, 10, 15], MaxDD 0 (never drops)
    returns = np.array([[10, 5], [-5, 5], [10, 5]], dtype=np.float32)

    metrics = compute_batch_performance(returns)

    assert metrics[0, 0] == 15.0  # P1 Profit
    assert metrics[0, 1] == 5.0  # P1 MaxDD
    assert metrics[0, 2] == 3.0  # P1 RetDD = 15/5

    assert metrics[1, 0] == 15.0  # P2 Profit
    assert metrics[1, 1] == 0.0  # P2 MaxDD
    assert metrics[1, 2] == 0.0  # P2 RetDD = 0 (no drawdown)


def test_compute_batch_performance_all_negative():
    """Portfolio with all losses has positive MaxDD equal to total loss depth."""
    returns = np.array([[-10], [-10], [-10]], dtype=np.float32)
    metrics = compute_batch_performance(returns)

    assert metrics[0, 0] == -30.0  # Profit
    assert metrics[0, 1] == 30.0  # MaxDD


def _make_long_df(strategy_data: dict) -> pl.DataFrame:
    """Build a long-format DataFrame suitable for BruteForceEngine from a dict of {name: [values]}."""
    dates = pd.to_datetime(["2023-01-01", "2023-01-02", "2023-01-03"])
    rows = []
    for name, values in strategy_data.items():
        for dt, val in zip(dates, values, strict=False):
            rows.append({"Horário": dt, "Strategy": name, "Net_Profit": val})
    return pl.from_pandas(pd.DataFrame(rows))


def test_engine_run_retdd_ranking():
    """BruteForceEngine ranks portfolios by RetDD descending."""
    long_df = _make_long_df(
        {
            "S1": [10.0, 10.0, 10.0],  # Profit 30, no drawdown → RetDD 0
            "S2": [20.0, -5.0, 20.0],  # Profit 35, MaxDD 5   → RetDD 7
            "S3": [-10.0, -10.0, -10.0],  # Profit -30 (negative)
        }
    )

    engine = BruteForceEngine(long_df)
    results = engine.run(min_assets=1, max_assets=1, top_n=2, rank_by="RetDD")

    assert len(results) == 2
    # S2 has highest RetDD = 35/5 = 7.0
    assert results[0]["Combo"] == ("S2",)
    assert results[1]["Combo"] == ("S1",)


def test_engine_run_netprofit_ranking():
    """BruteForceEngine ranks portfolios by NetProfit descending."""
    long_df = _make_long_df(
        {
            "S1": [10.0, 10.0, 10.0],  # Profit 30
            "S2": [20.0, -5.0, 20.0],  # Profit 35
        }
    )

    engine = BruteForceEngine(long_df)
    results = engine.run(min_assets=1, max_assets=1, top_n=2, rank_by="NetProfit")

    assert len(results) == 2
    assert results[0]["Combo"] == ("S2",)
    assert results[1]["Combo"] == ("S1",)


def test_engine_run_with_real_reports(pt_parser):
    """BruteForceEngine produces valid results using real report data."""
    names = list(pt_parser.deals_by_expert.keys())
    assert len(names) >= 2, "Need at least 2 reports for combination test"

    pm = PortfolioManager()
    for name in names[:6]:
        pm.add_strategy(name, pt_parser.deals_by_expert[name])

    long_df = pm.get_all_trades_long()
    engine = BruteForceEngine(long_df)
    results = engine.run(min_assets=2, max_assets=2, top_n=5, rank_by="RetDD")

    assert len(results) > 0
    for r in results:
        assert len(r["Combo"]) == 2
        assert r["Maximum_Drawdown"] >= 0.0
        assert r["Total_Trades"] > 0


def test_engine_correlation_filter_reduces_results(pt_parser):
    """A tight correlation filter (0.0) returns fewer results than no filter (1.0)."""
    names = list(pt_parser.deals_by_expert.keys())
    assert len(names) >= 3, "Need at least 3 reports"

    pm = PortfolioManager()
    for name in names[:8]:
        pm.add_strategy(name, pt_parser.deals_by_expert[name])

    long_df = pm.get_all_trades_long()

    engine_no_filter = BruteForceEngine(long_df)
    results_all = engine_no_filter.run(
        min_assets=2, max_assets=2, top_n=100, rank_by="RetDD", max_corr=1.0
    )

    engine_tight = BruteForceEngine(long_df)
    results_filtered = engine_tight.run(
        min_assets=2, max_assets=2, top_n=100, rank_by="RetDD", max_corr=0.0
    )

    assert len(results_filtered) <= len(results_all)
