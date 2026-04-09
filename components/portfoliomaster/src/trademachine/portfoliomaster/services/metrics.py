"""
Metrics Core Module
===================
MT5-specific data cleaning and metrics adapters for the portfoliomaster component.
Heavy calculations are delegated to trademachine.metrics (the canonical engine).
"""

from typing import Any

import numpy as np
import pandas as pd
import polars as pl
from trademachine.core.metrics import (
    compute_max_drawdown,
    compute_retdd,
)


def clean_mt5_numeric_string(series: pd.Series | pl.Series) -> pd.Series | pl.Series:
    """Unified logic to clean MT5 numeric strings."""
    if isinstance(series, pd.Series):
        cleaned = series.astype(str).str.replace(r"[^\d.\-]", "", regex=True)
        return pd.to_numeric(cleaned.replace("", "0"), errors="coerce").fillna(0.0)
    else:
        return (
            series.cast(pl.String)
            .str.replace_all(r"[^\d\.\-]", "")
            .str.replace(r"^$", "0")
            .cast(pl.Float64, strict=False)
            .fill_null(0.0)
        )


def compute_vector_metrics(
    returns: np.ndarray | list[float] | pd.Series | pl.Series,
) -> dict[str, float]:
    """
    Calculates core performance metrics from a vector of returns.

    Metrics Definition (MetaTrader 5 Style):
    - Net Profit: Sum of all net profits (Profit + Swap + Commission).
    - Max Drawdown (Fixed): The maximum drop from a peak in the equity curve,
      calculated from an initial balance of 0.0.
    - RetDD (Recovery Factor): Net Profit / Maximum Drawdown.

    Uses float64 for financial precision in large-scale accumulations.
    """
    if len(returns) == 0:
        return {"Profit": 0.0, "MaxDD": 0.0, "RetDD": 0.0}

    # Standardized to float64 to prevent rounding errors in long equity curves
    arr = np.array(returns, dtype=np.float64)
    profit = float(np.sum(arr))

    # Use core.metrics for MaxDD and RetDD
    max_dd = compute_max_drawdown(arr)
    ret_dd = compute_retdd(arr)

    return {
        "Profit": round(profit, 2),
        "MaxDD": round(max_dd, 2),
        "RetDD": round(ret_dd, 2),
    }


def preprocess_deals(deals_df: pd.DataFrame) -> pd.DataFrame:
    """Cleans and prepares MT5 deals DataFrame."""
    valid_types = ["buy", "sell", "balance"]
    cleaned_df = deals_df[deals_df["Horário"].str.strip() != ""].copy()
    cleaned_df = cleaned_df[cleaned_df["Tipo"].isin(valid_types)]

    numeric_cols = ["Lucro", "Saldo", "Comissão", "Swap"]
    for col in numeric_cols:
        if col in cleaned_df.columns:
            cleaned_df[col] = clean_mt5_numeric_string(cleaned_df[col])

    return cleaned_df


def extract_closed_trades(deals_df: pd.DataFrame) -> pd.DataFrame:
    """Extracts trade records representing position closures."""
    closure_directions = ["out", "in/out"]
    trades_df = deals_df[
        deals_df["Tipo"].isin(["buy", "sell"])
        & deals_df["Direção"].isin(closure_directions)
    ].copy()

    trades_df["Net_Profit"] = (
        trades_df["Lucro"] + trades_df["Swap"] + trades_df["Comissão"]
    ).round(2)

    return trades_df


def _compute_win_loss_streaks(outcomes: list[int]) -> tuple:
    """Separates a sequence of trade outcomes into win and loss streak lengths.

    Args:
        outcomes: List of 1 (win) or -1 (loss) values.

    Returns:
        Tuple of (win_streaks, loss_streaks) as lists of run lengths.
    """
    win_streaks: list[int] = []
    loss_streaks: list[int] = []
    current_streak = 1
    current_outcome = outcomes[0]

    for outcome in outcomes[1:]:
        if outcome == current_outcome:
            current_streak += 1
        else:
            target = win_streaks if current_outcome == 1 else loss_streaks
            target.append(current_streak)
            current_outcome = outcome
            current_streak = 1

    # Append the final run
    target = win_streaks if current_outcome == 1 else loss_streaks
    target.append(current_streak)

    return win_streaks, loss_streaks


