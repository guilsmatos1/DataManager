"""Engine implementation for BacktestEngine."""

from __future__ import annotations

import inspect
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from trademachine.backtestengine.config import BacktestConfig
from trademachine.backtestengine_broker.public import (
    MT5_AVAILABLE,
    AccountInfo,
    MetaTrader5,
    SnapshotImporters,
    SymbolInfo,
    Tick,
    TradeDeal,
    TradeOrder,
    TradePosition,
    account_info_from_mt5,
    ensure_utc,
    evaluate_margin_state,
)
from trademachine.backtestengine_history.public import HistoryManager
from trademachine.backtestengine_stats.public import BacktestStats
from trademachine.core.logger import setup_logger


def _default_point(symbol: str) -> float:
    return 0.01 if symbol.endswith("JPY") else 0.0001


def _default_symbol_info(symbol: str) -> SymbolInfo:
    point = _default_point(symbol)
    digits = 3 if point == 0.01 else 5
    return SymbolInfo(
        name=symbol,
        point=point,
        digits=digits,
        bid=1.0,
        ask=1.0 + point * 10,
        description=symbol,
    )


def _default_account_info(config: BacktestConfig) -> AccountInfo:
    return AccountInfo(
        login=11223344,
        leverage=config.leverage,
        balance=config.deposit,
        equity=config.deposit,
        margin_free=config.deposit,
        margin_level=float("inf"),
        margin_so_mode=MetaTrader5.ACCOUNT_STOPOUT_MODE_PERCENT,
        trade_allowed=True,
        trade_expert=True,
        name="BacktestEngine",
        server="TradeMachine-Simulator",
        currency="USD",
        company="TradeMachine",
    )


@dataclass(slots=True)
class BacktestResult:
    """Serialized result returned by a finished run."""

    config: BacktestConfig
    stats: BacktestStats
    deals: list[TradeDeal]
    open_positions: list[TradePosition]
    pending_orders: list[TradeOrder]
    balance_curve: np.ndarray
    equity_curve: np.ndarray
    margin_level_curve: np.ndarray
    ticks_processed: int

    def to_summary_dict(self) -> dict[str, Any]:
        payload = self.stats.to_dict()
        payload.update(
            {
                "bot_name": self.config.bot_name,
                "open_positions": len(self.open_positions),
                "pending_orders": len(self.pending_orders),
            }
        )
        return payload


