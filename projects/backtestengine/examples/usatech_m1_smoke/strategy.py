"""Minimal M1 smoke-test strategy for USATECH."""

from __future__ import annotations

SYMBOL = "USATECH"
VOLUME = 0.01

_opened = False


def on_tick(engine) -> None:
    """Open one buy and one sell on the first available tick."""
    global _opened

    if _opened:
        return

    tick = engine.symbol_info_tick(SYMBOL)
    if tick is None:
        return

    engine.order_send(
        {
            "action": engine.mt5_instance.TRADE_ACTION_DEAL,
            "symbol": SYMBOL,
            "volume": VOLUME,
            "type": engine.mt5_instance.ORDER_TYPE_BUY,
            "price": tick.ask,
            "comment": "USATECH M1 buy",
        }
    )
    engine.order_send(
        {
            "action": engine.mt5_instance.TRADE_ACTION_DEAL,
            "symbol": SYMBOL,
            "volume": VOLUME,
            "type": engine.mt5_instance.ORDER_TYPE_SELL,
            "price": tick.bid,
            "comment": "USATECH M1 sell",
        }
    )
    _opened = True