def calculate_metrics_from_deals(deals_df: pd.DataFrame) -> dict[str, Any]:
    """Orchestrates full MT5 report metrics calculation via the metrics component."""
    from trademachine.metrics.public import EquityPoint, TradeRecord, compute_all

    processed_df = preprocess_deals(deals_df)

    balance_rows = processed_df[processed_df["Tipo"] == "balance"]
    initial_balance = (
        float(balance_rows["Saldo"].iloc[0]) if not balance_rows.empty else 0.0
    )

    trades_df = extract_closed_trades(processed_df)
    if len(trades_df) == 0:
        return {}

    # Parse MT5 timestamps (format: "YYYY.MM.DD HH:MM:SS")
    ts_fmt = "%Y.%m.%d %H:%M:%S"
    trade_ts = pd.to_datetime(trades_df["Horário"], format=ts_fmt, errors="coerce")
    equity_ts = pd.to_datetime(processed_df["Horário"], format=ts_fmt, errors="coerce")

    # Build TradeRecord list (Horário is close time; used as entry and exit)
    trade_records: list[TradeRecord] = [
        TradeRecord(entry_time=ts, exit_time=ts, pnl=float(pnl), side="long")
        for ts, pnl in zip(trade_ts, trades_df["Net_Profit"], strict=True)
        if pd.notna(ts)
    ]

    # Build equity curve from all processed rows (balance + trade rows)
    equity_points: list[EquityPoint] = [
        EquityPoint(timestamp=ts, equity=float(eq))
        for ts, eq in zip(equity_ts, processed_df["Saldo"], strict=True)
        if pd.notna(ts) and pd.notna(eq)
    ]

    initial_capital = max(initial_balance, 1.0)
    result = compute_all(trade_records, equity_points, initial_capital)

    # Net profit directly from trades to avoid initial_capital rounding artefacts
    pnls = trades_df["Net_Profit"].tolist()
    net_profit_val = round(float(trades_df["Net_Profit"].sum()), 2)
    max_dd = result.drawdown or 0.0
    retdd_val = round(net_profit_val / max_dd, 2) if max_dd > 0 else 0.0

    # Trade counts (MT5 convention: break-even >= 0 counts as win)
    total = len(trades_df)
    wins_count = int(sum(1 for p in pnls if p >= 0))
    losses_count = total - wins_count

    # Average consecutive streaks (not in MetricsResult — only max is tracked there)
    outcomes = [1 if p >= 0 else -1 for p in pnls]
    win_streaks, loss_streaks = _compute_win_loss_streaks(outcomes)
    avg_win_streak = (
        round(sum(win_streaks) / len(win_streaks), 1) if win_streaks else 0.0
    )
    avg_loss_streak = (
        round(sum(loss_streaks) / len(loss_streaks), 1) if loss_streaks else 0.0
    )

    return {
        "Net_Profit": net_profit_val,
        "Gross_Profit": round(result.gross_profit or 0.0, 2),
        "Gross_Loss": round(result.gross_loss or 0.0, 2),
        "Profit_Factor": round(result.profit_factor or 0.0, 2),
        "RetDD": retdd_val,
        "Total_Trades": total,
        "Win_Percentage": round((result.winning_pct or 0.0) * 100, 2),
        "Payoff": round(result.average_trade or 0.0, 2),
        "Maximum_Drawdown": round(max_dd, 2),
        "Relative_Drawdown": round((result.drawdown_pct or 0.0) * 100, 2),
        "Win_Loss_Ratio": round(result.wins_losses_ratio or 0.0, 2),
        "Avg_Win": round(result.average_win or 0.0, 2),
        "Avg_Loss": round(result.average_loss or 0.0, 2),
        "Avg_Consecutive_Wins": avg_win_streak,
        "Avg_Consecutive_Losses": avg_loss_streak,
        "Winning_Trades_Count": wins_count,
        "Losing_Trades_Count": losses_count,
    }
