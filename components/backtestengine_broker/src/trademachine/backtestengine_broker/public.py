"""Public API for broker models and MT5-like compatibility."""

from __future__ import annotations

import json
import logging
from calendar import monthrange
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class _MetaTrader5Fallback:
    """Tiny offline-compatible subset of the MetaTrader5 API."""

    TIMEFRAME_M1 = 1
    TIMEFRAME_M2 = 2
    TIMEFRAME_M3 = 3
    TIMEFRAME_M4 = 4
    TIMEFRAME_M5 = 5
    TIMEFRAME_M6 = 6
    TIMEFRAME_M10 = 10
    TIMEFRAME_M12 = 12
    TIMEFRAME_M15 = 15
    TIMEFRAME_M20 = 20
    TIMEFRAME_M30 = 30
    TIMEFRAME_H1 = 60
    TIMEFRAME_H2 = 120
    TIMEFRAME_H3 = 180
    TIMEFRAME_H4 = 240
    TIMEFRAME_H6 = 360
    TIMEFRAME_H8 = 480
    TIMEFRAME_H12 = 720
    TIMEFRAME_D1 = 1440
    TIMEFRAME_W1 = 10080
    TIMEFRAME_MN1 = 43200

    COPY_TICKS_ALL = 0

    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TYPE_BUY_LIMIT = 2
    ORDER_TYPE_SELL_LIMIT = 3
    ORDER_TYPE_BUY_STOP = 4
    ORDER_TYPE_SELL_STOP = 5
    ORDER_TYPE_BUY_STOP_LIMIT = 6
    ORDER_TYPE_SELL_STOP_LIMIT = 7

    POSITION_TYPE_BUY = 0
    POSITION_TYPE_SELL = 1

    DEAL_ENTRY_IN = 0
    DEAL_ENTRY_OUT = 1
    DEAL_TYPE_BUY = 0
    DEAL_TYPE_SELL = 1
    DEAL_TYPE_BALANCE = 2

    TRADE_ACTION_DEAL = 1
    TRADE_ACTION_PENDING = 5
    TRADE_ACTION_SLTP = 6
    TRADE_ACTION_MODIFY = 7
    TRADE_ACTION_REMOVE = 8

    ORDER_TIME_GTC = 0
    ORDER_TIME_DAY = 1
    ORDER_TIME_SPECIFIED = 2
    ORDER_TIME_SPECIFIED_DAY = 3

    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_BOC = 2
    ORDER_FILLING_RETURN = 3

    ORDER_STATE_STARTED = 0
    ORDER_STATE_FILLED = 4
    ORDER_STATE_CANCELED = 5
    ORDER_STATE_PLACED = 7

    TRADE_RETCODE_DONE = 10009

    ACCOUNT_STOPOUT_MODE_PERCENT = 0
    ACCOUNT_STOPOUT_MODE_MONEY = 1

    def initialize(self) -> bool:
        return False

    def last_error(self) -> tuple[int, str]:
        return (-1, "MetaTrader5 module is not installed")


try:
    import MetaTrader5 as _mt5

    MetaTrader5 = _mt5
    MT5_AVAILABLE = True
except ImportError:
    MetaTrader5 = _MetaTrader5Fallback()
    MT5_AVAILABLE = False


SUPPORTED_TESTER_MODELLING = {
    "every_tick",
    "real_ticks",
    "new_bar",
    "1-minute-ohlc",
}

REQUIRED_TESTER_CONFIG_KEYS = {
    "bot_name",
    "symbols",
    "timeframe",
    "start_date",
    "end_date",
    "modelling",
    "deposit",
    "leverage",
}

