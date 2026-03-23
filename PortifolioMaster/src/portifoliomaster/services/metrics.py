"""
Metrics Core Module
===================
Centralized logic for calculating performance metrics and cleaning MT5 data.
Follows PEP8 standards and uses descriptive naming.
"""

from typing import Any

import numpy as np
import pandas as pd
import polars as pl


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

    # Drawdown calculation starting from 0.0 (Initial account state)
    equity = np.cumsum(np.insert(arr, 0, 0.0))
    peaks = np.maximum.accumulate(equity)
    drawdowns = peaks - equity
    max_dd = float(np.max(drawdowns))

    ret_dd = (profit / max_dd) if max_dd > 0 else 0.0

    return {"Profit": round(profit, 2), "MaxDD": round(max_dd, 2), "RetDD": round(ret_dd, 2)}


def compute_drawdown_metrics(
    balance_curve: list[float], initial_balance: float
) -> dict[str, float]:
    """
    Calculates detailed Drawdown metrics from a balance curve.

    Metrics Definition (MT5 Style):
    - Absolute Drawdown: Initial Balance - Minimum Balance reached.
    - Maximum Drawdown: Largest drop from a peak.
    - Relative Drawdown: Maximum Drawdown as a percentage of the peak value,
      computed at each point in time (max over all points, not just at peak DD).
    """
    if not balance_curve:
        return {"absolute": 0.0, "maximum": 0.0, "relative": 0.0}

    arr = np.array(balance_curve, dtype=np.float64)
    absolute_drawdown = max(0.0, initial_balance - float(np.min(arr)))

    peaks = np.maximum.accumulate(np.maximum(arr, initial_balance))
    drawdowns = peaks - arr
    max_dd = float(np.max(drawdowns))
    safe_peaks = np.where(peaks > 0, peaks, 1.0)
    max_rel_dd = float(np.max(drawdowns / safe_peaks)) * 100

    return {
        "absolute": round(absolute_drawdown, 2),
        "maximum": round(max_dd, 2),
        "relative": round(max_rel_dd, 2),
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
        deals_df["Tipo"].isin(["buy", "sell"]) & deals_df["Direção"].isin(closure_directions)
    ].copy()

    trades_df["Net_Profit"] = (
        trades_df["Lucro"] + trades_df["Swap"] + trades_df["Comissão"]
    ).round(2)

    return trades_df


def compute_performance_ratios(trades_df: pd.DataFrame) -> dict[str, float]:
    """Calculates win/loss ratios and averages."""
    total = len(trades_df)
    if total == 0:
        return {"avg_win": 0.0, "avg_loss": 0.0, "win_percentage": 0.0, "win_loss_ratio": 0.0}

    # MT5 convention: break-even trades (profit == 0) count as wins
    wins = trades_df[trades_df["Net_Profit"] >= 0]
    losses = trades_df[trades_df["Net_Profit"] < 0]

    num_wins = len(wins)
    num_losses = len(losses)  # actual losing trades, not (total - wins)

    avg_win = wins["Net_Profit"].mean() if num_wins > 0 else 0.0
    avg_loss = losses["Net_Profit"].mean() if num_losses > 0 else 0.0

    win_loss_ratio = round(num_wins / num_losses, 2) if num_losses > 0 else float("inf")
    return {
        "avg_win": round(float(avg_win), 2),
        "avg_loss": round(float(avg_loss), 2),
        "win_percentage": round((num_wins / total) * 100, 2),
        "win_loss_ratio": win_loss_ratio,
    }


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


def compute_streak_statistics(trades_df: pd.DataFrame) -> dict[str, float]:
    """Calculates average consecutive win and loss streaks."""
    # MT5 convention: break-even trades (profit == 0) count as wins, consistent
    # with compute_performance_ratios which uses >= 0 for wins.
    outcomes = [1 if profit >= 0 else -1 for profit in trades_df["Net_Profit"]]
    if not outcomes:
        return {"avg_win_streak": 0.0, "avg_loss_streak": 0.0}

    win_streaks, loss_streaks = _compute_win_loss_streaks(outcomes)

    return {
        "avg_win_streak": round(sum(win_streaks) / len(win_streaks) if win_streaks else 0.0, 1),
        "avg_loss_streak": round(sum(loss_streaks) / len(loss_streaks) if loss_streaks else 0.0, 1),
    }


def calculate_metrics_from_deals(deals_df: pd.DataFrame) -> dict[str, Any]:
    """Orchestrates full MT5 report metrics calculation."""
    processed_df = preprocess_deals(deals_df)

    # Accurate initial balance detection
    balance_rows = processed_df[processed_df["Tipo"] == "balance"]
    initial_balance = balance_rows["Saldo"].iloc[0] if not balance_rows.empty else 0.0

    trades_df = extract_closed_trades(processed_df)
    if len(trades_df) == 0:
        return {}

    # Core performance metrics
    base_metrics = compute_vector_metrics(trades_df["Net_Profit"])

    # Detailed drawdown metrics from balance curve
    drawdowns = compute_drawdown_metrics(processed_df["Saldo"].tolist(), initial_balance)

    ratios = compute_performance_ratios(trades_df)
    streaks = compute_streak_statistics(trades_df)

    gross_profit = float(trades_df[trades_df["Net_Profit"] > 0]["Net_Profit"].sum())
    gross_loss = float(trades_df[trades_df["Net_Profit"] < 0]["Net_Profit"].sum())

    return {
        "Net_Profit": base_metrics["Profit"],
        "Gross_Profit": round(gross_profit, 2),
        "Gross_Loss": round(gross_loss, 2),
        "Profit_Factor": round(gross_profit / abs(gross_loss), 2) if gross_loss != 0 else 0.0,
        "RetDD": base_metrics["RetDD"],
        "Total_Trades": len(trades_df),
        "Win_Percentage": ratios["win_percentage"],
        "Payoff": round(base_metrics["Profit"] / len(trades_df), 2),
        "Maximum_Drawdown": drawdowns["maximum"],
        "Relative_Drawdown": drawdowns["relative"],
        "Win_Loss_Ratio": ratios["win_loss_ratio"],
        "Avg_Win": ratios["avg_win"],
        "Avg_Loss": ratios["avg_loss"],
        "Avg_Consecutive_Wins": streaks["avg_win_streak"],
        "Avg_Consecutive_Losses": streaks["avg_loss_streak"],
        "Winning_Trades_Count": int(len(trades_df[trades_df["Net_Profit"] >= 0])),
        "Losing_Trades_Count": int(len(trades_df[trades_df["Net_Profit"] < 0])),
    }
