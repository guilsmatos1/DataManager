"""TCP ingestion server for MT5 terminals.

Handles socket communication, client management, message routing, and lifecycle.
Business logic (entity registration, persistence, drift) lives in processors.py.
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
from trademachine.tradingmonitor_ingestion.ingestion import processors  # noqa: F401
from trademachine.tradingmonitor_ingestion.ingestion.processors import (  # noqa: F401
    EXISTING_ACCOUNTS,
    EXISTING_STRATEGIES,
    EXISTING_SYMBOLS,
    REDACTED,
    _mask_sensitive_data,
    build_runtime_schema_from_payload,
    ensure_account_exists,
    ensure_strategy_exists,
    ensure_symbol_exists,
    invalidate_cache,
    link_strategies_to_account,
    maybe_check_drift,
    maybe_process_runtime_context,
    process_account,
    process_backtest_deal,
    process_backtest_end,
    process_backtest_equity,
    process_backtest_start,
    process_deal,
    process_equity,
    process_strategy_runtime,
    save_dead_letter,
)
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
    SessionLocal,
    ensure_database_connection,
    notifier,
    settings,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# ── Constants ────────────────────────────────────────────────────────────────────
RECV_TIMEOUT_SECONDS = 300
_MAX_BUFFER_SIZE = 1 * 1024 * 1024  # 1 MB

# Expose heartbeat file path for backward compatibility
HEARTBEAT_FILE = settings.heartbeat_file

# ── Structured JSON logging ──────────────────────────────────────────────────────
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


# ── Server state ─────────────────────────────────────────────────────────────────
@dataclass
class ServerState:
    """Transport-level server state (connections, events, uptime)."""

    connected_clients: set = field(default_factory=set)
    strategy_connections: dict = field(default_factory=dict)
    last_event_at: dict = field(default_factory=dict)
    server_start_time: datetime | None = None


# Module-level instance
_state = ServerState()

# Backward-compatible aliases
_connected_clients = _state.connected_clients
_strategy_connections = _state.strategy_connections
_last_event_at = _state.last_event_at
_server_start_time = _state.server_start_time

# Transport locks
_clients_lock = threading.Lock()
_connections_lock = threading.Lock()
_last_event_lock = threading.Lock()
_heartbeat_lock = threading.Lock()


# ── Server lifecycle ─────────────────────────────────────────────────────────────


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


# ── Socket handling ──────────────────────────────────────────────────────────────


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


# ── Message routing ──────────────────────────────────────────────────────────────

MessageHandler = Callable[["Session", dict, str | None, set[str]], str | None]


def _handle_deal_message(
    db: Session,
    data: dict,
    conn_account_id: str | None,
    conn_strategies_seen: set[str],
) -> str | None:
    valid_deal = DealSchema(**data)
    conn_strategies_seen.add(str(valid_deal.magic))
    processors.process_deal(db, valid_deal, account_id=conn_account_id)
    processors.maybe_process_runtime_context(db, valid_deal, account_id=conn_account_id)
    return conn_account_id


def _handle_equity_message(
    db: Session,
    data: dict,
    conn_account_id: str | None,
    conn_strategies_seen: set[str],
) -> str | None:
    valid_equity = EquitySchema(**data)
    if str(valid_equity.magic) != "0":
        conn_strategies_seen.add(str(valid_equity.magic))
    processors.process_equity(db, valid_equity, account_id=conn_account_id)
    processors.maybe_process_runtime_context(
        db, valid_equity, account_id=conn_account_id
    )
    return conn_account_id


def _handle_account_message(
    db: Session,
    data: dict,
    conn_account_id: str | None,
    conn_strategies_seen: set[str],
) -> str | None:
    valid_account = AccountSchema(**data)
    processors.process_account(db, valid_account)
    new_account_id = str(valid_account.login)
    processors.link_strategies_to_account(db, conn_strategies_seen, new_account_id)
    processors.maybe_process_runtime_context(
        db, valid_account, account_id=new_account_id
    )
    return new_account_id


def _handle_strategy_runtime_message(
    db: Session,
    data: dict,
    conn_account_id: str | None,
    conn_strategies_seen: set[str],
) -> str | None:
    valid_runtime = StrategyRuntimeSchema(**data)
    if str(valid_runtime.magic) != "0":
        conn_strategies_seen.add(str(valid_runtime.magic))
    processors.process_strategy_runtime(db, valid_runtime, account_id=conn_account_id)
    return conn_account_id


def _handle_backtest_start_message(
    db: Session,
    data: dict,
    conn_account_id: str | None,
    conn_strategies_seen: set[str],
) -> str | None:
    del conn_strategies_seen
    processors.process_backtest_start(db, BacktestStartSchema(**data))
    return conn_account_id


def _handle_backtest_deal_message(
    db: Session,
    data: dict,
    conn_account_id: str | None,
    conn_strategies_seen: set[str],
) -> str | None:
    del conn_strategies_seen
    processors.process_backtest_deal(db, BacktestDealSchema(**data))
    return conn_account_id


def _handle_backtest_equity_message(
    db: Session,
    data: dict,
    conn_account_id: str | None,
    conn_strategies_seen: set[str],
) -> str | None:
    del conn_strategies_seen
    processors.process_backtest_equity(db, BacktestEquitySchema(**data))
    return conn_account_id


def _handle_backtest_end_message(
    db: Session,
    data: dict,
    conn_account_id: str | None,
    conn_strategies_seen: set[str],
) -> str | None:
    del conn_strategies_seen
    processors.process_backtest_end(db, BacktestEndSchema(**data))
    return conn_account_id


_MESSAGE_HANDLERS: dict[str, MessageHandler] = {
    "ACCOUNT": _handle_account_message,
    "BACKTEST_DEAL": _handle_backtest_deal_message,
    "BACKTEST_END": _handle_backtest_end_message,
    "BACKTEST_EQUITY": _handle_backtest_equity_message,
    "BACKTEST_START": _handle_backtest_start_message,
    "DEAL": _handle_deal_message,
    "EQUITY": _handle_equity_message,
    "STRATEGY_RUNTIME": _handle_strategy_runtime_message,
}


def _process_message(
    db: Session,
    topic: str,
    data: dict,
    conn_account_id: str | None,
    conn_strategies_seen: set[str],
) -> str | None:
    """Processes a parsed message and returns the updated conn_account_id if applicable."""
    handler = _MESSAGE_HANDLERS.get(topic)
    if handler is None:
        logger.warning("Unknown topic: %s", topic, extra={"topic": topic})
        return conn_account_id
    return handler(db, data, conn_account_id, conn_strategies_seen)


# ── Client handling ──────────────────────────────────────────────────────────────


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
                    save_dead_letter(db, topic, line, str(ve.errors()))
                except json.JSONDecodeError:
                    logger.warning("Malformed JSON: %s", line[:120])
                    save_dead_letter(db, topic, line, "JSONDecodeError")
                except Exception as e:
                    db.rollback()
                    logger.error(
                        "Error processing [%s]: %s",
                        topic,
                        e,
                        exc_info=True,
                        extra={"topic": topic},
                    )
                    save_dead_letter(db, topic, line, str(e))
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


# ── Backward-compatible re-exports ───────────────────────────────────────────────
# Tests and other code import underscore-prefixed names from tcp_server.
_build_runtime_schema_from_payload = build_runtime_schema_from_payload
_maybe_process_runtime_context = maybe_process_runtime_context
_maybe_check_drift = maybe_check_drift
_save_dead_letter = save_dead_letter
_link_strategies_to_account = link_strategies_to_account