STRING2TIMEFRAME_MAP = {
    "M1": MetaTrader5.TIMEFRAME_M1,
    "M2": MetaTrader5.TIMEFRAME_M2,
    "M3": MetaTrader5.TIMEFRAME_M3,
    "M4": MetaTrader5.TIMEFRAME_M4,
    "M5": MetaTrader5.TIMEFRAME_M5,
    "M6": MetaTrader5.TIMEFRAME_M6,
    "M10": MetaTrader5.TIMEFRAME_M10,
    "M12": MetaTrader5.TIMEFRAME_M12,
    "M15": MetaTrader5.TIMEFRAME_M15,
    "M20": MetaTrader5.TIMEFRAME_M20,
    "M30": MetaTrader5.TIMEFRAME_M30,
    "H1": MetaTrader5.TIMEFRAME_H1,
    "H2": MetaTrader5.TIMEFRAME_H2,
    "H3": MetaTrader5.TIMEFRAME_H3,
    "H4": MetaTrader5.TIMEFRAME_H4,
    "H6": MetaTrader5.TIMEFRAME_H6,
    "H8": MetaTrader5.TIMEFRAME_H8,
    "H12": MetaTrader5.TIMEFRAME_H12,
    "D1": MetaTrader5.TIMEFRAME_D1,
    "W1": MetaTrader5.TIMEFRAME_W1,
    "MN1": MetaTrader5.TIMEFRAME_MN1,
}

TIMEFRAME2STRING_MAP = {value: key for key, value in STRING2TIMEFRAME_MAP.items()}

ORDER_TYPE_MAP = {
    MetaTrader5.ORDER_TYPE_BUY: "BUY",
    MetaTrader5.ORDER_TYPE_SELL: "SELL",
    MetaTrader5.ORDER_TYPE_BUY_LIMIT: "BUY_LIMIT",
    MetaTrader5.ORDER_TYPE_SELL_LIMIT: "SELL_LIMIT",
    MetaTrader5.ORDER_TYPE_BUY_STOP: "BUY_STOP",
    MetaTrader5.ORDER_TYPE_SELL_STOP: "SELL_STOP",
    MetaTrader5.ORDER_TYPE_BUY_STOP_LIMIT: "BUY_STOP_LIMIT",
    MetaTrader5.ORDER_TYPE_SELL_STOP_LIMIT: "SELL_STOP_LIMIT",
}

DEAL_TYPE_MAP = {
    MetaTrader5.DEAL_TYPE_BUY: "BUY",
    MetaTrader5.DEAL_TYPE_SELL: "SELL",
    MetaTrader5.DEAL_TYPE_BALANCE: "BALANCE",
}

BUY_ACTIONS = {
    MetaTrader5.ORDER_TYPE_BUY,
    MetaTrader5.ORDER_TYPE_BUY_LIMIT,
    MetaTrader5.ORDER_TYPE_BUY_STOP,
    MetaTrader5.ORDER_TYPE_BUY_STOP_LIMIT,
}

SELL_ACTIONS = {
    MetaTrader5.ORDER_TYPE_SELL,
    MetaTrader5.ORDER_TYPE_SELL_LIMIT,
    MetaTrader5.ORDER_TYPE_SELL_STOP,
    MetaTrader5.ORDER_TYPE_SELL_STOP_LIMIT,
}


def no_mt5_runtime_error() -> None:
    """Raises a descriptive error when the MT5 binding is unavailable."""
    if not MT5_AVAILABLE:
        raise RuntimeError(
            "MetaTrader5 is not installed. Use offline mode or install the MT5 binding."
        )


