"""Shared utilities for the metrics module."""

from __future__ import annotations

import pandas as pd

CLOSED_TRADE_TYPES = ["BUY", "SELL"]


def net_pnl(df: pd.DataFrame) -> pd.Series:
    """Return net P&L (profit + commission + swap) as a Series."""
    return df["profit"] + df["commission"] + df["swap"]


def filter_trading_deals(deals_df: pd.DataFrame) -> pd.DataFrame:
    """Filter deals to only closed BUY/SELL trades."""
    return deals_df[deals_df["type"].isin(CLOSED_TRADE_TYPES)]


def combine_equity_series(
    equity_series_list: list[pd.Series], forward_fill_limit: int | None = None
) -> pd.DataFrame:
    """Normalize and combine equity series before summing a portfolio curve.

    Args:
        equity_series_list: List of equity Series to combine.
        forward_fill_limit: Max consecutive NaNs to fill forward.
            None means unlimited forward fill.
    """
    if not equity_series_list:
        return pd.DataFrame()

    normalized: list[pd.Series] = []
    for series in equity_series_list:
        sorted_series = series.sort_index()
        if sorted_series.index.has_duplicates:
            sorted_series = sorted_series.groupby(level=0).last()
        normalized.append(sorted_series)

    combined = pd.concat(normalized, axis=1).sort_index()
    return combined.ffill(limit=forward_fill_limit).fillna(0)
