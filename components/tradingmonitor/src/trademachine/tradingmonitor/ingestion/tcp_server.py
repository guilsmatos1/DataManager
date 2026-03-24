import json
import logging
import os
import socket
import threading
from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from trademachine.tradingmonitor.config import settings
from trademachine.tradingmonitor.db.database import SessionLocal
from trademachine.tradingmonitor.db.models import (
    Account,
    Backtest,
    BacktestDeal,
    BacktestEquity,
    Deal,
    DealType,
    EquityCurve,
    IngestionError,
    Strategy,
    Symbol,
)
from trademachine.tradingmonitor.ingestion.schemas import (
    AccountSchema,
    BacktestDealSchema,
    BacktestEndSchema,
    BacktestEquitySchema,
    BacktestStartSchema,
    DealSchema,
    EquitySchema,
)
from trademachine.tradingmonitor.utils.notifications import notifier


# ── Structured JSON logging ──────────────────────────────────────────────────
class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for extra in ("strategy_id", "ticket", "topic", "addr"):
            if hasattr(record, extra):
                payload[extra] = getattr(record, extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


_json_handler = logging.FileHandler("ingestion.log")
_json_handler.setFormatter(_JsonFormatter())
_stream_handler = logging.StreamHandler()
_stream_handler.setFormatter(_JsonFormatter())

# basicConfig() is a no-op when handlers are already configured (e.g. by uvicorn).
# Attach handlers directly to the root logger only if none are set yet.
logger = logging.getLogger("TCPServer")
# Attach handlers directly so JSON output reaches the file regardless of whether
# uvicorn or basicConfig has already configured the root logger.
if not logger.handlers:
    logger.addHandler(_json_handler)
    logger.addHandler(_stream_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False  # prevent double-output under uvicorn

HEARTBEAT_FILE = "/tmp/trademachine.tradingmonitor_heartbeat"
_heartbeat_lock = threading.Lock()

# ── Server state ─────────────────────────────────────────────────────────────
_connected_clients: set[tuple] = set()
_clients_lock = threading.Lock()
_last_event_at: dict[str, str] = {}  # topic → ISO timestamp
_last_event_lock = threading.Lock()
_server_start_time: datetime | None = (
    None  # set to non-None only when start_server() is called
)

# In-memory caches to avoid repeated DB lookups
EXISTING_STRATEGIES: set[str] = set()
EXISTING_ACCOUNTS: set[str] = set()
EXISTING_SYMBOLS: set[str] = set()

_MAX_BUFFER_SIZE = 1 * 1024 * 1024  # 1 MB — protect against OOM from malformed clients
_DEAD_LETTER_FILE = "/tmp/trademachine.tradingmonitor_dead_letters.jsonl"

# Cache: "strategy_id:run_id" → backtest DB id
_active_backtests: dict[str, int] = {}
_backtests_lock = threading.Lock()


def _backtest_cache_key(strategy_id: str, run_id: int) -> str:
    return f"{strategy_id}:{run_id}"


def invalidate_cache(strategy_id: str | None = None, account_id: str | None = None):
    """Remove entries from in-memory strategy/account caches.

    Call this whenever a strategy or account is deleted so that the next
    incoming message triggers a fresh DB lookup instead of using a stale
    cache entry.

    Example (routes.py delete endpoint):
        from trademachine.tradingmonitor.ingestion.tcp_server import invalidate_cache
        invalidate_cache(strategy_id=strategy_id)
    """
    if strategy_id is not None:
        EXISTING_STRATEGIES.discard(strategy_id)
    if account_id is not None:
        EXISTING_ACCOUNTS.discard(account_id)


def _get_or_lookup_backtest_id(db, strategy_id: str, run_id: int) -> int | None:
    key = _backtest_cache_key(strategy_id, run_id)
    with _backtests_lock:
        if key in _active_backtests:
            return _active_backtests[key]
        # Query inside the lock to prevent duplicate lookups from concurrent threads.
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
            return bt.id
        return None


def update_heartbeat():
    try:
        with _heartbeat_lock:
            with open(HEARTBEAT_FILE, "w") as f:
                f.write(datetime.now(UTC).isoformat())
    except Exception as e:
        logger.error("Failed to update heartbeat: %s", e)


def _record_event(topic: str):
    with _last_event_lock:
        _last_event_at[topic] = datetime.now(UTC).isoformat()


def get_server_uptime_seconds() -> float | None:
    """Return seconds since start_server() was called, or None if not yet started."""
    if _server_start_time is None:
        return None
    return round((datetime.now(UTC) - _server_start_time).total_seconds(), 1)


def get_ingestion_status() -> dict:
    with _clients_lock:
        clients = [{"ip": ip, "port": port} for ip, port in _connected_clients]
    with _last_event_lock:
        last = dict(_last_event_at)
    uptime = get_server_uptime_seconds()
    heartbeat_ts = None
    if os.path.exists(HEARTBEAT_FILE):
        try:
            with _heartbeat_lock:
                with open(HEARTBEAT_FILE) as f:
                    heartbeat_ts = f.read().strip()
        except Exception:
            pass
    return {
        "connected_clients": len(clients),
        "clients": clients,
        "last_event_at": last,
        "uptime_seconds": round(uptime, 1) if uptime is not None else 0.0,
        "heartbeat": heartbeat_ts,
    }


def ensure_strategy_exists(
    db, strategy_id: str, symbol: str | None = None, account_id: str | None = None
):
    if strategy_id in EXISTING_STRATEGIES:
        if account_id:
            db.query(Strategy).filter(
                Strategy.id == strategy_id, Strategy.account_id.is_(None)
            ).update({"account_id": account_id})
        return
    strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not strategy:
        try:
            # Use a savepoint so that an IntegrityError from a concurrent insert
            # only rolls back this sub-transaction, leaving the outer session valid.
            with db.begin_nested():
                db.add(
                    Strategy(
                        id=strategy_id,
                        name=f"MT5 Strategy {strategy_id}",
                        symbol=symbol,
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
    # Add to cache only after confirming the row is present (inserted or pre-existing).
    EXISTING_STRATEGIES.add(strategy_id)


def ensure_symbol_exists(db, symbol: str | None) -> None:
    """Insert symbol into the symbols table if it doesn't already exist."""
    if not symbol or symbol in EXISTING_SYMBOLS:
        return
    try:
        stmt = pg_insert(Symbol.__table__).values(name=symbol).on_conflict_do_nothing()
        db.execute(stmt)
    except Exception as e:
        logger.debug("Symbol ensure error for %s: %s", symbol, e)
    EXISTING_SYMBOLS.add(symbol)


def ensure_account_exists(db, account_id: str, broker: str | None = None):
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


def _link_strategies_to_account(db, strategy_ids: set[str], account_id: str) -> None:
    """Bulk-set account_id on strategies that don't have one yet."""
    if not strategy_ids or not account_id:
        return
    db.query(Strategy).filter(
        Strategy.id.in_(strategy_ids),
        Strategy.account_id.is_(None),
    ).update({"account_id": account_id}, synchronize_session="fetch")
    db.commit()


def _save_dead_letter(db, topic: str, raw: str, error: str):
    try:
        err = IngestionError(
            topic=topic, raw_message=raw[:4096], error_message=error[:2048]
        )
        db.add(err)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Failed to save dead letter to DB: %s — falling back to file", e)
        try:
            entry = json.dumps(
                {
                    "ts": datetime.now(UTC).isoformat(),
                    "topic": topic,
                    "raw": raw[:4096],
                    "error": error[:2048],
                }
            )
            with open(_DEAD_LETTER_FILE, "a") as f:
                f.write(entry + "\n")
        except Exception as fe:
            logger.error("Dead letter file fallback also failed: %s", fe)


def _configure_keepalive(conn: socket.socket) -> None:
    """Enable TCP keepalive and set a recv timeout on a client socket.

    Keepalive: the OS sends probes after 60 s of idle and drops the connection
    after 5 unanswered probes (every 10 s) — total ~110 s to detect a dead peer.
    Timeout: recv() raises TimeoutError if no data arrives within 5 minutes,
    which catches connections that are "alive" at the TCP level but not sending.
    """
    conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    if hasattr(socket, "TCP_KEEPIDLE"):
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)
    if hasattr(socket, "TCP_KEEPINTVL"):
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
    if hasattr(socket, "TCP_KEEPCNT"):
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5)
    conn.settimeout(300)  # 5 minutes — drops stale / frozen connections


def handle_client(conn: socket.socket, addr: tuple, on_event: Callable | None = None):
    """Handle a single MT5 connection in its own thread."""
    _configure_keepalive(conn)
    logger.info("MT5 connected", extra={"addr": f"{addr[0]}:{addr[1]}"})
    with _clients_lock:
        _connected_clients.add(addr)

    db = SessionLocal()
    buf = ""
    conn_account_id: str | None = None
    conn_strategies_seen: set[str] = set()

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

                    if topic == "DEAL":
                        valid = DealSchema(**data)
                        conn_strategies_seen.add(str(valid.magic))
                        process_deal(db, valid, account_id=conn_account_id)
                    elif topic == "EQUITY":
                        valid = EquitySchema(**data)
                        if str(valid.magic) != "0":
                            conn_strategies_seen.add(str(valid.magic))
                        process_equity(db, valid, account_id=conn_account_id)
                    elif topic == "ACCOUNT":
                        valid = AccountSchema(**data)
                        process_account(db, valid)
                        conn_account_id = str(valid.login)
                        _link_strategies_to_account(
                            db, conn_strategies_seen, conn_account_id
                        )
                    elif topic == "BACKTEST_START":
                        valid = BacktestStartSchema(**data)
                        process_backtest_start(db, valid)
                    elif topic == "BACKTEST_DEAL":
                        valid = BacktestDealSchema(**data)
                        process_backtest_deal(db, valid)
                    elif topic == "BACKTEST_EQUITY":
                        valid = BacktestEquitySchema(**data)
                        process_backtest_equity(db, valid)
                    elif topic == "BACKTEST_END":
                        valid = BacktestEndSchema(**data)
                        process_backtest_end(db, valid)
                    else:
                        logger.warning(
                            "Unknown topic: %s", topic, extra={"topic": topic}
                        )
                        continue

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
    finally:
        with _clients_lock:
            _connected_clients.discard(addr)
        db.close()
        conn.close()
        logger.info("MT5 disconnected", extra={"addr": f"{addr[0]}:{addr[1]}"})


def start_server(
    host: str | None = None, port: int | None = None, on_event: Callable | None = None
):
    """Start the TCP ingestion server. Accepts multiple concurrent MT5 connections."""
    global _server_start_time
    _server_start_time = datetime.now(UTC)

    host = host or settings.server_host
    port = port or settings.server_port

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server_sock.bind((host, port))
        server_sock.listen(10)
        logger.info("TCP Server listening on %s:%s", host, port)
    except Exception as e:
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
            except Exception as e:
                logger.error("Accept error: %s", e)
    finally:
        server_sock.close()


# ── Message processors ────────────────────────────────────────────


def process_deal(db, data: DealSchema, account_id: str | None = None):
    magic = str(data.magic)
    ensure_symbol_exists(db, data.symbol)
    ensure_strategy_exists(db, magic, data.symbol, account_id=account_id)
    stmt = (
        pg_insert(Deal.__table__)
        .values(
            timestamp=datetime.fromtimestamp(data.time, tz=UTC),
            ticket=data.ticket,
            strategy_id=magic,
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
    logger.debug(
        "Deal processed: ticket=%s",
        data.ticket,
        extra={"strategy_id": magic, "ticket": data.ticket},
    )


def process_equity(db, data: EquitySchema, account_id: str | None = None):
    magic = str(data.magic)
    if magic == "0":
        # magic=0 means account-level equity with no specific strategy; skip.
        return
    ensure_strategy_exists(db, magic, account_id=account_id)
    stmt = (
        pg_insert(EquityCurve.__table__)
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


def process_account(db, data: AccountSchema):
    acc_id = str(data.login)
    acc = db.query(Account).filter(Account.id == acc_id).first()
    if acc:
        acc.balance = data.balance
        acc.free_margin = data.free_margin
        acc.total_deposits = data.deposits
        acc.total_withdrawals = data.withdrawals
        logger.info("Account %s updated.", acc_id, extra={"strategy_id": acc_id})
    else:
        ensure_account_exists(db, acc_id, data.broker)

    # Margin check
    if data.free_margin < (data.balance * (settings.margin_threshold_pct / 100.0)):
        notifier.notify_low_margin(
            acc_id, data.free_margin, settings.margin_threshold_pct
        )


# ── Backtest processors ───────────────────────────────────────────────────────


def process_backtest_start(db, data: BacktestStartSchema):
    magic = str(data.magic)
    ensure_symbol_exists(db, data.symbol)
    ensure_strategy_exists(db, magic, data.symbol)
    bt = Backtest(
        strategy_id=magic,
        client_run_id=data.run_id,
        name=data.name,
        symbol=data.symbol,
        timeframe=data.timeframe,
        start_date=datetime.fromtimestamp(data.start_date, tz=UTC),
        end_date=datetime.fromtimestamp(data.end_date, tz=UTC),
        initial_balance=data.initial_balance,
        parameters=data.parameters,
        status="running",
    )
    db.merge(bt)
    db.flush()
    # Refresh to get the assigned id
    bt = (
        db.query(Backtest)
        .filter(
            Backtest.strategy_id == magic,
            Backtest.client_run_id == data.run_id,
        )
        .first()
    )
    if bt:
        key = _backtest_cache_key(magic, data.run_id)
        with _backtests_lock:
            _active_backtests[key] = bt.id
        logger.info(
            "Backtest started: id=%s strategy=%s run_id=%s",
            bt.id,
            magic,
            data.run_id,
            extra={"strategy_id": magic},
        )


def process_backtest_deal(db, data: BacktestDealSchema):
    magic = str(data.magic)
    bt_id = _get_or_lookup_backtest_id(db, magic, data.run_id)
    if bt_id is None:
        raise ValueError(
            f"Backtest not found for strategy={magic} run_id={data.run_id}"
        )
    stmt = (
        pg_insert(BacktestDeal.__table__)
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


def process_backtest_equity(db, data: BacktestEquitySchema):
    magic = str(data.magic)
    bt_id = _get_or_lookup_backtest_id(db, magic, data.run_id)
    if bt_id is None:
        raise ValueError(
            f"Backtest not found for strategy={magic} run_id={data.run_id}"
        )
    stmt = (
        pg_insert(BacktestEquity.__table__)
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


def process_backtest_end(db, data: BacktestEndSchema):
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
    # Remove from in-memory cache
    key = _backtest_cache_key(magic, data.run_id)
    with _backtests_lock:
        _active_backtests.pop(key, None)
