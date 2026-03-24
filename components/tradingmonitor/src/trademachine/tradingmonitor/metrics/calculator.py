from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import quantstats as qs
from trademachine.tradingmonitor.metrics.repository import (
    get_strategy_deals,
    get_strategy_equity_curve,
)

# Extending pandas with quantstats
qs.extend_pandas()

# Re-export for backward compatibility
__all__ = [
    "get_strategy_deals",
    "get_strategy_equity_curve",
    "calculate_metrics_from_df",
    "calculate_metrics",
    "calculate_correlation_matrix",
    "calculate_concurrency",
    "calculate_portfolio_metrics",
]


def _compute_qs_stats(daily_returns: pd.Series, advanced: bool) -> dict:
    stats: dict = {}
    try:
        stats["Max Drawdown (%)"] = qs.stats.max_drawdown(daily_returns) * 100
    except (ValueError, ZeroDivisionError):
        stats["Max Drawdown (%)"] = None

    try:
        stats["Recovery Factor"] = qs.stats.recovery_factor(daily_returns)
    except (ValueError, ZeroDivisionError):
        stats["Recovery Factor"] = None

    try:
        stats["Sharpe Ratio"] = qs.stats.sharpe(daily_returns)
    except (ValueError, ZeroDivisionError):
        stats["Sharpe Ratio"] = None

    if advanced:
        try:
            stats["Sortino Ratio"] = qs.stats.sortino(daily_returns)
        except (ValueError, ZeroDivisionError):
            stats["Sortino Ratio"] = None
        try:
            stats["Calmar Ratio"] = qs.stats.calmar(daily_returns)
        except (ValueError, ZeroDivisionError):
            stats["Calmar Ratio"] = None
        try:
            var_5 = float(np.percentile(daily_returns, 5))
            stats["VaR 95% (daily)"] = var_5
            stats["CVaR 95% (daily)"] = float(
                daily_returns[daily_returns <= var_5].mean()
            )
        except (ValueError, ZeroDivisionError):
            stats["VaR 95% (daily)"] = None
            stats["CVaR 95% (daily)"] = None

    return stats


def calculate_metrics_from_df(
    deals_df: pd.DataFrame, equity_df: pd.DataFrame, advanced: bool = False
) -> dict:
    """Helper function to calculate metrics from DataFrames with improved robustness."""
    if deals_df.empty:
        return {"error": "No trades found."}

    # Filter to BUY/SELL only — pd.read_sql stores enum values as strings ('BUY', 'SELL')
    trading_deals = deals_df[deals_df["type"].isin(["BUY", "SELL"])]

    if trading_deals.empty:
        return {"error": "No valid trading deals found."}

    gross_profit = trading_deals[trading_deals["profit"] > 0]["profit"].sum()
    gross_loss = abs(trading_deals[trading_deals["profit"] < 0]["profit"].sum())

    # Net profit includes commissions and swaps
    net_profit = (
        trading_deals["profit"].sum()
        + trading_deals["commission"].sum()
        + trading_deals["swap"].sum()
    )

    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else (float("inf") if gross_profit > 0 else 0.0)
    )

    winning_trades = len(trading_deals[trading_deals["profit"] > 0])
    win_rate = (
        (winning_trades / len(trading_deals)) * 100 if len(trading_deals) > 0 else 0
    )

    metrics = {
        "Total Trades": len(trading_deals),
        "Net Profit": net_profit,
        "Gross Profit": gross_profit,
        "Gross Loss": gross_loss,
        "Profit Factor": profit_factor,
        "Win Rate (%)": win_rate,
    }

    if not equity_df.empty:
        # Optimization: Resample to daily frequency before calculating complex stats
        # Forward fill to handle weekends/holidays properly for the equity curve
        daily_equity = equity_df["equity"].resample("D").last().ffill().dropna()

        if len(daily_equity) > 1:
            daily_returns = daily_equity.pct_change().dropna()
            if not daily_returns.empty:
                stats = _compute_qs_stats(daily_returns, advanced)
                metrics.update(stats)

    if advanced:
        # Risk-Reward Ratio (Expectativa): avg_win / abs(avg_loss)
        wins = trading_deals[trading_deals["profit"] > 0]["profit"]
        losses = trading_deals[trading_deals["profit"] < 0]["profit"]
        if not wins.empty and not losses.empty:
            avg_win = wins.mean()
            avg_loss = abs(losses.mean())
            metrics["Risk-Reward Ratio"] = avg_win / avg_loss if avg_loss > 0 else None
        else:
            metrics["Risk-Reward Ratio"] = None

    ordered_keys = [
        "Total Trades",
        "Net Profit",
        "Profit Factor",
        "Recovery Factor",
        "Win Rate (%)",
        "Max Drawdown (%)",
        "Gross Profit",
        "Gross Loss",
    ]

    final_metrics = {}
    for k in ordered_keys:
        if k in metrics:
            final_metrics[k] = metrics[k]

    for k, v in metrics.items():
        if k not in final_metrics:
            final_metrics[k] = v

    return final_metrics


def calculate_metrics(strategy_id: str) -> dict:
    """Calculate comprehensive trading metrics for a given strategy."""
    deals_df = get_strategy_deals(strategy_id)
    equity_df = get_strategy_equity_curve(strategy_id)
    return calculate_metrics_from_df(deals_df, equity_df)


