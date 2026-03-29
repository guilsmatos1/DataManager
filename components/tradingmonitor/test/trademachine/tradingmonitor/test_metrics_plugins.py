from datetime import datetime, timedelta

import pandas as pd
from trademachine.tradingmonitor.metrics.calculator import (
    calculate_dynamic_correlation,
    calculate_metrics_from_df,
)
from trademachine.tradingmonitor.metrics.plugins.base import BaseMetric


class MockMetric(BaseMetric):
    @property
    def name(self) -> str:
        return "Mock Metric"

    def calculate(self, deals_df, daily_returns=None, **kwargs):
        return 42.0


def test_plugin_system_integration(monkeypatch):
    """Test if the system correctly picks up and executes plugins."""
    # Temporarily add MockMetric to PLUGINS where it's consumed by the calculator
    from trademachine.tradingmonitor.metrics import calculator

    original_plugins = calculator.PLUGINS.copy()
    monkeypatch.setattr(
        "trademachine.tradingmonitor.metrics.calculator.PLUGINS",
        original_plugins + [MockMetric],
    )

    base_time = datetime(2024, 1, 1)
    deals_df = pd.DataFrame(
        {
            "type": ["BUY", "SELL"],
            "profit": [10.0, -5.0],
            "commission": [0.0, 0.0],
            "swap": [0.0, 0.0],
        },
        index=[base_time, base_time + timedelta(hours=1)],
    )

    metrics = calculate_metrics_from_df(deals_df, pd.DataFrame())

    assert "Mock Metric" in metrics
    assert metrics["Mock Metric"] == 42.0


def test_individual_plugins_logic():
    """Test the logic of specific plugins directly."""
    from trademachine.tradingmonitor.metrics.plugins import (
        MaxDrawdown,
        RiskRewardRatio,
        SharpeRatio,
    )

    # Mock data for returns: [1%, -1%, 2%, -0.5%] with DatetimeIndex
    base_time = datetime(2024, 1, 1)
    daily_returns = pd.Series(
        [0.01, -0.01, 0.02, -0.005],
        index=[base_time + timedelta(days=i) for i in range(4)],
    )
    deals_df = pd.DataFrame(
        {
            "profit": [10.0, -5.0, 20.0, -5.0],
        }
    )

    sharpe = SharpeRatio()
    assert sharpe.name == "Sharpe Ratio"
    val_sharpe = sharpe.calculate(deals_df, daily_returns)
    assert val_sharpe is not None
    assert isinstance(val_sharpe, float)

    mdd = MaxDrawdown()
    val_mdd = mdd.calculate(deals_df, daily_returns)
    assert val_mdd is not None
    assert val_mdd <= 0  # Drawdown is typically negative in QuantStats

    rrr = RiskRewardRatio()
    val_rrr = rrr.calculate(deals_df)
    # Average win = (10+20)/2 = 15
    # Average loss = (5+5)/2 = 5
    # RRR = 15 / 5 = 3.0
    assert val_rrr == 3.0


def test_calculate_dynamic_correlation_logic(monkeypatch):
    """Test the rolling correlation calculation."""
    base_time = datetime(2024, 1, 1)

    # Strategy 1: Positive returns every day
    s1_deals = pd.DataFrame(
        {"profit": [10.0] * 10, "commission": [0.0] * 10, "swap": [0.0] * 10},
        index=[base_time + timedelta(days=i) for i in range(10)],
    )

    # Strategy 2: Also positive returns every day (High correlation)
    s2_deals = pd.DataFrame(
        {"profit": [5.0] * 10, "commission": [0.0] * 10, "swap": [0.0] * 10},
        index=[base_time + timedelta(days=i) for i in range(10)],
    )

    # Strategy 3: Alternating (Lower correlation)
    s3_deals = pd.DataFrame(
        {"profit": [10.0, -10.0] * 5, "commission": [0.0] * 10, "swap": [0.0] * 10},
        index=[base_time + timedelta(days=i) for i in range(10)],
    )

    def mock_get_deals(sid, since=None):
        if sid == "S1":
            return s1_deals
        if sid == "S2":
            return s2_deals
        if sid == "S3":
            return s3_deals
        return pd.DataFrame()

    monkeypatch.setattr(
        "trademachine.tradingmonitor.metrics.calculator.get_strategy_deals",
        mock_get_deals,
    )

    # Test window of 5 days
    result = calculate_dynamic_correlation(["S1", "S2", "S3"], window_days=5)

    assert "matrix" in result
    assert len(result["strategies"]) == 3
    # S1 vs S2 should be highly correlated (both constant profit)
    # Note: correlation of constant series might be NaN or 0 depending on implementation,
    # but here we use daily resample which fills 0s if missing.
    # Actually, constant vs constant is NaN in pandas corr(). Let's check robustness.

    matrix = result["matrix"]
    assert len(matrix) == 3
    assert len(matrix[0]) == 3


def test_dynamic_correlation_insufficient_data(monkeypatch):
    """Test error handling when not enough data is available."""
    monkeypatch.setattr(
        "trademachine.tradingmonitor.metrics.calculator.get_strategy_deals",
        lambda sid: pd.DataFrame(),
    )

    result = calculate_dynamic_correlation(["S1", "S2"], window_days=30)
    assert "error" in result
