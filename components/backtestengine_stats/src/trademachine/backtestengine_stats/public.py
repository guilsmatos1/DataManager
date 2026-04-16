"""Public API for backtest statistics."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from trademachine.backtestengine_broker.public import MetaTrader5, TradeDeal


def _max_drawdown(curve: np.ndarray) -> tuple[float, float]:
    if curve.size == 0:
        return 0.0, 0.0
    running_peak = np.maximum.accumulate(curve)
    drawdowns = running_peak - curve
    max_drawdown = float(drawdowns.max(initial=0.0))
    if running_peak.size == 0:
        return max_drawdown, 0.0
    peak_index = int(drawdowns.argmax()) if drawdowns.size else 0
    peak_value = float(running_peak[peak_index]) if running_peak.size else 0.0
    pct = 0.0 if peak_value <= 0 else (max_drawdown / peak_value) * 100.0
    return max_drawdown, pct


@dataclass(slots=True)
class BacktestStats:
    """Aggregated performance statistics."""

    deals: list[TradeDeal]
    initial_deposit: float
    balance_curve: np.ndarray
    equity_curve: np.ndarray
    margin_level_curve: np.ndarray
    ticks: int
    symbols: int
    _closed_deals: list[TradeDeal] = field(init=False, repr=False)
    _profits: np.ndarray = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.balance_curve = np.asarray(self.balance_curve, dtype=float)
        self.equity_curve = np.asarray(self.equity_curve, dtype=float)
        self.margin_level_curve = np.asarray(self.margin_level_curve, dtype=float)

        self._closed_deals = [
            deal for deal in self.deals if deal.entry == MetaTrader5.DEAL_ENTRY_OUT
        ]
        self._profits = np.asarray(
            [deal.profit + deal.commission for deal in self._closed_deals], dtype=float
        )

    @property
    def total_trades(self) -> int:
        return len(self._closed_deals)

    @property
    def total_deals(self) -> int:
        return len(self.deals)

    @property
    def total_long_trades(self) -> int:
        return sum(
            1 for deal in self._closed_deals if deal.type == MetaTrader5.DEAL_TYPE_BUY
        )

    @property
    def total_short_trades(self) -> int:
        return sum(
            1 for deal in self._closed_deals if deal.type == MetaTrader5.DEAL_TYPE_SELL
        )

    @property
    def gross_profit(self) -> float:
        if self._profits.size == 0:
            return 0.0
        return float(self._profits[self._profits > 0].sum())

    @property
    def gross_loss(self) -> float:
        if self._profits.size == 0:
            return 0.0
        return float(abs(self._profits[self._profits < 0].sum()))

    @property
    def net_profit(self) -> float:
        if self._profits.size == 0:
            return 0.0
        return float(self._profits.sum())

    @property
    def win_rate(self) -> float:
        if self._profits.size == 0:
            return 0.0
        wins = float((self._profits > 0).sum())
        return wins / float(self._profits.size) * 100.0

    @property
    def expected_payoff(self) -> float:
        if self._profits.size == 0:
            return 0.0
        return float(self._profits.mean())

    @property
    def profit_factor(self) -> float:
        gross_loss = self.gross_loss
        if gross_loss == 0.0:
            return float("inf") if self.gross_profit > 0 else 0.0
        return self.gross_profit / gross_loss

    @property
    def max_drawdown_money(self) -> float:
        value, _ = _max_drawdown(self.balance_curve)
        return value

    @property
    def max_drawdown_pct(self) -> float:
        _, pct = _max_drawdown(self.balance_curve)
        return pct

    @property
    def final_balance(self) -> float:
        if self.balance_curve.size == 0:
            return float(self.initial_deposit)
        return float(self.balance_curve[-1])

    @property
    def final_equity(self) -> float:
        if self.equity_curve.size == 0:
            return float(self.initial_deposit)
        return float(self.equity_curve[-1])

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticks": self.ticks,
            "symbols": self.symbols,
            "total_deals": self.total_deals,
            "total_trades": self.total_trades,
            "total_long_trades": self.total_long_trades,
            "total_short_trades": self.total_short_trades,
            "gross_profit": self.gross_profit,
            "gross_loss": self.gross_loss,
            "net_profit": self.net_profit,
            "win_rate": self.win_rate,
            "expected_payoff": self.expected_payoff,
            "profit_factor": self.profit_factor,
            "max_drawdown_money": self.max_drawdown_money,
            "max_drawdown_pct": self.max_drawdown_pct,
            "final_balance": self.final_balance,
            "final_equity": self.final_equity,
        }


__all__ = ["BacktestStats"]
