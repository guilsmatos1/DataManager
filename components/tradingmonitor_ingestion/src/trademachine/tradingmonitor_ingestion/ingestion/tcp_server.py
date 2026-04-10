"""TCP ingestion server for MT5 terminals.

Handles socket communication, client management, message routing, and persistence.
This module orchestrates the ingestion pipeline by delegating pure DB operations
to processors.py and drift checking to drift_checker.py.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pythonjsonlogger.json import JsonFormatter
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from trademachine.tradingmonitor_ingestion.ingestion.schemas import (
    AccountSchema,
    BacktestDealSchema,
    BacktestEndSchema,
    BacktestEquitySchema,
    BacktestStartSchema,
    DealSchema,
    EquitySchema,
    StrategyRuntimeSchema,
)
from trademachine.tradingmonitor_storage.public import (
    Account,
    Backtest,
    BacktestDeal,
    BacktestEquity,
    DealType,
    EquityCurve,
    IngestionError,
    SessionLocal,
    Strategy,
    StrategyRuntimeSnapshot,
    Symbol,
    ensure_database_connection,
    insert_deal_if_new,
    notifier,
    settings,
)

if TYPE_CHECKING:
    pass

# ── Constants ───────────────────────────────────────────────────────────────────
DRIFT_CHECK_INTERVAL = 10
RECV_TIMEOUT_SECONDS = 300
_MAX_BUFFER_SIZE = 1 * 1024 * 1024  # 1 MB

# Expose heartbeat file path for backward compatibility
HEARTBEAT_FILE = settings.heartbeat_file


# ── Structured JSON logging ─────────────────────────────────────────────────────
_json_formatter = JsonFormatter(
    fmt="%(ts)s %(level)s %(logger)s %(msg)s",
    rename_fields={"levelname": "level", "name": "logger", "message": "msg"},
    timestamp=True,
)


_json_handler = logging.FileHandler("ingestion.log")
_json_handler.setFormatter(_json_formatter)
_stream_handler = logging.StreamHandler()
_stream_handler.setFormatter(_json_formatter)

logger = logging.getLogger("TCPServer")
if not logger.handlers:
    logger.addHandler(_json_handler)
    logger.addHandler(_stream_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


# ── Server state ────────────────────────────────────────────────────────────────
@dataclass
class ServerState:
    """Encapsulates all mutable server state for easier testing and maintainability."""

    connected_clients: set = field(default_factory=set)
    strategy_connections: dict = field(default_factory=dict)
    last_event_at: dict = field(default_factory=dict)  # topic → ISO timestamp
    server_start_time: datetime | None = None
    existing_strategies: set = field(default_factory=set)
    existing_accounts: set = field(default_factory=set)
    existing_symbols: set = field(default_factory=set)
    active_backtests: dict = field(
        default_factory=dict
    )  # "strategy_id:run_id" → backtest DB id
    deal_counters: dict = field(default_factory=dict)  # strategy_id → count


# Module-level instance
_state = ServerState()

# Backward-compatible aliases (point to the same objects in _state)
_connected_clients = _state.connected_clients
_strategy_connections = _state.strategy_connections
_last_event_at = _state.last_event_at
_server_start_time = _state.server_start_time
EXISTING_STRATEGIES = _state.existing_strategies
EXISTING_ACCOUNTS = _state.existing_accounts
EXISTING_SYMBOLS = _state.existing_symbols
_active_backtests = _state.active_backtests
_deal_counters = _state.deal_counters

# Locks remain at module level (threading primitives, not state)
_clients_lock = threading.Lock()
_connections_lock = threading.Lock()
_last_event_lock = threading.Lock()
_backtests_lock = threading.Lock()
_counters_lock = threading.Lock()
_heartbeat_lock = threading.Lock()

# ── Cache helpers ───────────────────────────────────────────────────────────────


def _backtest_cache_key(strategy_id: str, run_id: int) -> str:
    return f"{strategy_id}:{run_id}"


def invalidate_cache(
    strategy_id: str | None = None, account_id: str | None = None
) -> None:
    """Remove entries from in-memory strategy/account caches.

    Call this whenever a strategy or account is deleted so that the next
    incoming message triggers a fresh DB lookup instead of using a stale
    cache entry.
    """
    if strategy_id is not None:
        EXISTING_STRATEGIES.discard(strategy_id)
    if account_id is not None:
        EXISTING_ACCOUNTS.discard(account_id)


# ── Server lifecycle ────────────────────────────────────────────────────────────


def update_heartbeat() -> None:
    """Update the heartbeat file with current timestamp."""
    try:
        with _heartbeat_lock:
            with open(settings.heartbeat_file, "w") as f:
                f.write(datetime.now(UTC).isoformat())
    except OSError as e:
        logger.error("Failed to update heartbeat: %s", e)


def _record_event(topic: str) -> None:
    """Record the timestamp of the last event for each topic."""
    with _last_event_lock:
        _last_event_at[topic] = datetime.now(UTC).isoformat()


def get_server_uptime_seconds() -> float | None:
    """Return seconds since start_server() was called, or None if not yet started."""
    if _server_start_time is None:
        return None
    return round((datetime.now(UTC) - _server_start_time).total_seconds(), 1)


def get_ingestion_status() -> dict:
    """Return current ingestion server status."""
    with _clients_lock:
        clients = [{"ip": ip, "port": port} for ip, port in _connected_clients]
    with _last_event_lock:
        last = dict(_last_event_at)
    uptime = get_server_uptime_seconds()
    heartbeat_ts = None
    if os.path.exists(settings.heartbeat_file):
        try:
            with _heartbeat_lock:
                with open(settings.heartbeat_file) as f:
                    heartbeat_ts = f.read().strip()
        except OSError:
            pass
    return {
        "connected_clients": len(clients),
        "clients": clients,
        "last_event_at": last,
        "uptime_seconds": round(uptime, 1) if uptime is not None else 0.0,
        "heartbeat": heartbeat_ts,
    }


# ── Socket handling ─────────────────────────────────────────────────────────────


def _configure_keepalive(conn: socket.socket) -> None:
    """Enable TCP keepalive and set a recv timeout on a client socket."""
    conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    if hasattr(socket, "TCP_KEEPIDLE"):
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)
    if hasattr(socket, "TCP_KEEPINTVL"):
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
    if hasattr(socket, "TCP_KEEPCNT"):
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5)
    conn.settimeout(RECV_TIMEOUT_SECONDS)


def send_kill_command(strategy_id: str) -> bool:
    """Send a KILL command to the MT5 EA associated with the strategy_id."""
    with _connections_lock:
        conn = _strategy_connections.get(strategy_id)
        if not conn:
            logger.warning(
                "Kill command failed: No active connection for strategy %s", strategy_id
            )
            return False

        try:
            command = {"command": "KILL", "magic": strategy_id}
            payload = json.dumps(command) + "\n"
            conn.sendall(payload.encode("utf-8"))
            logger.info("Kill command sent to strategy %s", strategy_id)
            return True
        except OSError as e:
            logger.error("Failed to send kill command to %s: %s", strategy_id, e)
            return False


def _get_or_lookup_backtest_id(
    db: Session, strategy_id: str, run_id: int
) -> int | None:
    key = _backtest_cache_key(strategy_id, run_id)
    with _backtests_lock:
        if key in _active_backtests:
            return int(_active_backtests[key])
        bt = (
            db.query(Backtest)
            .filter(
                Backtest.strategy_id == strategy_id,
                Backtest.client_run_id == run_id,
            )
            .first()
        )
        if bt:
            _active_backtests[key] = bt.id
            return int(bt.id)
        return None


# ── Sensitive data masking ───────────────────────────────────────────────────────
_SENSITIVE_KEYS = frozenset(
    {"password", "token", "secret", "key", "api_key", "authorization"}
)
REDACTED = "***REDACTED***"


def _mask_sensitive_data(data: str) -> str:
    """Mask values of sensitive keys in a JSON string."""
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError:
        return data

    def redact(obj: dict | list) -> dict | list:
        if isinstance(obj, dict):
            result: dict[str, object] = {}
            for k, v in obj.items():
                if any(sensitive in k.lower() for sensitive in _SENSITIVE_KEYS):
                    result[k] = REDACTED
                elif isinstance(v, dict | list):
                    result[k] = redact(v)
                else:
                    result[k] = v
            return result
        elif isinstance(obj, list):
            return [redact(item) for item in obj]
        return obj

    masked = redact(parsed)
    return json.dumps(masked, ensure_ascii=False)


def _save_dead_letter(db: Session, topic: str, raw: str, error: str) -> None:
    """Save a failed message to the dead letter table/file."""
    masked_raw = _mask_sensitive_data(raw)
    try:
        err = IngestionError(
            topic=topic, raw_message=masked_raw[:4096], error_message=error[:2048]
        )
        db.add(err)
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.error(
            "Failed to save dead letter to DB: %s — falling back to file", error
        )
        try:
            entry = json.dumps(
                {
                    "ts": datetime.now(UTC).isoformat(),
                    "topic": topic,
                    "raw": masked_raw[:4096],
                    "error": error[:2048],
                }
            )
            with open(settings.dead_letter_file, "a") as f:
                f.write(entry + "\n")
        except OSError as fe:
            logger.error("Dead letter file fallback also failed: %s", fe)


# ── Strategy/Symbol/Account existence helpers ──────────────────────────────────


def ensure_strategy_exists(
    db: Session,
    strategy_id: str,
    symbol: str | None = None,
    account_id: str | None = None,
) -> None:
    """Ensure a strategy exists in the database, creating it if necessary."""
    symbol_id = _get_symbol_id(db, symbol)
    if strategy_id in EXISTING_STRATEGIES:
        if account_id:
            db.query(Strategy).filter(
                Strategy.id == strategy_id, Strategy.account_id.is_(None)
            ).update({"account_id": account_id})
        if symbol:
            db.query(Strategy).filter(Strategy.id == strategy_id).update(
                {"symbol": symbol, "symbol_id": symbol_id}
            )
        return
    strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not strategy:
        try:
            with db.begin_nested():
                db.add(
                    Strategy(
                        id=strategy_id,
                        name=f"MT5 Strategy {strategy_id}",
                        symbol=symbol,
                        symbol_id=symbol_id,
                        account_id=account_id,
                        live=False,
                        real_account=False,
                    )
                )
            logger.info("New strategy registered", extra={"strategy_id": strategy_id})
            notifier.notify_new_strategy(strategy_id, symbol)
        except IntegrityError:
            logger.debug(
                "Strategy %s already exists (concurrent insert)",
                strategy_id,
                extra={"strategy_id": strategy_id},
            )
    elif account_id and strategy.account_id is None:
        strategy.account_id = account_id
    if symbol and strategy:
        strategy.symbol = symbol
        strategy.symbol_id = symbol_id
    EXISTING_STRATEGIES.add(strategy_id)


def ensure_symbol_exists(db: Session, symbol: str | None) -> None:
    """Insert symbol into the symbols table if it doesn't already exist."""
    if not symbol or symbol in EXISTING_SYMBOLS:
        return
    try:
        stmt = pg_insert(Symbol).values(name=symbol).on_conflict_do_nothing()
        db.execute(stmt)
    except Exception as e:
        logger.debug("Symbol ensure error for %s: %s", symbol, e)
    EXISTING_SYMBOLS.add(symbol)