def ensure_utc(value: datetime) -> datetime:
    """Normalizes a datetime to UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def month_bounds(value: datetime) -> tuple[datetime, datetime]:
    """Returns UTC month start/end for a datetime."""
    current = ensure_utc(value)
    start = datetime(current.year, current.month, 1, tzinfo=UTC)
    last_day = monthrange(current.year, current.month)[1]
    end = datetime(current.year, current.month, last_day, 23, 59, 59, tzinfo=UTC)
    return start, end


def period_seconds(period: int) -> int:
    """Converts a timeframe constant into seconds."""
    return int(period) * 60


def PeriodSeconds(period: int) -> int:
    """Legacy compatibility alias."""
    return period_seconds(period)


@dataclass(frozen=True, slots=True)
class Tick:
    """MT5-like tick information."""

    time: int
    bid: float
    ask: float
    last: float
    volume: int = 0
    time_msc: int = 0
    flags: int = -1
    volume_real: float = 0.0

    def _asdict(self) -> dict[str, Any]:
        return asdict(self)


def make_tick(
    time: int | datetime,
    bid: float,
    ask: float,
    last: float = 0.0,
    volume: int = 0,
    time_msc: int = 0,
    flags: int = -1,
    volume_real: float = 0.0,
) -> Tick:
    """Builds a normalized tick structure."""
    if isinstance(time, datetime):
        utc_time = ensure_utc(time)
        timestamp = int(utc_time.timestamp())
        millis = int(utc_time.timestamp() * 1000)
        return Tick(
            time=timestamp,
            bid=float(bid),
            ask=float(ask),
            last=float(last or bid),
            volume=int(volume),
            time_msc=int(time_msc or millis),
            flags=int(flags),
            volume_real=float(volume_real),
        )

    tick_seconds = int(time)
    return Tick(
        time=tick_seconds,
        bid=float(bid),
        ask=float(ask),
        last=float(last or bid),
        volume=int(volume),
        time_msc=int(time_msc or tick_seconds * 1000),
        flags=int(flags),
        volume_real=float(volume_real),
    )


def make_tick_from_dict(data: dict[str, Any]) -> Tick:
    """Builds a tick from a mapping."""
    return make_tick(
        time=data["time"],
        bid=data.get("bid", 0.0),
        ask=data.get("ask", 0.0),
        last=data.get("last", 0.0),
        volume=data.get("volume", 0),
        time_msc=data.get("time_msc", 0),
        flags=data.get("flags", -1),
        volume_real=data.get("volume_real", 0.0),
    )


def make_tick_from_tuple(data: tuple[Any, ...]) -> Tick:
    """Builds a tick from a tuple."""
    if len(data) < 8:
        raise ValueError("Tick tuple must contain at least 8 values")
    return make_tick(
        time=data[0],
        bid=data[1],
        ask=data[2],
        last=data[3],
        volume=data[4],
        time_msc=data[5],
        flags=data[6],
        volume_real=data[7],
    )


def _value_or_default(data: dict[str, Any], key: str, default: Any) -> Any:
    value = data.get(key, default)
    if value is None:
        return default
    return value


@dataclass(frozen=True, slots=True)
class SymbolInfo:
    """Compact symbol snapshot with raw MT5 data fallback."""

    name: str
    point: float = 0.0001
    trade_contract_size: float = 100000.0
    filling_mode: int = 1
    digits: int = 5
    volume_min: float = 0.01
    volume_max: float = 100.0
    volume_step: float = 0.01
    trade_stops_level: int = 0
    visible: bool = True
    bid: float = 0.0
    ask: float = 0.0
    description: str = ""
    currency_profit: str = ""
    currency_margin: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> SymbolInfo:
        normalized = dict(data)
        name = str(normalized.get("name") or normalized.get("symbol") or "")
        known = {
            "name",
            "point",
            "trade_contract_size",
            "filling_mode",
            "digits",
            "volume_min",
            "volume_max",
            "volume_step",
            "trade_stops_level",
            "visible",
            "bid",
            "ask",
            "description",
            "currency_profit",
            "currency_margin",
        }
        raw = {key: value for key, value in normalized.items() if key not in known}
        return cls(
            name=name,
            point=float(_value_or_default(normalized, "point", 0.0001)),
            trade_contract_size=float(
                _value_or_default(normalized, "trade_contract_size", 100000.0)
            ),
            filling_mode=int(_value_or_default(normalized, "filling_mode", 1)),
            digits=int(_value_or_default(normalized, "digits", 5)),
            volume_min=float(_value_or_default(normalized, "volume_min", 0.01)),
            volume_max=float(_value_or_default(normalized, "volume_max", 100.0)),
            volume_step=float(_value_or_default(normalized, "volume_step", 0.01)),
            trade_stops_level=int(
                _value_or_default(normalized, "trade_stops_level", 0)
            ),
            visible=bool(_value_or_default(normalized, "visible", True)),
            bid=float(_value_or_default(normalized, "bid", 0.0)),
            ask=float(_value_or_default(normalized, "ask", 0.0)),
            description=str(_value_or_default(normalized, "description", "")),
            currency_profit=str(_value_or_default(normalized, "currency_profit", "")),
            currency_margin=str(_value_or_default(normalized, "currency_margin", "")),
            raw=raw,
        )

    def __getattr__(self, item: str) -> Any:
        try:
            return self.raw[item]
        except KeyError as exc:
            raise AttributeError(item) from exc

    def to_mapping(self) -> dict[str, Any]:
        payload = dict(self.raw)
        payload.update(
            {
                "name": self.name,
                "point": self.point,
                "trade_contract_size": self.trade_contract_size,
                "filling_mode": self.filling_mode,
                "digits": self.digits,
                "volume_min": self.volume_min,
                "volume_max": self.volume_max,
                "volume_step": self.volume_step,
                "trade_stops_level": self.trade_stops_level,
                "visible": self.visible,
                "bid": self.bid,
                "ask": self.ask,
                "description": self.description,
                "currency_profit": self.currency_profit,
                "currency_margin": self.currency_margin,
            }
        )
        return payload

    def _asdict(self) -> dict[str, Any]:
        return self.to_mapping()


@dataclass(frozen=True, slots=True)
class AccountInfo:
    """Compact account snapshot with raw MT5 data fallback."""

    login: int = 0
    trade_mode: int = 0
    leverage: int = 100
    limit_orders: int = 0
    margin_so_mode: int = 0
    trade_allowed: bool = True
    trade_expert: bool = True
    margin_mode: int = 0
    currency_digits: int = 2
    fifo_close: bool = False
    balance: float = 0.0
    credit: float = 0.0
    profit: float = 0.0
    equity: float = 0.0
    margin: float = 0.0
    margin_free: float = 0.0
    margin_level: float = 0.0
    margin_so_call: float = 0.0
    margin_so_so: float = 0.0
    margin_initial: float = 0.0
    margin_maintenance: float = 0.0
    assets: float = 0.0
    liabilities: float = 0.0
    commission_blocked: float = 0.0
    name: str = "TradeMachine"
    server: str = "BacktestEngine"
    currency: str = "USD"
    company: str = "TradeMachine"
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> AccountInfo:
        normalized = dict(data)
        known = {
            "login",
            "trade_mode",
            "leverage",
            "limit_orders",
            "margin_so_mode",
            "trade_allowed",
            "trade_expert",
            "margin_mode",
            "currency_digits",
            "fifo_close",
            "balance",
            "credit",
            "profit",
            "equity",
            "margin",
            "margin_free",
            "margin_level",
            "margin_so_call",
            "margin_so_so",
            "margin_initial",
            "margin_maintenance",
            "assets",
            "liabilities",
            "commission_blocked",
            "name",
            "server",
            "currency",
            "company",
        }
        raw = {key: value for key, value in normalized.items() if key not in known}
        return cls(
            login=int(_value_or_default(normalized, "login", 0)),
            trade_mode=int(_value_or_default(normalized, "trade_mode", 0)),
            leverage=int(_value_or_default(normalized, "leverage", 100)),
            limit_orders=int(_value_or_default(normalized, "limit_orders", 0)),
            margin_so_mode=int(_value_or_default(normalized, "margin_so_mode", 0)),
            trade_allowed=bool(_value_or_default(normalized, "trade_allowed", True)),
            trade_expert=bool(_value_or_default(normalized, "trade_expert", True)),
            margin_mode=int(_value_or_default(normalized, "margin_mode", 0)),
            currency_digits=int(_value_or_default(normalized, "currency_digits", 2)),
            fifo_close=bool(_value_or_default(normalized, "fifo_close", False)),
            balance=float(_value_or_default(normalized, "balance", 0.0)),
            credit=float(_value_or_default(normalized, "credit", 0.0)),
            profit=float(_value_or_default(normalized, "profit", 0.0)),
            equity=float(_value_or_default(normalized, "equity", 0.0)),
            margin=float(_value_or_default(normalized, "margin", 0.0)),
            margin_free=float(_value_or_default(normalized, "margin_free", 0.0)),
            margin_level=float(_value_or_default(normalized, "margin_level", 0.0)),
            margin_so_call=float(_value_or_default(normalized, "margin_so_call", 0.0)),
            margin_so_so=float(_value_or_default(normalized, "margin_so_so", 0.0)),
            margin_initial=float(_value_or_default(normalized, "margin_initial", 0.0)),
            margin_maintenance=float(
                _value_or_default(normalized, "margin_maintenance", 0.0)
            ),
            assets=float(_value_or_default(normalized, "assets", 0.0)),
            liabilities=float(_value_or_default(normalized, "liabilities", 0.0)),
            commission_blocked=float(
                _value_or_default(normalized, "commission_blocked", 0.0)
            ),
            name=str(_value_or_default(normalized, "name", "TradeMachine")),
            server=str(_value_or_default(normalized, "server", "BacktestEngine")),
            currency=str(_value_or_default(normalized, "currency", "USD")),
            company=str(_value_or_default(normalized, "company", "TradeMachine")),
            raw=raw,
        )

    def __getattr__(self, item: str) -> Any:
        try:
            return self.raw[item]
        except KeyError as exc:
            raise AttributeError(item) from exc

    def to_mapping(self) -> dict[str, Any]:
        payload = dict(self.raw)
        payload.update(
            {
                "login": self.login,
                "trade_mode": self.trade_mode,
                "leverage": self.leverage,
                "limit_orders": self.limit_orders,
                "margin_so_mode": self.margin_so_mode,
                "trade_allowed": self.trade_allowed,
                "trade_expert": self.trade_expert,
                "margin_mode": self.margin_mode,
                "currency_digits": self.currency_digits,
                "fifo_close": self.fifo_close,
                "balance": self.balance,
                "credit": self.credit,
                "profit": self.profit,
                "equity": self.equity,
                "margin": self.margin,
                "margin_free": self.margin_free,
                "margin_level": self.margin_level,
                "margin_so_call": self.margin_so_call,
                "margin_so_so": self.margin_so_so,
                "margin_initial": self.margin_initial,
                "margin_maintenance": self.margin_maintenance,
                "assets": self.assets,
                "liabilities": self.liabilities,
                "commission_blocked": self.commission_blocked,
                "name": self.name,
                "server": self.server,
                "currency": self.currency,
                "company": self.company,
            }
        )
        return payload

    def _asdict(self) -> dict[str, Any]:
        return self.to_mapping()


@dataclass(frozen=True, slots=True)
class TradeOrder:
    """Pending order snapshot."""

    ticket: int
    time_setup: int
    time_setup_msc: int
    time_done: int
    time_done_msc: int
    time_expiration: int
    type: int
    type_time: int
    type_filling: int
    state: int
    magic: int
    position_id: int
    position_by_id: int
    reason: int
    volume_initial: float
    volume_current: float
    price_open: float
    sl: float
    tp: float
    price_current: float
    price_stoplimit: float
    symbol: str
    comment: str
    external_id: str = ""

    def _asdict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TradePosition:
    """Open position snapshot."""

    ticket: int
    time: int
    time_msc: int
    time_update: int
    time_update_msc: int
    type: int
    magic: int
    identifier: int
    reason: int
    volume: float
    price_open: float
    sl: float
    tp: float
    price_current: float
    swap: float
    profit: float
    symbol: str
    comment: str
    external_id: str = ""
    margin: float = 0.0

    def _asdict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TradeDeal:
    """Closed/open deal snapshot."""

    ticket: int
    order: int
    time: int
    time_msc: int
    type: int
    entry: int
    magic: int
    position_id: int
    reason: int
    volume: float
    price: float
    commission: float
    swap: float
    profit: float
    fee: float
    symbol: str
    comment: str
    external_id: str = ""
    balance: float = 0.0

    def _asdict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MarginEvent:
    """Represents the simulated account margin state."""

    state: str
    reason: str
    value: float
    call_level: float
    stop_level: float
    mode: int


def evaluate_margin_state(account: AccountInfo) -> MarginEvent:
    """Evaluates MT5-like margin call and stop-out state."""
    mode = int(account.margin_so_mode)
    call_level = float(account.margin_so_call or 0.0)
    stop_level = float(account.margin_so_so or 0.0)

    if mode == MetaTrader5.ACCOUNT_STOPOUT_MODE_MONEY:
        value = float(account.margin_free)
        if stop_level > 0 and value <= stop_level:
            return MarginEvent(
                "STOP_OUT",
                f"free_margin {value:.2f} <= stop_out {stop_level:.2f}",
                value,
                call_level,
                stop_level,
                mode,
            )
        if call_level > 0 and value <= call_level:
            return MarginEvent(
                "MARGIN_CALL",
                f"free_margin {value:.2f} <= margin_call {call_level:.2f}",
                value,
                call_level,
                stop_level,
                mode,
            )
        return MarginEvent("OK", "margin ok", value, call_level, stop_level, mode)

    if account.margin <= 0:
        value = float("inf")
    else:
        value = (float(account.equity) / float(account.margin)) * 100.0

    if stop_level > 0 and value <= stop_level:
        return MarginEvent(
            "STOP_OUT",
            f"margin_level {value:.2f}% <= stop_out {stop_level:.2f}%",
            value,
            call_level,
            stop_level,
            mode,
        )
    if call_level > 0 and value <= call_level:
        return MarginEvent(
            "MARGIN_CALL",
            f"margin_level {value:.2f}% <= margin_call {call_level:.2f}%",
            value,
            call_level,
            stop_level,
            mode,
        )
    return MarginEvent("OK", "margin ok", value, call_level, stop_level, mode)


def symbol_info_from_mt5(obj: Any) -> SymbolInfo:
    """Coerces a native MT5 symbol object into a SymbolInfo."""
    if isinstance(obj, SymbolInfo):
        return obj
    if isinstance(obj, dict):
        return SymbolInfo.from_mapping(obj)
    payload = {
        key: getattr(obj, key)
        for key in dir(obj)
        if not key.startswith("_") and not callable(getattr(obj, key))
    }
    return SymbolInfo.from_mapping(payload)


def account_info_from_mt5(obj: Any) -> AccountInfo:
    """Coerces a native MT5 account object into an AccountInfo."""
    if isinstance(obj, AccountInfo):
        return obj
    if isinstance(obj, dict):
        return AccountInfo.from_mapping(obj)
    payload = {
        key: getattr(obj, key)
        for key in dir(obj)
        if not key.startswith("_") and not callable(getattr(obj, key))
    }
    return AccountInfo.from_mapping(payload)


ACCOUNT_INFO_FILE = "account_info.json"
SYMBOL_INFO_FILE = "symbol_info.json"


class SnapshotImporters:
    """Imports broker snapshots in the legacy StrategyTester5 layout."""

    def __init__(self, broker_path: str, logger: logging.Logger | None = None):
        self.broker_path = Path(broker_path)
        self.logger = logger or logging.getLogger(__name__)

    def account_info(self) -> AccountInfo | None:
        file_path = self.broker_path / ACCOUNT_INFO_FILE
        if not file_path.exists():
            self.logger.debug("Account snapshot not found at %s", file_path)
            return None
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        return AccountInfo.from_mapping(payload.get("account_info", {}))

    def all_symbol_info(self) -> tuple[SymbolInfo, ...]:
        file_path = self.broker_path / SYMBOL_INFO_FILE
        if not file_path.exists():
            self.logger.debug("Symbol snapshot not found at %s", file_path)
            return tuple()
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        rows = payload.get("all_symbols_info", [])
        return tuple(SymbolInfo.from_mapping(row) for row in rows)


class SnapshotExporters:
    """Exports broker snapshots in the legacy StrategyTester5 layout."""

    def __init__(
        self,
        broker_path: str,
        logger: logging.Logger | None = None,
        file_not_exists: bool = True,
    ):
        self.broker_path = Path(broker_path)
        self.logger = logger or logging.getLogger(__name__)
        self.file_not_exists = file_not_exists
        self.broker_path.mkdir(parents=True, exist_ok=True)

    def _write_payload(self, file_path: Path, payload: dict[str, Any]) -> bool:
        if self.file_not_exists and file_path.exists():
            self.logger.debug("Skipping existing broker snapshot: %s", file_path)
            return False
        file_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return True

    def account_info(self, account_info: AccountInfo | dict[str, Any]) -> bool:
        if isinstance(account_info, AccountInfo):
            payload = account_info.to_mapping()
        else:
            payload = account_info
        return self._write_payload(
            self.broker_path / ACCOUNT_INFO_FILE,
            {"account_info": payload},
        )

    def all_symbol_info(self, symbol_info: tuple[Any, ...] | list[Any]) -> bool:
        rows: list[dict[str, Any]] = []
        for item in symbol_info:
            if isinstance(item, SymbolInfo):
                rows.append(item.to_mapping())
            elif isinstance(item, dict):
                rows.append(item)
            else:
                rows.append(symbol_info_from_mt5(item).to_mapping())
        return self._write_payload(
            self.broker_path / SYMBOL_INFO_FILE,
            {"all_symbols_info": rows},
        )


def snapshot_broker_data(
    broker_path: str,
    mt5_instance: Any | None = None,
    symbols: list[str] | None = None,
    logger: logging.Logger | None = None,
    overwrite: bool = True,
) -> tuple[AccountInfo, tuple[SymbolInfo, ...]]:
    """Exports account and symbol metadata from a live MT5 runtime."""
    if not MT5_AVAILABLE:
        no_mt5_runtime_error()

    runtime = mt5_instance or MetaTrader5
    account = account_info_from_mt5(runtime.account_info())
    if symbols:
        all_symbols = tuple(
            symbol_info_from_mt5(runtime.symbol_info(name)) for name in symbols
        )
    else:
        symbols_get = getattr(runtime, "symbols_get", None)
        if symbols_get is None:
            raise RuntimeError("MT5 runtime does not expose symbols_get()")
        all_symbols = tuple(symbol_info_from_mt5(item) for item in symbols_get())

    exporter = SnapshotExporters(
        broker_path=broker_path,
        logger=logger,
        file_not_exists=not overwrite,
    )
    exporter.account_info(account)
    exporter.all_symbol_info(all_symbols)
    return account, all_symbols


__all__ = [
    "ACCOUNT_INFO_FILE",
    "AccountInfo",
    "BUY_ACTIONS",
    "DEAL_TYPE_MAP",
    "MarginEvent",
    "MT5_AVAILABLE",
    "MetaTrader5",
    "ORDER_TYPE_MAP",
    "PeriodSeconds",
    "REQUIRED_TESTER_CONFIG_KEYS",
    "SELL_ACTIONS",
    "STRING2TIMEFRAME_MAP",
    "SUPPORTED_TESTER_MODELLING",
    "SnapshotExporters",
    "SnapshotImporters",
    "SymbolInfo",
    "TIMEFRAME2STRING_MAP",
    "Tick",
    "TradeDeal",
    "TradeOrder",
    "TradePosition",
    "account_info_from_mt5",
    "ensure_utc",
    "evaluate_margin_state",
    "make_tick",
    "make_tick_from_dict",
    "make_tick_from_tuple",
    "month_bounds",
    "no_mt5_runtime_error",
    "period_seconds",
    "snapshot_broker_data",
    "symbol_info_from_mt5",
]
