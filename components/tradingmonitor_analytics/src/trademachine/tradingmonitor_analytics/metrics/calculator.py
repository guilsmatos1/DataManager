from __future__ import annotations

from datetime import datetime

import matplotlib

matplotlib.use("Agg")

import numpy as np
import pandas as pd
import quantstats as qs
from trademachine.core.metrics import compute_profit_factor, compute_win_rate
from trademachine.tradingmonitor_analytics.metrics.plugins import PLUGINS
from trademachine.tradingmonitor_analytics.metrics.plugins.base import BaseMetric
from trademachine.tradingmonitor_analytics.metrics.repository import (
    get_strategy_deals,
    get_strategy_equity_curve,
)
from trademachine.tradingmonitor_analytics.metrics.utils import (
    combine_equity_series,
    filter_trading_deals,
    net_pnl,
)
from trademachine.tradingmonitor_storage.public import Portfolio, SessionLocal

# Lazy initialization cache for plugin instances
_plugin_instances: dict[type[BaseMetric], BaseMetric] = {}


def _get_plugin(plugin_cls: type[BaseMetric]) -> BaseMetric:
    """Get or create a cached instance of a plugin."""
    if plugin_cls not in _plugin_instances:
        _plugin_instances[plugin_cls] = plugin_cls()
    return _plugin_instances[plugin_cls]


# Re-export for backward compatibility
__all__ = [
    "get_strategy_deals",
    "get_strategy_equity_curve",
    "calculate_metrics_from_df",
    "calculate_metrics",
    "calculate_correlation_matrix",
    "calculate_dynamic_correlation",
    "calculate_concurrency",
    "calculate_portfolio_metrics",
]


def _build_base_metrics(trading_deals: pd.DataFrame) -> dict:
    """Compute profit, gross profit/loss, profit factor and win rate."""
    gross_profit = trading_deals[trading_deals["profit"] > 0]["profit"].sum()
    gross_loss = -abs(trading_deals[trading_deals["profit"] < 0]["profit"].sum())
    profit = net_pnl(trading_deals).sum()
    return {
        "Total Trades": len(trading_deals),
        "Profit": profit,
        "Avg Profit": profit / len(trading_deals),
        "Gross Profit": gross_profit,
        "Gross Loss": gross_loss,
        "Profit Factor": compute_profit_factor(trading_deals["profit"].values),
        "Win Rate (%)": compute_win_rate(trading_deals["profit"].values),
    }


def _build_streak_metrics(profits: np.ndarray) -> dict:
    """Compute consecutive wins/losses and Z-Score from profit array."""
    max_consecutive_wins = 0
    max_consecutive_losses = 0
    current_wins = 0
    current_losses = 0
    for p in profits:
        if p > 0:
            current_wins += 1
            current_losses = 0
            max_consecutive_wins = max(max_consecutive_wins, current_wins)
        elif p < 0:
            current_losses += 1
            current_wins = 0
            max_consecutive_losses = max(max_consecutive_losses, current_losses)
        else:
            current_wins = 0
            current_losses = 0

    wins = np.sum(profits > 0)
    losses = np.sum(profits < 0)
    runs = 1
    for i in range(1, len(profits)):
        if (
            (profits[i] > 0) != (profits[i - 1] > 0)
            and profits[i] != 0
            and profits[i - 1] != 0
        ):
            runs += 1
    n = wins + losses
    z_score = None
    if n > 2 and wins > 0 and losses > 0:
        expected_runs = (2.0 * wins * losses) / n + 1
        std_runs = np.sqrt(
            (2.0 * wins * losses * (2.0 * wins * losses - n)) / (n * n * (n - 1))
        )
        if std_runs > 0:
            z_score = round((runs - expected_runs) / std_runs, 2)

    return {
        "Consecutive Wins": max_consecutive_wins,
        "Consecutive Losses": max_consecutive_losses,
        "Z-Score": z_score,
    }