def _get_symbol_id(db: Session, symbol: str | None) -> int | None:
    if not symbol:
        return None
    row = db.query(Symbol.id).filter(Symbol.name == symbol).first()
    return int(row[0]) if row is not None else None


def ensure_account_exists(
    db: Session, account_id: str, broker: str | None = None
) -> None:
    """Ensure an account exists in the database, creating it if necessary."""
    if account_id in EXISTING_ACCOUNTS:
        return
    acc = db.query(Account).filter(Account.id == account_id).first()
    if not acc:
        try:
            with db.begin_nested():
                db.add(
                    Account(
                        id=account_id,
                        name=f"Account {account_id}",
                        broker=broker or "Unknown",
                    )
                )
            logger.info("New account registered", extra={"strategy_id": account_id})
        except IntegrityError:
            logger.debug(
                "Account %s already exists (concurrent insert)",
                account_id,
                extra={"strategy_id": account_id},
            )
    EXISTING_ACCOUNTS.add(account_id)


def _link_strategies_to_account(
    db: Session, strategy_ids: set[str], account_id: str
) -> None:
    """Bulk-set account_id on strategies that don't have one yet."""
    if not strategy_ids or not account_id:
        return
    db.query(Strategy).filter(
        Strategy.id.in_(strategy_ids),
        Strategy.account_id.is_(None),
    ).update({"account_id": account_id}, synchronize_session="fetch")
    db.commit()


