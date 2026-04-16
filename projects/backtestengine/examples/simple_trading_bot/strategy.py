"""Smoke-test strategy adapted from StrategyTester5's simple trading bot."""

from __future__ import annotations

from trademachine.backtestengine.public import MetaTrader5, TradeExecutor

SYMBOL = "EURUSD"
MAGIC_NUMBER = 10012026
SLIPPAGE = 100
STOP_LOSS_POINTS = 700
TAKE_PROFIT_POINTS = 500

_trade: TradeExecutor | None = None


def _pos_exists(engine, magic: int, position_type: int) -> bool:
    for position in engine.positions_get():
        if position.type == position_type and position.magic == magic:
            return True
    return False


def on_tick(engine) -> None:
    """Opens a buy and a sell if they don't exist yet, like the original example."""
    global _trade

    if _trade is None:
        _trade = TradeExecutor(
            simulator=engine,
            magic_number=MAGIC_NUMBER,
            filling_type_symbol=SYMBOL,
            deviation_points=SLIPPAGE,
        )

    tick_info = engine.symbol_info_tick(symbol=SYMBOL)
    if tick_info is None:
        return

    symbol_info = engine.symbol_info(symbol=SYMBOL)
    ask = tick_info.ask
    bid = tick_info.bid
    point = symbol_info.point

    if not _pos_exists(
        engine, magic=MAGIC_NUMBER, position_type=MetaTrader5.POSITION_TYPE_BUY
    ):
        _trade.buy(
            volume=0.01,
            symbol=SYMBOL,
            price=ask,
            sl=ask - STOP_LOSS_POINTS * point,
            tp=ask + TAKE_PROFIT_POINTS * point,
            comment="Tester buy",
        )

    if not _pos_exists(
        engine, magic=MAGIC_NUMBER, position_type=MetaTrader5.POSITION_TYPE_SELL
    ):
        _trade.sell(
            volume=0.01,
            symbol=SYMBOL,
            price=bid,
            sl=bid + STOP_LOSS_POINTS * point,
            tp=bid - TAKE_PROFIT_POINTS * point,
            comment="Tester sell",
        )
