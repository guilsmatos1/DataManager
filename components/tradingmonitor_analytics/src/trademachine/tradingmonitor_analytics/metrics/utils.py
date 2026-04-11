"""Shared utilities for the metrics module."""

import pandas as pd


def net_pnl(df: pd.DataFrame) -> pd.Series:
    """Return net P&L (profit + commission + swap) as a Series."""
    return df["profit"] + df["commission"] + df["swap"]