# ── Message routing ─────────────────────────────────────────────────────────────


def _process_message(
    db: Session,
    topic: str,
    data: dict,
    conn_account_id: str | None,
    conn_strategies_seen: set[str],
) -> str | None:
    """Processes a parsed message and returns the updated conn_account_id if applicable."""
    if topic == "DEAL":
        valid_deal = DealSchema(**data)
        conn_strategies_seen.add(str(valid_deal.magic))
        process_deal(db, valid_deal, account_id=conn_account_id)
        _maybe_process_runtime_context(db, valid_deal, account_id=conn_account_id)
    elif topic == "EQUITY":
        valid_eq = EquitySchema(**data)
        if str(valid_eq.magic) != "0":
            conn_strategies_seen.add(str(valid_eq.magic))
        process_equity(db, valid_eq, account_id=conn_account_id)
        _maybe_process_runtime_context(db, valid_eq, account_id=conn_account_id)
    elif topic == "ACCOUNT":
        valid_acc = AccountSchema(**data)
        process_account(db, valid_acc)
        new_account_id = str(valid_acc.login)
        _link_strategies_to_account(db, conn_strategies_seen, new_account_id)
        _maybe_process_runtime_context(db, valid_acc, account_id=new_account_id)
        return new_account_id
    elif topic == "STRATEGY_RUNTIME":
        valid_runtime = StrategyRuntimeSchema(**data)
        if str(valid_runtime.magic) != "0":
            conn_strategies_seen.add(str(valid_runtime.magic))
        process_strategy_runtime(db, valid_runtime, account_id=conn_account_id)
    elif topic == "BACKTEST_START":
        valid_bs = BacktestStartSchema(**data)
        process_backtest_start(db, valid_bs)
    elif topic == "BACKTEST_DEAL":
        valid_bd = BacktestDealSchema(**data)
        process_backtest_deal(db, valid_bd)
    elif topic == "BACKTEST_EQUITY":
        valid_be = BacktestEquitySchema(**data)
        process_backtest_equity(db, valid_be)
    elif topic == "BACKTEST_END":
        valid_bend = BacktestEndSchema(**data)
        process_backtest_end(db, valid_bend)
    else:
        logger.warning("Unknown topic: %s", topic, extra={"topic": topic})
    return conn_account_id