def _build_trade_breakdown(trading_deals: pd.DataFrame) -> dict:
    """Compute long/short trade counts and percentages."""
    total = len(trading_deals)
    long_trades = int((trading_deals["type"] == "BUY").sum())
    short_trades = int((trading_deals["type"] == "SELL").sum())
    long_pct = (long_trades / total * 100) if total else 0.0
    short_pct = (short_trades / total * 100) if total else 0.0
    return {
        "Long Trades": long_trades,
        "Long Trades (%)": round(long_pct, 2),
        "Short Trades": short_trades,
        "Short Trades (%)": round(short_pct, 2),
    }


def _compute_return_pct(equity_df: pd.DataFrame) -> float | None:
    """Compute return percentage from equity curve."""
    if equity_df.empty or "equity" not in equity_df.columns:
        return None
    equity_series = equity_df["equity"].dropna().astype(float)
    if equity_series.empty:
        return None
    starting = float(equity_series.iloc[0])
    ending = float(equity_series.iloc[-1])
    if starting == 0:
        return None
    return ((ending - starting) / abs(starting)) * 100


def _build_daily_returns(equity_df: pd.DataFrame) -> pd.Series | None:
    """Resample equity to daily and compute percentage returns for plugins."""
    if equity_df.empty:
        return None
    daily_equity = equity_df["equity"].resample("D").last().ffill().dropna()
    if len(daily_equity) <= 1:
        return None
    return daily_equity.pct_change().dropna()


_ORDERED_KEYS = [
    "Total Trades",
    "Profit",
    "Avg Profit",
    "Return (%)",
    "Profit Factor",
    "Ret/DD",
    "Win Rate (%)",
    "Drawdown",
    "Gross Profit",
    "Gross Loss",
    "Consecutive Wins",
    "Consecutive Losses",
    "Long Trades",
    "Long Trades (%)",
    "Short Trades",
    "Short Trades (%)",
    "Z-Score",
]


def calculate_metrics_from_df(
    deals_df: pd.DataFrame, equity_df: pd.DataFrame, advanced: bool = False
) -> dict:
    """Calculate metrics from DataFrames with improved robustness."""
    if deals_df.empty:
        return {"error": "No trades found."}

    trading_deals = filter_trading_deals(deals_df)
    if trading_deals.empty:
        return {"error": "No valid trading deals found."}

    metrics = _build_base_metrics(trading_deals)
    metrics["Return (%)"] = _compute_return_pct(equity_df)
    metrics.update(_build_streak_metrics(trading_deals["profit"].values))
    metrics.update(_build_trade_breakdown(trading_deals))

    daily_returns = _build_daily_returns(equity_df)
    for plugin_cls in PLUGINS:
        plugin = _get_plugin(plugin_cls)
        if not advanced and plugin.is_advanced:
            continue
        val = plugin.calculate(trading_deals, daily_returns)
        if val is not None:
            metrics[plugin.name] = val

    final_metrics = {k: metrics[k] for k in _ORDERED_KEYS if k in metrics}
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
        net = net_pnl(df)
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


