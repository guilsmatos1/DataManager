from __future__ import annotations

from typing import Any

import pandas as pd
from trademachine.tradingmonitor_analytics.metrics.utils import (
    CLOSED_TRADE_TYPES,
    net_pnl,
)
from trademachine.tradingmonitor_storage.public import Strategy


def side_type_names(side: str | None) -> list[str]:
    if side == "buy":
        return ["BUY"]
    if side == "sell":
        return ["SELL"]
    return ["BUY", "SELL"]


def synthetic_equity(
    deals_df: pd.DataFrame, balance_baseline: float | None = None
) -> pd.DataFrame:
    if deals_df.empty:
        return pd.DataFrame()
    baseline = float(balance_baseline or 0.0)
    return pd.DataFrame({"equity": net_pnl(deals_df).cumsum() + baseline})


def closed_trades(deals_df: pd.DataFrame) -> pd.DataFrame:
    if deals_df.empty or "type" not in deals_df.columns:
        return deals_df

    trading_deals = deals_df[deals_df["type"].isin(CLOSED_TRADE_TYPES)].copy()
    if trading_deals.empty:
        return trading_deals

    open_volume_by_symbol: dict[str, dict[str, float]] = {}
    closed_rows: list[tuple[object, dict[str, object]]] = []
    epsilon = 1e-9

    for timestamp, row in trading_deals.sort_index(kind="stable").iterrows():
        symbol = str(row.get("symbol") or "")
        deal_type = str(row.get("type") or "").upper()
        volume = float(row.get("volume") or 0.0)
        if volume <= epsilon or deal_type not in {"BUY", "SELL"}:
            continue

        slots = open_volume_by_symbol.setdefault(symbol, {"buy": 0.0, "sell": 0.0})
        closing_side = "sell" if deal_type == "BUY" else "buy"
        opening_side = "buy" if deal_type == "BUY" else "sell"
        closed_volume = min(volume, slots[closing_side])

        if closed_volume > epsilon:
            slots[closing_side] -= closed_volume
            ratio = closed_volume / volume
            closed_rows.append(
                (
                    timestamp,
                    {
                        "strategy_id": row.get("strategy_id"),
                        "symbol": symbol,
                        "type": deal_type,
                        "volume": closed_volume,
                        "price": float(row.get("price") or 0.0),
                        "profit": float(row.get("profit") or 0.0) * ratio,
                        "commission": float(row.get("commission") or 0.0) * ratio,
                        "swap": float(row.get("swap") or 0.0) * ratio,
                    },
                )
            )

        remaining_volume = volume - closed_volume
        if remaining_volume > epsilon:
            slots[opening_side] += remaining_volume

    if not closed_rows:
        return trading_deals.iloc[0:0].copy()

    closed_df = pd.DataFrame([row for _, row in closed_rows])
    closed_df.index = pd.Index(
        [timestamp for timestamp, _ in closed_rows], name=trading_deals.index.name
    )
    return closed_df.sort_index(kind="stable")


def closed_trades_for_side(deals_df: pd.DataFrame, side: str | None) -> pd.DataFrame:
    if side not in {"buy", "sell"}:
        return closed_trades(deals_df)

    realized_trades = closed_trades(deals_df)
    if realized_trades.empty:
        return realized_trades

    expected_type = "SELL" if side == "buy" else "BUY"
    return realized_trades[realized_trades["type"] == expected_type].copy()


def equity_points_from_deals(
    deals_df: pd.DataFrame,
    *,
    balance_baseline: float | None,
    id_field: str,
    id_value: str | int,
) -> list[dict[str, Any]]:
    if deals_df.empty:
        return []

    pnl = net_pnl(deals_df.fillna(0))
    baseline = float(balance_baseline or 0.0)
    equity = pnl.cumsum() + baseline

    points: list[dict[str, Any]] = []
    for timestamp, value in equity.items():
        point_timestamp = (
            timestamp.to_pydatetime()
            if hasattr(timestamp, "to_pydatetime")
            else timestamp
        )
        points.append(
            {
                "timestamp": point_timestamp,
                id_field: id_value,
                "balance": float(value),
                "equity": float(value),
            }
        )
    return points


def strategy_matches_history_type(strategy: Strategy, history_type: str) -> bool:
    account_type = (
        (strategy.account.account_type or "").strip().lower()
        if strategy.account
        else ""
    )
    if "demo" in account_type:
        return history_type == "demo"
    if "real" in account_type:
        return history_type == "real"
    if history_type == "real":
        return bool(strategy.real_account)
    if history_type == "demo":
        return not bool(strategy.real_account)
    return True


def compute_max_drawdown(equity_series: list[float]) -> float | None:
    if not equity_series:
        return None
    peak = equity_series[0]
    max_drawdown = 0.0
    for equity in equity_series:
        peak = max(peak, equity)
        if peak > 0:
            drawdown = (peak - equity) / peak
            max_drawdown = max(max_drawdown, drawdown)
    return max_drawdown