# ── Message processors ───────────────────────────────────────────────────────────


def _build_runtime_schema_from_payload(
    data: DealSchema | EquitySchema | AccountSchema,
) -> StrategyRuntimeSchema | None:
    """Extract a runtime snapshot piggybacked on another payload, if present."""
    if data.open_profit is None:
        return None
    if data.open_trades_count is None:
        return None
    if data.pending_orders_count is None:
        return None

    time_value = getattr(data, "time", None)
    magic_value = getattr(data, "magic", None)
    if time_value is None or magic_value is None:
        return None

    return StrategyRuntimeSchema(
        time=time_value,
        magic=magic_value,
        open_profit=data.open_profit,
        open_trades_count=data.open_trades_count,
        pending_orders_count=data.pending_orders_count,
    )


def _maybe_process_runtime_context(
    db: Session,
    data: DealSchema | EquitySchema | AccountSchema,
    account_id: str | None = None,
) -> None:
    """Persist runtime context when it is bundled into another MT5 payload."""
    runtime_data = _build_runtime_schema_from_payload(data)
    if runtime_data is None:
        return
    process_strategy_runtime(db, runtime_data, account_id=account_id)


def _maybe_check_drift(strategy_id: str) -> None:
    """Trigger a performance drift check in the background every N deals."""
    if strategy_id == "0":
        return
    with _counters_lock:
        count = _deal_counters.get(strategy_id, 0) + 1
        _deal_counters[strategy_id] = count

    if count % DRIFT_CHECK_INTERVAL == 0:
        logger.info("Triggering drift check for strategy %s", strategy_id)

        def _run_drift_check() -> None:
            from trademachine.tradingmonitor_analytics.public import (
                check_performance_drift,
            )

            try:
                check_performance_drift(strategy_id)
            except Exception as e:
                logger.error("Drift check failed for strategy %s: %s", strategy_id, e)
                notifier.notify_system_error(
                    context=f"Drift check strategy {strategy_id}",
                    error=str(e),
                )

        threading.Thread(target=_run_drift_check, daemon=True).start()