class BacktestEngine:
    """Offline-first strategy tester with a StrategyTester5-compatible surface."""

    def __init__(
        self,
        tester_config: BacktestConfig | dict[str, Any],
        mt5_instance: Any | None = None,
        logging_level: int = logging.WARNING,
        logs_dir: str = "Logs",
        reports_dir: str = "Reports",
        history_dir: str = "History",
        broker_data_dir: str = "ICMarketsSC-Demo",
        trading_history_dir: str = "TradingHistory",
        POLARS_COLLECT_ENGINE: str = "auto",
        use_mt5: bool | None = None,
    ):
        self.config = (
            tester_config
            if isinstance(tester_config, BacktestConfig)
            else BacktestConfig.from_legacy_dict(tester_config)
        )
        self.mt5_instance = mt5_instance or MetaTrader5
        self.POLARS_COLLECT_ENGINE = POLARS_COLLECT_ENGINE
        self.reports_dir = reports_dir
        self.history_dir = history_dir
        self.broker_data_dir = broker_data_dir
        self.trading_history_dir = trading_history_dir
        self.use_mt5 = (
            use_mt5
            if use_mt5 is not None
            else any(arg.startswith("--mt5") for arg in sys.argv)
        )

        log_path = Path(logs_dir) / f"{self.config.bot_name}.log"
        self.logger = setup_logger(
            log_path=str(log_path),
            level=logging_level,
            quiet=logging_level > logging.INFO,
        )

        self._ticket_counter = 1
        self._position_counter = 1
        self._result: BacktestResult | None = None
        self.IS_STOPPED = False
        self.TESTER_IDX = 0
        self.CURVES_IDX = 0
        self.positions_unrealized_pl = 0.0
        self.positions_total_margin = 0.0
        self.tick_cache: dict[str, Tick] = {}
        self.symbol_info_cache: dict[str, SymbolInfo] = {}
        self.trade_validators_cache: dict[str, Any] = {}
        self.__orders_container__: list[TradeOrder] = []
        self.__positions_container__: list[TradePosition] = []
        self.__deals_history_container__: list[TradeDeal] = []
        self.tester_curves: dict[str, list[float]] = {
            "time": [],
            "balance": [],
            "equity": [],
            "margin_level": [],
        }

        self.AccountInfo = self._load_account_info()
        self._load_symbol_info()
        self.TESTER_ALL_BARS_INFO, self.TESTER_ALL_TICKS_INFO = self._load_history()
        self._ticks_by_symbol = self._build_tick_streams()
        self._tick_index_by_symbol = {symbol: 0 for symbol in self.config.symbols}
        self._seed_current_ticks()
        self._append_balance_marker()
        self._record_deposit_deal()

    def _next_ticket(self) -> int:
        ticket = self._ticket_counter
        self._ticket_counter += 1
        return ticket

    def _next_position_id(self) -> int:
        position_id = self._position_counter
        self._position_counter += 1
        return position_id

    def _record_deposit_deal(self) -> None:
        deposit_deal = TradeDeal(
            ticket=self._next_ticket(),
            order=0,
            time=int(self.config.start_date.timestamp()),
            time_msc=int(self.config.start_date.timestamp() * 1000),
            type=MetaTrader5.DEAL_TYPE_BALANCE,
            entry=MetaTrader5.DEAL_ENTRY_IN,
            magic=0,
            position_id=0,
            reason=0,
            volume=0.0,
            price=0.0,
            commission=0.0,
            swap=0.0,
            profit=0.0,
            fee=0.0,
            symbol="",
            comment="Initial deposit",
            balance=self.AccountInfo.balance,
        )
        self.__deals_history_container__.append(deposit_deal)

    def _load_account_info(self) -> AccountInfo:
        importer = SnapshotImporters(self.broker_data_dir, self.logger)
        snapshot = importer.account_info()
        if snapshot is None and self.use_mt5 and MT5_AVAILABLE:
            snapshot = account_info_from_mt5(self.mt5_instance.account_info())
        if snapshot is None:
            snapshot = _default_account_info(self.config)

        return replace(
            snapshot,
            leverage=self.config.leverage,
            balance=self.config.deposit,
            equity=self.config.deposit,
            margin=0.0,
            margin_free=self.config.deposit,
            margin_level=float("inf"),
            profit=0.0,
        )

    def _load_symbol_info(self) -> None:
        importer = SnapshotImporters(self.broker_data_dir, self.logger)
        rows = importer.all_symbol_info()
        for item in rows:
            self.symbol_info_cache[item.name] = item

        if self.use_mt5 and MT5_AVAILABLE:
            for symbol in self.config.symbols:
                if symbol not in self.symbol_info_cache:
                    info = self.mt5_instance.symbol_info(symbol)
                    if info is not None:
                        self.symbol_info_cache[symbol] = SymbolInfo.from_mapping(
                            {
                                key: getattr(info, key)
                                for key in dir(info)
                                if not key.startswith("_")
                                and not callable(getattr(info, key))
                            }
                        )

        for symbol in self.config.symbols:
            self.symbol_info_cache.setdefault(symbol, _default_symbol_info(symbol))

    def _load_history(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        history_manager = HistoryManager(
            mt5_instance=self.mt5_instance,
            symbols=self.config.symbols,
            start_dt=self.config.start_date,
            end_dt=self.config.end_date,
            timeframe=self.config.timeframe,
            POLARS_COLLECT_ENGINE=self.POLARS_COLLECT_ENGINE,
            logger=self.logger,
            mt5_source=self.use_mt5,
            history_dir=self.history_dir,
        )
        return history_manager.fetch_history(
            self.config.modelling,
            symbol_info_func=self.symbol_info,
        )

    def _build_tick_streams(self) -> dict[str, list[Tick]]:
        streams: dict[str, list[Tick]] = {symbol: [] for symbol in self.config.symbols}
        for item in self.TESTER_ALL_TICKS_INFO:
            symbol = item["symbol"]
            frame = item["ticks"]
            rows = []
            if frame is not None and not frame.is_empty():
                for row in frame.iter_rows(named=True):
                    rows.append(
                        Tick(
                            time=int(row["time"]),
                            bid=float(row["bid"]),
                            ask=float(row["ask"]),
                            last=float(row["last"]),
                            volume=int(row.get("volume", 0)),
                            time_msc=int(row.get("time_msc", int(row["time"]) * 1000)),
                            flags=int(row.get("flags", -1)),
                            volume_real=float(row.get("volume_real", 0.0)),
                        )
                    )
            streams[symbol] = rows
        return streams

    def _seed_current_ticks(self) -> None:
        for symbol, ticks in self._ticks_by_symbol.items():
            if ticks:
                self.tick_cache[symbol] = ticks[0]
                info = self.symbol_info_cache[symbol]
                self.symbol_info_cache[symbol] = replace(
                    info,
                    bid=ticks[0].bid,
                    ask=ticks[0].ask,
                )

    def _append_balance_marker(self) -> None:
        self._refresh_account_snapshot()
        marker_time = (
            max((tick.time_msc for tick in self.tick_cache.values()), default=0)
            if self.tick_cache
            else int(self.config.start_date.timestamp() * 1000)
        )
        self.tester_curves["time"].append(float(marker_time))
        self.tester_curves["balance"].append(float(self.AccountInfo.balance))
        self.tester_curves["equity"].append(float(self.AccountInfo.equity))
        self.tester_curves["margin_level"].append(float(self.AccountInfo.margin_level))
        self.CURVES_IDX += 1

    def _refresh_account_snapshot(self) -> None:
        floating_profit = sum(
            self._profit_for_position(position, self.symbol_info_tick(position.symbol))
            for position in self.__positions_container__
            if self.symbol_info_tick(position.symbol) is not None
        )
        total_margin = sum(position.margin for position in self.__positions_container__)
        equity = self.AccountInfo.balance + floating_profit
        margin_free = equity - total_margin
        if total_margin > 0:
            margin_level = equity / total_margin * 100.0
        else:
            margin_level = float("inf")
        self.positions_unrealized_pl = floating_profit
        self.positions_total_margin = total_margin
        self.AccountInfo = replace(
            self.AccountInfo,
            profit=floating_profit,
            equity=equity,
            margin=total_margin,
            margin_free=margin_free,
            margin_level=margin_level,
        )

    def _profit_for_position(self, position: TradePosition, tick: Tick | None) -> float:
        if tick is None:
            return position.profit
        contract_size = self.symbol_info(position.symbol).trade_contract_size or 1.0
        if position.type == MetaTrader5.POSITION_TYPE_BUY:
            return (tick.bid - position.price_open) * position.volume * contract_size
        return (position.price_open - tick.ask) * position.volume * contract_size

    def _margin_for_position(self, symbol: str, volume: float, price: float) -> float:
        contract_size = self.symbol_info(symbol).trade_contract_size or 1.0
        leverage = max(1, self.AccountInfo.leverage)
        return price * volume * contract_size / leverage

    def _create_open_deal(
        self,
        *,
        position_id: int,
        order_ticket: int,
        symbol: str,
        order_type: int,
        volume: float,
        price: float,
        comment: str,
        magic: int,
        current_tick: Tick,
    ) -> None:
        deal = TradeDeal(
            ticket=self._next_ticket(),
            order=order_ticket,
            time=current_tick.time,
            time_msc=current_tick.time_msc,
            type=MetaTrader5.DEAL_TYPE_BUY
            if order_type
            in (
                MetaTrader5.ORDER_TYPE_BUY,
                MetaTrader5.ORDER_TYPE_BUY_LIMIT,
                MetaTrader5.ORDER_TYPE_BUY_STOP,
            )
            else MetaTrader5.DEAL_TYPE_SELL,
            entry=MetaTrader5.DEAL_ENTRY_IN,
            magic=magic,
            position_id=position_id,
            reason=0,
            volume=volume,
            price=price,
            commission=0.0,
            swap=0.0,
            profit=0.0,
            fee=0.0,
            symbol=symbol,
            comment=comment,
            balance=self.AccountInfo.balance,
        )
        self.__deals_history_container__.append(deal)

    def _open_position(
        self,
        *,
        symbol: str,
        volume: float,
        order_type: int,
        price: float,
        sl: float,
        tp: float,
        comment: str,
        magic: int,
        current_tick: Tick,
        existing_ticket: int | None = None,
    ) -> TradePosition:
        ticket = existing_ticket or self._next_ticket()
        position_type = (
            MetaTrader5.POSITION_TYPE_BUY
            if order_type
            in (
                MetaTrader5.ORDER_TYPE_BUY,
                MetaTrader5.ORDER_TYPE_BUY_LIMIT,
                MetaTrader5.ORDER_TYPE_BUY_STOP,
            )
            else MetaTrader5.POSITION_TYPE_SELL
        )
        margin = self._margin_for_position(symbol, volume, price)
        position = TradePosition(
            ticket=ticket,
            time=current_tick.time,
            time_msc=current_tick.time_msc,
            time_update=current_tick.time,
            time_update_msc=current_tick.time_msc,
            type=position_type,
            magic=magic,
            identifier=self._next_position_id(),
            reason=0,
            volume=float(volume),
            price_open=float(price),
            sl=float(sl),
            tp=float(tp),
            price_current=float(price),
            swap=0.0,
            profit=0.0,
            symbol=symbol,
            comment=comment,
            margin=margin,
        )
        self.__positions_container__.append(position)
        self._create_open_deal(
            position_id=position.identifier,
            order_ticket=ticket,
            symbol=symbol,
            order_type=order_type,
            volume=volume,
            price=price,
            comment=comment,
            magic=magic,
            current_tick=current_tick,
        )
        self._refresh_account_snapshot()
        return position

    def _close_position(
        self, position: TradePosition, price: float, tick: Tick, comment: str = ""
    ) -> None:
        profit = self._profit_for_position(
            position, replace(tick, bid=price, ask=price)
        )
        self.AccountInfo = replace(
            self.AccountInfo, balance=self.AccountInfo.balance + profit
        )
        deal = TradeDeal(
            ticket=self._next_ticket(),
            order=position.ticket,
            time=tick.time,
            time_msc=tick.time_msc,
            type=MetaTrader5.DEAL_TYPE_BUY
            if position.type == MetaTrader5.POSITION_TYPE_BUY
            else MetaTrader5.DEAL_TYPE_SELL,
            entry=MetaTrader5.DEAL_ENTRY_OUT,
            magic=position.magic,
            position_id=position.identifier,
            reason=0,
            volume=position.volume,
            price=price,
            commission=0.0,
            swap=0.0,
            profit=profit,
            fee=0.0,
            symbol=position.symbol,
            comment=comment or position.comment,
            balance=self.AccountInfo.balance,
        )
        self.__deals_history_container__.append(deal)
        self.__positions_container__ = [
            current
            for current in self.__positions_container__
            if current.ticket != position.ticket
        ]
        self._refresh_account_snapshot()

    def _apply_stop_levels(self, symbol: str) -> None:
        tick = self.symbol_info_tick(symbol)
        if tick is None:
            return

        positions_to_close: list[tuple[TradePosition, float, str]] = []
        for position in self.__positions_container__:
            if position.symbol != symbol:
                continue
            if position.type == MetaTrader5.POSITION_TYPE_BUY:
                if position.sl > 0 and tick.bid <= position.sl:
                    positions_to_close.append((position, position.sl, "Stop loss"))
                elif position.tp > 0 and tick.bid >= position.tp:
                    positions_to_close.append((position, position.tp, "Take profit"))
            else:
                if position.sl > 0 and tick.ask >= position.sl:
                    positions_to_close.append((position, position.sl, "Stop loss"))
                elif position.tp > 0 and tick.ask <= position.tp:
                    positions_to_close.append((position, position.tp, "Take profit"))

        for position, price, comment in positions_to_close:
            self._close_position(position, price, tick, comment)

    def _activate_pending_orders(self, symbol: str) -> None:
        tick = self.symbol_info_tick(symbol)
        if tick is None:
            return

        remaining_orders: list[TradeOrder] = []
        for order in self.__orders_container__:
            if order.symbol != symbol:
                remaining_orders.append(order)
                continue

            price = order.price_open
            should_fill = False
            if order.type == MetaTrader5.ORDER_TYPE_BUY_LIMIT:
                should_fill = tick.ask <= price
            elif order.type == MetaTrader5.ORDER_TYPE_SELL_LIMIT:
                should_fill = tick.bid >= price
            elif order.type == MetaTrader5.ORDER_TYPE_BUY_STOP:
                should_fill = tick.ask >= price
            elif order.type == MetaTrader5.ORDER_TYPE_SELL_STOP:
                should_fill = tick.bid <= price

            if should_fill:
                self._open_position(
                    symbol=order.symbol,
                    volume=order.volume_current,
                    order_type=order.type,
                    price=order.price_open,
                    sl=order.sl,
                    tp=order.tp,
                    comment=order.comment,
                    magic=order.magic,
                    current_tick=tick,
                    existing_ticket=order.ticket,
                )
            else:
                remaining_orders.append(order)

        self.__orders_container__ = remaining_orders

    def _advance_tick(self) -> tuple[str | None, Tick | None]:
        next_symbol: str | None = None
        next_tick: Tick | None = None
        for symbol, ticks in self._ticks_by_symbol.items():
            index = self._tick_index_by_symbol[symbol]
            if index >= len(ticks):
                continue
            candidate = ticks[index]
            if next_tick is None or (candidate.time_msc, symbol) < (
                next_tick.time_msc,
                next_symbol or symbol,
            ):
                next_symbol = symbol
                next_tick = candidate

        if next_symbol is None or next_tick is None:
            return None, None

        self._tick_index_by_symbol[next_symbol] += 1
        self.tick_cache[next_symbol] = next_tick
        info = self.symbol_info_cache[next_symbol]
        self.symbol_info_cache[next_symbol] = replace(
            info,
            bid=next_tick.bid,
            ask=next_tick.ask,
        )
        return next_symbol, next_tick

    def _invoke_callback(self, callback: Callable[..., Any]) -> None:
        parameters = inspect.signature(callback).parameters
        if len(parameters) == 0:
            callback()
        else:
            callback(self)

    def symbol_info(self, symbol: str) -> SymbolInfo:
        return self.symbol_info_cache[symbol]

    def symbol_info_tick(self, symbol: str) -> Tick | None:
        return self.tick_cache.get(symbol)

    def positions_get(self) -> tuple[TradePosition, ...]:
        return tuple(self.__positions_container__)

    def orders_get(self) -> tuple[TradeOrder, ...]:
        return tuple(self.__orders_container__)

    def history_deals_get(self) -> tuple[TradeDeal, ...]:
        return tuple(self.__deals_history_container__)

    def account_info(self) -> AccountInfo:
        return self.AccountInfo

    def position_close(self, ticket: int, price: float | None = None) -> bool:
        for position in self.__positions_container__:
            if position.ticket != ticket:
                continue
            tick = self.symbol_info_tick(position.symbol)
            if tick is None:
                return False
            close_price = price
            if close_price is None:
                close_price = (
                    tick.bid
                    if position.type == MetaTrader5.POSITION_TYPE_BUY
                    else tick.ask
                )
            self._close_position(position, float(close_price), tick, "Manual close")
            return True
        return False

    def stop(self) -> None:
        self.IS_STOPPED = True

    def order_send(self, request: dict[str, Any]) -> dict[str, Any] | None:
        symbol = request.get("symbol")
        if not symbol:
            return None
        tick = self.symbol_info_tick(symbol)
        if tick is None:
            return None

        action = request["action"]
        order_type = int(request["type"])
        volume = float(request.get("volume", 0.0))
        price = float(
            request.get(
                "price",
                tick.ask
                if order_type
                in (
                    MetaTrader5.ORDER_TYPE_BUY,
                    MetaTrader5.ORDER_TYPE_BUY_STOP,
                    MetaTrader5.ORDER_TYPE_BUY_LIMIT,
                )
                else tick.bid,
            )
        )
        sl = float(request.get("sl", 0.0))
        tp = float(request.get("tp", 0.0))
        comment = str(request.get("comment", ""))
        magic = int(request.get("magic", 0))
        ticket = self._next_ticket()

        if action == MetaTrader5.TRADE_ACTION_DEAL:
            position = self._open_position(
                symbol=symbol,
                volume=volume,
                order_type=order_type,
                price=price,
                sl=sl,
                tp=tp,
                comment=comment,
                magic=magic,
                current_tick=tick,
                existing_ticket=ticket,
            )
            return {
                "retcode": MetaTrader5.TRADE_RETCODE_DONE,
                "order": position.ticket,
                "price": price,
            }

        if action == MetaTrader5.TRADE_ACTION_PENDING:
            order = TradeOrder(
                ticket=ticket,
                time_setup=tick.time,
                time_setup_msc=tick.time_msc,
                time_done=0,
                time_done_msc=0,
                time_expiration=int(request.get("expiration", 0) or 0),
                type=order_type,
                type_time=int(request.get("type_time", MetaTrader5.ORDER_TIME_GTC)),
                type_filling=int(
                    request.get("type_filling", MetaTrader5.ORDER_FILLING_FOK)
                ),
                state=MetaTrader5.ORDER_STATE_PLACED,
                magic=magic,
                position_id=0,
                position_by_id=0,
                reason=0,
                volume_initial=volume,
                volume_current=volume,
                price_open=price,
                sl=sl,
                tp=tp,
                price_current=price,
                price_stoplimit=float(request.get("stoplimit", 0.0)),
                symbol=symbol,
                comment=comment,
            )
            self.__orders_container__.append(order)
            return {
                "retcode": MetaTrader5.TRADE_RETCODE_DONE,
                "order": order.ticket,
                "price": price,
            }

        if action == MetaTrader5.TRADE_ACTION_REMOVE:
            order_ticket = int(request.get("order", 0))
            before = len(self.__orders_container__)
            self.__orders_container__ = [
                order
                for order in self.__orders_container__
                if order.ticket != order_ticket
            ]
            if len(self.__orders_container__) < before:
                return {
                    "retcode": MetaTrader5.TRADE_RETCODE_DONE,
                    "order": order_ticket,
                }
            return None

        return None

    def build_result(self) -> BacktestResult:
        if self._result is not None:
            return self._result

        stats = BacktestStats(
            deals=list(self.__deals_history_container__),
            initial_deposit=self.config.deposit,
            balance_curve=np.asarray(self.tester_curves["balance"], dtype=float),
            equity_curve=np.asarray(self.tester_curves["equity"], dtype=float),
            margin_level_curve=np.asarray(
                self.tester_curves["margin_level"], dtype=float
            ),
            ticks=self.TESTER_IDX,
            symbols=len(self.config.symbols),
        )
        self._result = BacktestResult(
            config=self.config,
            stats=stats,
            deals=list(self.__deals_history_container__),
            open_positions=list(self.__positions_container__),
            pending_orders=list(self.__orders_container__),
            balance_curve=np.asarray(self.tester_curves["balance"], dtype=float),
            equity_curve=np.asarray(self.tester_curves["equity"], dtype=float),
            margin_level_curve=np.asarray(
                self.tester_curves["margin_level"], dtype=float
            ),
            ticks_processed=self.TESTER_IDX,
        )
        return self._result

    def OnTick(self, ontick_func: Callable[..., Any] | None = None) -> BacktestResult:
        """Runs the event loop using the StrategyTester5-compatible method name."""
        callback = ontick_func or (lambda *_args, **_kwargs: None)
        while not self.IS_STOPPED:
            symbol, tick = self._advance_tick()
            if symbol is None or tick is None:
                break
            self._activate_pending_orders(symbol)
            self._apply_stop_levels(symbol)
            self._invoke_callback(callback)
            self._apply_stop_levels(symbol)
            self._refresh_account_snapshot()
            margin_event = evaluate_margin_state(self.AccountInfo)
            if margin_event.state == "STOP_OUT" and self.__positions_container__:
                for position in list(self.__positions_container__):
                    current_tick = self.symbol_info_tick(position.symbol)
                    if current_tick is None:
                        continue
                    close_price = (
                        current_tick.bid
                        if position.type == MetaTrader5.POSITION_TYPE_BUY
                        else current_tick.ask
                    )
                    self._close_position(
                        position, close_price, current_tick, "Stop out"
                    )
            self._append_balance_marker()
            self.TESTER_IDX += 1

        for position in list(self.__positions_container__):
            current_tick = self.symbol_info_tick(position.symbol)
            if current_tick is None:
                continue
            close_price = (
                current_tick.bid
                if position.type == MetaTrader5.POSITION_TYPE_BUY
                else current_tick.ask
            )
            self._close_position(position, close_price, current_tick, "End of backtest")
        self._append_balance_marker()
        return self.build_result()

    def run(self, ontick_func: Callable[..., Any] | None = None) -> BacktestResult:
        """Preferred explicit alias for OnTick."""
        return self.OnTick(ontick_func=ontick_func)


class TradeExecutor:
    """Thin compatibility wrapper similar to StrategyTester5's CTrade."""

    def __init__(
        self,
        simulator: BacktestEngine,
        magic_number: int,
        filling_type_symbol: str,
        deviation_points: int,
    ):
        self.simulator = simulator
        self.mt5_instance = simulator.mt5_instance
        self.magic_number = magic_number
        self.deviation_points = deviation_points
        self.filling_type = self._get_type_filling(filling_type_symbol)

    def _get_type_filling(self, symbol: str) -> int:
        symbol_info = self.simulator.symbol_info(symbol)
        filling_map = {
            1: self.mt5_instance.ORDER_FILLING_FOK,
            2: self.mt5_instance.ORDER_FILLING_IOC,
            4: self.mt5_instance.ORDER_FILLING_BOC,
            8: self.mt5_instance.ORDER_FILLING_RETURN,
        }
        return filling_map.get(
            symbol_info.filling_mode, self.mt5_instance.ORDER_FILLING_FOK
        )

    def position_open(
        self,
        symbol: str,
        volume: float,
        order_type: int,
        price: float,
        sl: float = 0.0,
        tp: float = 0.0,
        comment: str = "",
    ) -> bool:
        request = {
            "action": self.mt5_instance.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "deviation": self.deviation_points,
            "magic": self.magic_number,
            "comment": comment,
            "type_time": self.mt5_instance.ORDER_TIME_GTC,
            "type_filling": self.filling_type,
            "sl": sl,
            "tp": tp,
        }
        return self.simulator.order_send(request) is not None

    def order_open(
        self,
        symbol: str,
        volume: float,
        order_type: int,
        price: float,
        sl: float = 0.0,
        tp: float = 0.0,
        type_time: int = MetaTrader5.ORDER_TIME_GTC,
        expiration: datetime | None = None,
        comment: str = "",
    ) -> bool:
        expiration_value = 0
        if expiration is not None:
            expiration_value = int(ensure_utc(expiration).timestamp() * 1000)
        request = {
            "action": self.mt5_instance.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "deviation": self.deviation_points,
            "magic": self.magic_number,
            "comment": comment,
            "type_time": type_time,
            "type_filling": self.filling_type,
            "expiration": expiration_value,
            "sl": sl,
            "tp": tp,
        }
        return self.simulator.order_send(request) is not None

    def buy(
        self,
        volume: float,
        symbol: str,
        price: float,
        sl: float = 0.0,
        tp: float = 0.0,
        comment: str = "",
    ) -> bool:
        return self.position_open(
            symbol, volume, self.mt5_instance.ORDER_TYPE_BUY, price, sl, tp, comment
        )

    def sell(
        self,
        volume: float,
        symbol: str,
        price: float,
        sl: float = 0.0,
        tp: float = 0.0,
        comment: str = "",
    ) -> bool:
        return self.position_open(
            symbol, volume, self.mt5_instance.ORDER_TYPE_SELL, price, sl, tp, comment
        )

    def buy_limit(
        self,
        volume: float,
        price: float,
        symbol: str,
        sl: float = 0.0,
        tp: float = 0.0,
        type_time: int = MetaTrader5.ORDER_TIME_GTC,
        expiration: datetime | None = None,
        comment: str = "",
    ) -> bool:
        return self.order_open(
            symbol,
            volume,
            self.mt5_instance.ORDER_TYPE_BUY_LIMIT,
            price,
            sl,
            tp,
            type_time,
            expiration,
            comment,
        )

    def sell_limit(
        self,
        volume: float,
        price: float,
        symbol: str,
        sl: float = 0.0,
        tp: float = 0.0,
        type_time: int = MetaTrader5.ORDER_TIME_GTC,
        expiration: datetime | None = None,
        comment: str = "",
    ) -> bool:
        return self.order_open(
            symbol,
            volume,
            self.mt5_instance.ORDER_TYPE_SELL_LIMIT,
            price,
            sl,
            tp,
            type_time,
            expiration,
            comment,
        )

    def buy_stop(
        self,
        volume: float,
        price: float,
        symbol: str,
        sl: float = 0.0,
        tp: float = 0.0,
        type_time: int = MetaTrader5.ORDER_TIME_GTC,
        expiration: datetime | None = None,
        comment: str = "",
    ) -> bool:
        return self.order_open(
            symbol,
            volume,
            self.mt5_instance.ORDER_TYPE_BUY_STOP,
            price,
            sl,
            tp,
            type_time,
            expiration,
            comment,
        )

    def sell_stop(
        self,
        volume: float,
        price: float,
        symbol: str,
        sl: float = 0.0,
        tp: float = 0.0,
        type_time: int = MetaTrader5.ORDER_TIME_GTC,
        expiration: datetime | None = None,
        comment: str = "",
    ) -> bool:
        return self.order_open(
            symbol,
            volume,
            self.mt5_instance.ORDER_TYPE_SELL_STOP,
            price,
            sl,
            tp,
            type_time,
            expiration,
            comment,
        )

    def close(self, ticket: int, price: float | None = None) -> bool:
        return self.simulator.position_close(ticket=ticket, price=price)


def run_backtest(
    config: BacktestConfig | dict[str, Any] | str | Path,
    strategy: Callable[..., Any] | None = None,
    **engine_kwargs: Any,
) -> BacktestResult:
    """Convenience helper used by the CLI and external integrations."""
    if isinstance(config, str | Path):
        parsed_config = BacktestConfig.from_json_file(config)
    elif isinstance(config, BacktestConfig):
        parsed_config = config
    else:
        parsed_config = BacktestConfig.from_legacy_dict(config)

    engine = BacktestEngine(tester_config=parsed_config, **engine_kwargs)
    return engine.run(strategy)
