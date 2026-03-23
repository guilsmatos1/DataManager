"""
Tests for Monte Carlo Simulation Module.
"""

import numpy as np
import pytest
from portifoliomaster.services.montecarlo import MonteCarloResult, run_montecarlo


def test_run_montecarlo_basic():
    returns = [10.0, -5.0, 20.0, -2.0, 15.0]
    n_iter = 100
    result = run_montecarlo(returns, n_iterations=n_iter, seed=42)

    assert isinstance(result, MonteCarloResult)
    assert len(result.max_dd_distribution) == n_iter
    assert len(result.ret_dd_distribution) == n_iter
    assert result.original_equity.shape == (6,)
    assert result.simulated_equities.shape == (n_iter, 6)

    # Summary checks
    assert result.summary["n_iterations"] == n_iter
    assert result.summary["n_trades"] == 5
    assert "max_dd" in result.summary
    assert "ret_dd" in result.summary


def test_run_montecarlo_determinism():
    returns = [10.0, -5.0, 20.0]
    res1 = run_montecarlo(returns, n_iterations=10, seed=123)
    res2 = run_montecarlo(returns, n_iterations=10, seed=123)

    np.testing.assert_array_almost_equal(res1.max_dd_distribution, res2.max_dd_distribution)
    np.testing.assert_array_almost_equal(res1.simulated_equities, res2.simulated_equities)


def test_run_montecarlo_empty_returns():
    with pytest.raises(ValueError, match="no trades"):
        run_montecarlo([], n_iterations=10)


def test_run_montecarlo_single_return():
    returns = [10.0]
    result = run_montecarlo(returns, n_iterations=10)
    # With only 1 trade, shuffling order doesn't change anything
    assert np.all(result.max_dd_distribution == result.original_max_dd)


def test_run_montecarlo_limiting_plot_curves():
    returns = np.random.randn(10)
    n_iter = 1500
    result = run_montecarlo(returns, n_iterations=n_iter)
    # Should only store 1000 curves for plotting
    assert result.simulated_equities.shape[0] == 1000
    assert result.max_dd_distribution.shape[0] == 1500