def process_deal(db: Session, data: DealSchema, account_id: str | None = None) -> None:
    """Insert a trade deal into the database."""
    magic = str(data.magic)
    ensure_symbol_exists(db, data.symbol)
    ensure_strategy_exists(db, magic, data.symbol, account_id=account_id)
    timestamp = datetime.fromtimestamp(data.time, tz=UTC)
    inserted = insert_deal_if_new(
        db,
        {
            "timestamp": timestamp,
            "ticket": data.ticket,
            "strategy_id": magic,
            "symbol": data.symbol,
            "type": DealType(str(data.type).upper()).value,
            "volume": data.volume,
            "price": data.price,
            "profit": data.profit,
            "commission": data.commission,
            "swap": data.swap,
        },
    )
    logger.debug(
        "Deal processed: ticket=%s",
        data.ticket,
        extra={"strategy_id": magic, "ticket": data.ticket},
    )
    if inserted and data.type in {"buy", "sell"}:
        strategy = db.query(Strategy).filter(Strategy.id == magic).first()
        notifier.notify_trade_closed(
            strategy_id=magic,
            strategy_name=strategy.name if strategy else None,
            symbol=data.symbol,
            deal_type=data.type,
            ticket=data.ticket,
            volume=data.volume,
            price=data.price,
            profit=data.profit,
            commission=data.commission,
            swap=data.swap,
            timestamp=timestamp,
        )
    _maybe_check_drift(magic)


def process_equity(
    db: Session, data: EquitySchema, account_id: str | None = None
) -> None:
    """Insert or update an equity curve point for a strategy."""
    magic = str(data.magic)
    if magic == "0":
        return
    ensure_strategy_exists(db, magic, account_id=account_id)
    stmt = (
        pg_insert(EquityCurve)
        .values(
            timestamp=datetime.fromtimestamp(data.time, tz=UTC),
            strategy_id=magic,
            balance=data.balance,
            equity=data.equity,
        )
        .on_conflict_do_update(
            index_elements=["timestamp", "strategy_id"],
            set_={"balance": data.balance, "equity": data.equity},
        )
    )
    db.execute(stmt)


def process_account(db: Session, data: AccountSchema) -> None:
    """Update or create an account record and check margin levels."""
    acc_id = str(data.login)
    acc = db.query(Account).filter(Account.id == acc_id).first()
    if not acc:
        ensure_account_exists(db, acc_id, data.broker)
        acc = db.query(Account).filter(Account.id == acc_id).first()
    if acc:
        acc.balance = data.balance
        acc.free_margin = data.free_margin
        acc.total_deposits = data.deposits
        acc.total_withdrawals = data.withdrawals
        logger.info("Account %s updated.", acc_id, extra={"strategy_id": acc_id})

    if data.free_margin < (data.balance * (settings.margin_threshold_pct / 100.0)):
        notifier.notify_low_margin(
            acc_id, data.free_margin, settings.margin_threshold_pct
        )


def process_strategy_runtime(
    db: Session,
    data: StrategyRuntimeSchema,
    account_id: str | None = None,
) -> None:
    """Insert or update the latest runtime snapshot for a strategy."""
    magic = str(data.magic)
    if magic == "0":
        return
    ensure_strategy_exists(db, magic, account_id=account_id)
    snapshot_ts = datetime.fromtimestamp(data.time, tz=UTC)
    stmt = (
        pg_insert(StrategyRuntimeSnapshot)
        .values(
            strategy_id=magic,
            timestamp=snapshot_ts,
            open_profit=data.open_profit,
            open_trades_count=data.open_trades_count,
            pending_orders_count=data.pending_orders_count,
        )
        .on_conflict_do_update(
            index_elements=["strategy_id"],
            set_={
                "timestamp": snapshot_ts,
                "open_profit": data.open_profit,
                "open_trades_count": data.open_trades_count,
                "pending_orders_count": data.pending_orders_count,
            },
        )
    )
    db.execute(stmt)