def calculate_correlation_matrix(
    strategy_ids: list[str], period: str = "daily", since: datetime | None = None
) -> dict:
    """Correlation matrix of net P&L returns across strategies."""
    freq_map = {"daily": "D", "weekly": "W-MON", "monthly": "MS"}
    freq = freq_map.get(period, "D")

    series = {}
    for sid in strategy_ids:
        df = get_strategy_deals(sid, since=since)
        if df.empty:
            continue
        net = df["profit"] + df["commission"] + df["swap"]
        series[sid] = net.resample(freq).sum()

    if len(series) < 2:
        return {
            "error": "Need at least 2 strategies with deal data to compute correlation."
        }

    combined = pd.DataFrame(series).fillna(0)
    combined = combined.loc[(combined != 0).any(axis=1)]

    if len(combined) < 3:
        return {
            "error": "Not enough overlapping periods to compute correlation (need ≥ 3)."
        }

    corr = combined.corr()
    strategies = list(corr.columns)

    # Build insights: top correlated / anti-correlated pairs
    correlation_pairs = []
    for idx_a, strategy_a in enumerate(strategies):
        for idx_b in range(idx_a + 1, len(strategies)):
            strategy_b = strategies[idx_b]
            corr_value = corr.iloc[idx_a, idx_b]
            if not np.isnan(corr_value):
                correlation_pairs.append(
                    (strategy_a, strategy_b, round(float(corr_value), 3))
                )

    correlation_pairs.sort(key=lambda x: x[2])
    most_negative = correlation_pairs[:3] if correlation_pairs else []
    most_positive = correlation_pairs[-3:][::-1] if correlation_pairs else []
    avg_corr = (
        round(float(np.mean([p[2] for p in correlation_pairs])), 3)
        if correlation_pairs
        else None
    )

    return {
        "strategies": strategies,
        "matrix": [
            [None if pd.isna(v) else round(float(v), 3) for v in row]
            for row in corr.values
        ],
        "data_points": len(combined),
        "period": period,
        "date_range": [
            combined.index.min().isoformat() if not combined.empty else None,
            combined.index.max().isoformat() if not combined.empty else None,
        ],
        "insights": {
            "avg_correlation": avg_corr,
            "most_positive": most_positive,
            "most_negative": most_negative,
        },
    }


def calculate_concurrency(
    strategy_ids: list[str], since: datetime | None = None
) -> dict:
    """Probability of concurrent operations between strategy pairs."""
    deals_by_strat = {}
    for sid in strategy_ids:
        df = get_strategy_deals(sid, since=since)
        if not df.empty:
            idx = df.index
            if idx.tz is not None:
                idx = idx.tz_convert("UTC").tz_localize(None)
            deals_by_strat[sid] = idx

    valid_ids = list(deals_by_strat.keys())
    n = len(valid_ids)

    if n < 2:
        return {"error": "Need at least 2 strategies with deal data."}

    def overlap_pct(s1, s2):
        if not s1 or not s2:
            return 0.0
        return round(len(s1 & s2) / min(len(s1), len(s2)) * 100, 1)

    same_hour = [[100.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    same_day = [[100.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    same_week = [[100.0 if i == j else 0.0 for j in range(n)] for i in range(n)]

    for i, id1 in enumerate(valid_ids):
        idx1 = deals_by_strat[id1]
        hours1 = set(idx1.floor("h"))
        days1 = set(idx1.normalize())
        weeks1 = set(idx1.to_period("W").astype(str))

        for j, id2 in enumerate(valid_ids):
            if j <= i:
                continue
            idx2 = deals_by_strat[id2]
            hours2 = set(idx2.floor("h"))
            days2 = set(idx2.normalize())
            weeks2 = set(idx2.to_period("W").astype(str))

            vh = overlap_pct(hours1, hours2)
            vd = overlap_pct(days1, days2)
            vw = overlap_pct(weeks1, weeks2)

            same_hour[i][j] = same_hour[j][i] = vh
            same_day[i][j] = same_day[j][i] = vd
            same_week[i][j] = same_week[j][i] = vw

    # Insights: highest overlap pairs per mode
    def top_pairs(matrix):
        pairs = []
        for i in range(n):
            for j in range(i + 1, n):
                pairs.append((valid_ids[i], valid_ids[j], matrix[i][j]))
        pairs.sort(key=lambda x: -x[2])
        return pairs[:3]

    return {
        "strategies": valid_ids,
        "same_hour": same_hour,
        "same_day": same_day,
        "same_week": same_week,
        "insights": {
            "top_hour": top_pairs(same_hour),
            "top_day": top_pairs(same_day),
            "top_week": top_pairs(same_week),
        },
    }


def calculate_portfolio_metrics(strategy_ids: list[str]) -> dict:
    """Aggregate data from multiple strategies with better time-alignment."""
    all_deals = []
    all_equity = []

    for sid in strategy_ids:
        df_deals = get_strategy_deals(sid)
        df_equity = get_strategy_equity_curve(sid)
        if not df_deals.empty:
            all_deals.append(df_deals)
        if not df_equity.empty:
            all_equity.append(df_equity)

    if not all_deals:
        return {"error": "No data found for any strategy in this portfolio."}

    combined_deals = pd.concat(all_deals).sort_index()

    if all_equity:
        # Portfolio Equity Aligment:
        # 1. Join all series 2. Fill gaps with ffill 3. Sum row-wise
        equity_combined_df = pd.concat(
            [df["equity"] for df in all_equity], axis=1
        ).sort_index()
        # Filling NaNs with ffill (carry forward last known value) and then 0 for initial period
        # ffill preenche apenas lacunas dentro do período ativo de cada estratégia (máx 5 períodos).
        # fillna(0) cobre o período anterior ao início de cada estratégia.
        equity_combined_df = equity_combined_df.ffill(limit=5).fillna(0)
        portfolio_equity = equity_combined_df.sum(axis=1)
        combined_equity_df = pd.DataFrame(portfolio_equity, columns=["equity"])
    else:
        combined_equity_df = pd.DataFrame()

    return calculate_metrics_from_df(combined_deals, combined_equity_df)