def calculate_dynamic_correlation(
    strategy_ids: list[str], window_days: int = 30
) -> dict:
    """Calculate rolling correlation across strategies for a specific window in days."""
    series = {}
    for sid in strategy_ids:
        df = get_strategy_deals(sid)
        if df.empty:
            continue
        # Use daily P&L for correlation
        net = net_pnl(df)
        series[sid] = net.resample("D").sum()

    if len(series) < 2:
        return {"error": "Not enough data for dynamic correlation."}

    combined = pd.DataFrame(series).fillna(0)

    # Only keep the last N days
    if not combined.empty:
        last_date = combined.index.max()
        start_date = last_date - pd.Timedelta(days=window_days)
        combined = combined[combined.index >= start_date]

    if len(combined) < 3:
        return {"error": f"Not enough data in the last {window_days} days."}

    corr = combined.corr()
    strategies = list(corr.columns)

    return {
        "window_days": window_days,
        "strategies": strategies,
        "matrix": [
            [None if pd.isna(v) else round(float(v), 3) for v in row]
            for row in corr.values
        ],
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
        if not df_deals.empty:
            all_deals.append(df_deals)
            pnl = net_pnl(df_deals)
            all_equity.append(pd.DataFrame({"equity": pnl.cumsum()}))

    if not all_deals:
        return {"error": "No data found for any strategy in this portfolio."}

    combined_deals = pd.concat(all_deals).sort_index()

    if all_equity:
        # Portfolio Equity Aligment:
        # 1. Join all series 2. Fill gaps with ffill 3. Sum row-wise
        # Filling NaNs with ffill (carry forward last known value) and then 0 for initial period
        # ffill preenche apenas lacunas dentro do período ativo de cada estratégia (máx 5 períodos).
        # fillna(0) cobre o período anterior ao início de cada estratégia.
        equity_combined_df = combine_equity_series(
            [equity_df["equity"] for equity_df in all_equity]
        )
        portfolio_equity = equity_combined_df.sum(axis=1)
        combined_equity_df = pd.DataFrame(portfolio_equity, columns=["equity"])
    else:
        combined_equity_df = pd.DataFrame()

    return calculate_metrics_from_df(combined_deals, combined_equity_df)


def generate_qs_report(
    strategy_id: str | None = None,
    portfolio_id: int | None = None,
    backtest_id: int | None = None,
    output_path: str = "report.html",
    title: str = "Performance Report",
) -> str | None:
    """Generate a QuantStats HTML report for a strategy, portfolio, or backtest.

    Args:
        strategy_id: The strategy identifier. If provided, generates a report for
            that strategy alone.
        portfolio_id: The portfolio database ID. If provided, generates a report
            combining all strategies in the portfolio. Cannot be used together
            with strategy_id.
        backtest_id: The backtest database ID. If provided, generates a report
            for that backtest.
        output_path: File path where the HTML report will be saved.
        title: Title displayed in the report header. Defaults to "Performance Report".
            Automatically prefixed with "Strategy Report: " or "Portfolio Report: "
            based on the source.

    Returns:
        The output_path string if the report was generated successfully, or None
        if no data was available for the specified strategy or portfolio.
    """
    equity_df = pd.DataFrame()

    if strategy_id:
        equity_df = get_strategy_equity_curve(strategy_id)
        if title == "Performance Report":
            title = f"Strategy Report: {strategy_id}"
    elif backtest_id:
        from trademachine.tradingmonitor_analytics.metrics.repository import (
            get_backtest_equity,
        )

        equity_df = get_backtest_equity(backtest_id)
        if title == "Performance Report":
            title = f"Backtest Report: {backtest_id}"
    elif portfolio_id:
        db = SessionLocal()
        try:
            portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
            if not portfolio:
                return None

            strategy_ids = [s.id for s in portfolio.strategies]
            if not strategy_ids:
                return None

            all_equity = []
            for sid in strategy_ids:
                df_e = get_strategy_equity_curve(sid)
                if not df_e.empty:
                    all_equity.append(df_e["equity"])

            if all_equity:
                equity_combined_df = combine_equity_series(all_equity)
                portfolio_equity = equity_combined_df.sum(axis=1)
                equity_df = pd.DataFrame(portfolio_equity, columns=["equity"])

            if title == "Performance Report":
                title = f"Portfolio Report: {portfolio.name}"
        except Exception as e:
            import logging

            logging.getLogger(__name__).error(
                f"Error fetching portfolio {portfolio_id}: {e}"
            )
            return None
        finally:
            db.close()

    if equity_df.empty:
        return None

    # Resample to daily equity and get returns
    daily_equity = equity_df["equity"].resample("D").last().ffill().dropna()
    if len(daily_equity) < 2:
        return None

    daily_returns = daily_equity.pct_change().dropna()

    if daily_returns.empty:
        return None

    # QuantStats report
    qs.reports.html(
        daily_returns,
        output=output_path,
        title=title,
        download_filename=output_path,
        show_browser=False,
    )

    return output_path