# ── Backtest processors ────────────────────────────────────────────────────────


def process_backtest_start(db: Session, data: BacktestStartSchema) -> None:
    """Register a new backtest run."""
    magic = str(data.magic)
    ensure_symbol_exists(db, data.symbol)
    ensure_strategy_exists(db, magic, data.symbol)
    bt = Backtest(
        strategy_id=magic,
        client_run_id=data.run_id,
        name=data.name,
        symbol=data.symbol,
        symbol_id=_get_symbol_id(db, data.symbol),
        timeframe=data.timeframe,
        start_date=datetime.fromtimestamp(data.start_date, tz=UTC),
        end_date=datetime.fromtimestamp(data.end_date, tz=UTC),
        initial_balance=data.initial_balance,
        parameters=data.parameters,
        status="running",
    )
    db.merge(bt)
    db.flush()
    bt_from_db = (
        db.query(Backtest)
        .filter(
            Backtest.strategy_id == magic,
            Backtest.client_run_id == data.run_id,
        )
        .first()
    )
    if bt_from_db:
        key = _backtest_cache_key(magic, data.run_id)
        with _backtests_lock:
            _active_backtests[key] = bt_from_db.id
        logger.info(
            "Backtest started: id=%s strategy=%s run_id=%s",
            bt_from_db.id,
            magic,
            data.run_id,
            extra={"strategy_id": magic},
        )


def process_backtest_deal(db: Session, data: BacktestDealSchema) -> None:
    """Insert a backtest deal."""
    magic = str(data.magic)
    bt_id = _get_or_lookup_backtest_id(db, magic, data.run_id)
    if bt_id is None:
        raise ValueError(
            f"Backtest not found for strategy={magic} run_id={data.run_id}"
        )
    stmt = (
        pg_insert(BacktestDeal)
        .values(
            backtest_id=bt_id,
            timestamp=datetime.fromtimestamp(data.time, tz=UTC),
            ticket=data.ticket,
            symbol=data.symbol,
            type=DealType(str(data.type).upper()).value,
            volume=data.volume,
            price=data.price,
            profit=data.profit,
            commission=data.commission,
            swap=data.swap,
        )
        .on_conflict_do_nothing()
    )
    db.execute(stmt)


def process_backtest_equity(db: Session, data: BacktestEquitySchema) -> None:
    """Insert or update a backtest equity point."""
    magic = str(data.magic)
    bt_id = _get_or_lookup_backtest_id(db, magic, data.run_id)
    if bt_id is None:
        raise ValueError(
            f"Backtest not found for strategy={magic} run_id={data.run_id}"
        )
    stmt = (
        pg_insert(BacktestEquity)
        .values(
            backtest_id=bt_id,
            timestamp=datetime.fromtimestamp(data.time, tz=UTC),
            balance=data.balance,
            equity=data.equity,
        )
        .on_conflict_do_update(
            index_elements=["backtest_id", "timestamp"],
            set_={"balance": data.balance, "equity": data.equity},
        )
    )
    db.execute(stmt)


def process_backtest_end(db: Session, data: BacktestEndSchema) -> None:
    """Mark a backtest as complete or failed."""
    magic = str(data.magic)
    bt_id = _get_or_lookup_backtest_id(db, magic, data.run_id)
    if bt_id is None:
        logger.warning(
            "BACKTEST_END: backtest not found strategy=%s run_id=%s", magic, data.run_id
        )
        return
    bt = db.query(Backtest).filter(Backtest.id == bt_id).first()
    if bt:
        bt.status = data.status
        logger.info(
            "Backtest finished: id=%s status=%s",
            bt_id,
            data.status,
            extra={"strategy_id": magic},
        )
    key = _backtest_cache_key(magic, data.run_id)
    with _backtests_lock:
        _active_backtests.pop(key, None)


# ── Client handling ────────────────────────────────────────────────────────────


