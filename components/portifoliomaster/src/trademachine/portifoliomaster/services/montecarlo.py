"""
Monte Carlo Module
=================
Runs Monte Carlo simulations on portfolio trade sequences to estimate
the distribution of drawdown and validate portfolio robustness.
"""

from __future__ import annotations

import dataclasses

import numpy as np
from trademachine.portifoliomaster.services.metrics import compute_vector_metrics


@dataclasses.dataclass
class MonteCarloResult:
    """Results from a Monte Carlo simulation."""

    original_equity: np.ndarray  # shape (n_trades+1,), starts at 0
    original_max_dd: float
    original_ret_dd: float
    simulated_equities: np.ndarray  # shape (min(n_iterations, 1000), n_trades+1)
    max_dd_distribution: np.ndarray  # shape (n_iterations,)
    ret_dd_distribution: np.ndarray  # shape (n_iterations,)
    summary: dict


def run_montecarlo(
    returns: np.ndarray | list[float],
    n_iterations: int = 1000,
    seed: int | None = None,
) -> MonteCarloResult:
    """Runs a vectorized Monte Carlo simulation by shuffling trade order.

    For each iteration, the sequence of trades is randomly permuted. This
    preserves the marginal distribution of individual trade outcomes while
    varying the path, allowing estimation of how much of the observed drawdown
    is structural vs. sequence-dependent.

    Args:
        returns: Array of per-trade net profits (e.g., combined portfolio trades).
        n_iterations: Number of random permutations to simulate.
        seed: Optional random seed for reproducibility.

    Returns:
        MonteCarloResult with distributions and summary statistics.
    """
    returns = np.asarray(returns, dtype=np.float64)
    if returns.size == 0:
        raise ValueError("Cannot run Monte Carlo simulation with no trades.")
    n_trades = len(returns)
    rng = np.random.default_rng(seed)

    # Original metrics
    orig_metrics = compute_vector_metrics(returns)
    orig_equity = np.concatenate([[0.0], np.cumsum(returns)])
    orig_profit = float(np.sum(returns))

    # Vectorized shuffle: create (n_iterations, n_trades) matrix, shuffle each row
    shuffled = np.tile(returns, (n_iterations, 1))
    rng.permuted(shuffled, axis=1, out=shuffled)

    # Equity curves: prepend column of zeros → shape (n_iterations, n_trades+1)
    zeros = np.zeros((n_iterations, 1), dtype=np.float64)
    equities = np.hstack([zeros, np.cumsum(shuffled, axis=1)])

    # Running peaks per simulation
    peaks = np.maximum.accumulate(equities, axis=1)

    # Max drawdown per simulation
    max_dd_dist = np.max(peaks - equities, axis=1)

    # RetDD per simulation (profit is constant — only trade order changes)
    with np.errstate(divide="ignore", invalid="ignore"):
        ret_dd_dist = np.where(max_dd_dist > 0, orig_profit / max_dd_dist, 0.0)

    # Limit stored equity curves to avoid memory/browser issues
    n_plot = min(n_iterations, 1000)
    simulated_equities = equities[:n_plot]

    summary = {
        "n_iterations": n_iterations,
        "n_trades": n_trades,
        "max_dd": {
            "mean": float(np.mean(max_dd_dist)),
            "median": float(np.median(max_dd_dist)),
            "p5": float(np.percentile(max_dd_dist, 5)),
            "p95": float(np.percentile(max_dd_dist, 95)),
            "worst": float(np.max(max_dd_dist)),
        },
        "ret_dd": {
            "mean": float(np.mean(ret_dd_dist)),
            "median": float(np.median(ret_dd_dist)),
            "p5": float(np.percentile(ret_dd_dist, 5)),
            "p95": float(np.percentile(ret_dd_dist, 95)),
            "worst": float(np.min(ret_dd_dist)),
        },
    }

    return MonteCarloResult(
        original_equity=orig_equity,
        original_max_dd=orig_metrics["MaxDD"],
        original_ret_dd=orig_metrics["RetDD"],
        simulated_equities=simulated_equities,
        max_dd_distribution=max_dd_dist,
        ret_dd_distribution=ret_dd_dist,
        summary=summary,
    )
