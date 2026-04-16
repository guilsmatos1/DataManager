"""Business-logic processors for ingested MT5 messages.

Pure DB operations, entity auto-registration, drift checking,
and dead-letter handling. No socket or transport concerns.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime

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
    Strategy,
    StrategyRuntimeSnapshot,
    Symbol,
    insert_deal_if_new,
    notifier,
    settings,
)

logger = logging.getLogger("TCPServer")

# ── Constants ────────────────────────────────────────────────────────────────────
DRIFT_CHECK_INTERVAL = 10

# ── Caches & locks ───────────────────────────────────────────────────────────────
EXISTING_STRATEGIES: set[str] = set()
EXISTING_ACCOUNTS: set[str] = set()
EXISTING_SYMBOLS: set[str] = set()
_active_backtests: dict[str, int] = {}  # "strategy_id:run_id" → backtest DB id
_deal_counters: dict[str, int] = {}

_backtests_lock = threading.Lock()
_counters_lock = threading.Lock()

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


def save_dead_letter(db: Session, topic: str, raw: str, error: str) -> None:
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


# ── Cache helpers ────────────────────────────────────────────────────────────────


def invalidate_cache(
    strategy_id: str | None = None, account_id: str | None = None
) -> None:
    """Remove entries from in-memory strategy/account caches."""
    if strategy_id is not None:
        EXISTING_STRATEGIES.discard(strategy_id)
    if account_id is not None:
        EXISTING_ACCOUNTS.discard(account_id)


def _backtest_cache_key(strategy_id: str, run_id: int) -> str:
    return f"{strategy_id}:{run_id}"


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


# ── Entity auto-registration ─────────────────────────────────────────────────────


def _get_symbol_id(db: Session, symbol: str | None) -> int | None:
    if not symbol:
        return None
    row = db.query(Symbol.id).filter(Symbol.name == symbol).first()
    return int(row[0]) if row is not None else None


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


def link_strategies_to_account(
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


# ── Runtime context extraction ───────────────────────────────────────────────────


def build_runtime_schema_from_payload(
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


def maybe_process_runtime_context(
    db: Session,
    data: DealSchema | EquitySchema | AccountSchema,
    account_id: str | None = None,
) -> None:
    """Persist runtime context when it is bundled into another MT5 payload."""
    runtime_data = build_runtime_schema_from_payload(data)
    if runtime_data is None:
        return
    process_strategy_runtime(db, runtime_data, account_id=account_id)


# ── Drift checking ───────────────────────────────────────────────────────────────


def maybe_check_drift(strategy_id: str) -> None:
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


# ── Live message processors ──────────────────────────────────────────────────────


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
    maybe_check_drift(magic)


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


# ── Backtest processors ──────────────────────────────────────────────────────────


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