def handle_client(
    conn: socket.socket,
    addr: tuple,
    on_event: Callable | None = None,
) -> None:
    """Handle a single MT5 connection in its own thread."""
    from pydantic import ValidationError

    _configure_keepalive(conn)
    logger.info("MT5 connected", extra={"addr": f"{addr[0]}:{addr[1]}"})
    with _clients_lock:
        _connected_clients.add(addr)

    db = SessionLocal()
    buf = ""
    conn_account_id: str | None = None
    conn_strategies_seen: set[str] = set()

    def _register_strategy(sid: str) -> None:
        if sid not in conn_strategies_seen:
            conn_strategies_seen.add(sid)
            with _connections_lock:
                _strategy_connections[sid] = conn

    try:
        while True:
            try:
                chunk = conn.recv(4096)
            except TimeoutError:
                logger.warning(
                    "Connection idle timeout from %s — closing",
                    addr,
                    extra={"addr": f"{addr[0]}:{addr[1]}"},
                )
                break
            except OSError:
                break

            if not chunk:
                break

            buf += chunk.decode("utf-8", errors="replace")

            if len(buf) > _MAX_BUFFER_SIZE:
                logger.warning(
                    "Buffer overflow from %s (%d bytes), closing connection",
                    addr,
                    len(buf),
                    extra={"addr": f"{addr[0]}:{addr[1]}"},
                )
                break

            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if not line:
                    continue

                parts = line.split(" ", 1)
                if len(parts) != 2:
                    logger.warning("Unexpected message format: %s", line[:80])
                    continue

                topic, json_data = parts
                topic = topic.upper()
                try:
                    data = json.loads(json_data)

                    if "magic" in data:
                        _register_strategy(str(data["magic"]))

                    conn_account_id = _process_message(
                        db, topic, data, conn_account_id, conn_strategies_seen
                    )

                    db.commit()
                    update_heartbeat()
                    _record_event(topic)

                    if on_event:
                        try:
                            on_event(topic, data)
                        except Exception as e:
                            logger.error("on_event callback error: %s", e)

                except ValidationError as ve:
                    logger.error(
                        "Validation error [%s]: %s",
                        topic,
                        ve.errors(),
                        extra={"topic": topic},
                    )
                    db.rollback()
                    _save_dead_letter(db, topic, line, str(ve.errors()))
                except json.JSONDecodeError:
                    logger.warning("Malformed JSON: %s", line[:120])
                    _save_dead_letter(db, topic, line, "JSONDecodeError")
                except Exception as e:
                    db.rollback()
                    logger.error(
                        "Error processing [%s]: %s",
                        topic,
                        e,
                        exc_info=True,
                        extra={"topic": topic},
                    )
                    _save_dead_letter(db, topic, line, str(e))
                    notifier.notify_ingestion_error(topic, str(e))

    except Exception as e:
        logger.error("Client %s handler error: %s", addr, e)
        notifier.notify_system_error(
            context=f"TCP client handler {addr[0]}:{addr[1]}",
            error=str(e),
        )
    finally:
        with _clients_lock:
            _connected_clients.discard(addr)
        with _connections_lock:
            for sid in conn_strategies_seen:
                if _strategy_connections.get(sid) == conn:
                    _strategy_connections.pop(sid, None)
        db.close()
        conn.close()
        logger.info("MT5 disconnected", extra={"addr": f"{addr[0]}:{addr[1]}"})


def start_server(
    host: str | None = None,
    port: int | None = None,
    on_event: Callable | None = None,
    require_database: bool = True,
) -> None:
    """Start the TCP ingestion server. Accepts multiple concurrent MT5 connections."""
    global _server_start_time
    _server_start_time = datetime.now(UTC)

    host = host or settings.server_host
    port = port or settings.server_port

    if require_database:
        ensure_database_connection("TradingMonitor ingestion")

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server_sock.bind((host, port))
        server_sock.listen(10)
        logger.info("TCP Server listening on %s:%s", host, port)
    except OSError as e:
        logger.error("Could not bind TCP socket on %s:%s — %s", host, port, e)
        return

    try:
        while True:
            try:
                conn, addr = server_sock.accept()
                t = threading.Thread(
                    target=handle_client,
                    args=(conn, addr, on_event),
                    daemon=True,
                )
                t.start()
            except OSError as e:
                logger.error("Accept error: %s", e)
    finally:
        server_sock.close()
