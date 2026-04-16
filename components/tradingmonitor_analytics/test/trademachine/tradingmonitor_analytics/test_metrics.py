from datetime import datetime, timedelta

import pandas as pd
from trademachine.tradingmonitor_analytics.metrics.calculator import (
    calculate_metrics_from_df,
)


def test_calculate_metrics_basic():
    # Setup mock deals
    base_time = datetime(2024, 1, 1)
    deals_data = {
        "ticket": [1, 2, 3, 4],
        "strategy_id": ["123", "123", "123", "123"],
        "symbol": ["EURUSD"] * 4,
        "type": ["BUY", "BUY", "SELL", "SELL"],
        "volume": [0.1] * 4,
        "price": [1.10, 1.11, 1.12, 1.10],
        "profit": [10.0, -5.0, 15.0, -2.0],
        "commission": [-1.0] * 4,
        "swap": [0.0] * 4,
    }

    # Create DataFrame with DatetimeIndex
    timestamps = [base_time + timedelta(hours=i) for i in range(4)]
    deals_df = pd.DataFrame(deals_data, index=timestamps)

    # Mock equity curve (one point per day to simulate daily returns)
    equity_times = [base_time + timedelta(days=i) for i in range(5)]
    equity_df = pd.DataFrame(
        {
            "strategy_id": ["123"] * 5,
            "balance": [1000, 1010, 1005, 1020, 1018],
            "equity": [1000, 1010, 1005, 1020, 1018],
        },
        index=equity_times,
    )

    metrics = calculate_metrics_from_df(deals_df, equity_df)

    assert metrics["Total Trades"] == 4
    # Profit = sum(profit) + sum(commission) + sum(swap)
    # sum(profit) = 10 - 5 + 15 - 2 = 18
    # sum(commission) = -4
    # Profit = 14
    assert metrics["Profit"] == 18.0 - 4.0
    assert metrics["Win Rate (%)"] == 50.0
    assert metrics["Gross Profit"] == 25.0
    assert metrics["Gross Loss"] == -7.0
    assert metrics["Profit Factor"] == 25.0 / 7.0
    assert "Sharpe Ratio" in metrics
    assert "Drawdown" in metrics


def test_calculate_metrics_no_trades():
    deals_df = pd.DataFrame()
    equity_df = pd.DataFrame()
    metrics = calculate_metrics_from_df(deals_df, equity_df)
    assert "error" in metrics
    assert metrics["error"] == "No trades found."


def test_calculate_metrics_all_losses():
    base_time = datetime(2024, 1, 1)
    deals_data = {
        "ticket": [1],
        "strategy_id": ["123"],
        "symbol": ["EURUSD"],
        "type": ["BUY"],
        "volume": [0.1],
        "price": [1.10],
        "profit": [-10.0],
        "commission": [0.0],
        "swap": [0.0],
    }
    deals_df = pd.DataFrame(deals_data, index=[base_time])
    metrics = calculate_metrics_from_df(deals_df, pd.DataFrame())

    assert metrics["Profit Factor"] == 0.0
    assert metrics["Win Rate (%)"] == 0.0
