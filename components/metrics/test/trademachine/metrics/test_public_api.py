"""Contract tests: public.py must expose the stable API surface."""

from __future__ import annotations

from trademachine.metrics import public


def test_public_exports() -> None:
    expected = {
        "EquityPoint",
        "MetricsInput",
        "MetricsResult",
        "Side",
        "TradeRecord",
        "compute_all",
        "compute_subset",
    }
    assert expected <= set(public.__all__)
    for name in expected:
        assert hasattr(public, name), f"public.py missing {name}"


def test_compute_all_returns_metrics_result(
    sample_trades, sample_equity, initial_capital
) -> None:
    result = public.compute_all(
        trades=sample_trades,
        equity=sample_equity,
        initial_capital=initial_capital,
    )
    assert isinstance(result, public.MetricsResult)


def test_compute_all_empty_trades(initial_capital) -> None:
    result = public.compute_all(trades=[], equity=[], initial_capital=initial_capital)
    assert isinstance(result, public.MetricsResult)
    assert result.total_profit == 0.0
    assert result.daily_avg_profit is None


def test_compute_subset_filters_keys(
    sample_trades, sample_equity, initial_capital
) -> None:
    subset = public.compute_subset(
        trades=sample_trades,
        equity=sample_equity,
        initial_capital=initial_capital,
        metrics={"total_profit", "profit_factor"},
    )
    assert set(subset.keys()) == {"total_profit", "profit_factor"}


def test_compute_all_full_result_fields(
    sample_trades, sample_equity, initial_capital
) -> None:
    result = public.compute_all(
        trades=sample_trades,
        equity=sample_equity,
        initial_capital=initial_capital,
        risk_per_trade=50.0,
    )
    assert result.total_profit is not None
    assert result.profit_factor is not None
    assert result.drawdown is not None
    assert result.sqn is not None
    assert result.stability is not None
    assert result.symmetry is not None
    assert result.exposure is not None
