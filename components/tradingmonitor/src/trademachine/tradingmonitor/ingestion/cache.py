"""In-memory caches for the ingestion server.

Provides thread-safe in-memory caches for strategies, accounts, symbols,
active backtests, and deal counters.
"""

from __future__ import annotations

import threading

# ── Strategy cache ─────────────────────────────────────────────────────────────
EXISTING_STRATEGIES: set[str] = set()
_strategies_lock = threading.Lock()


# ── Account cache ──────────────────────────────────────────────────────────────
EXISTING_ACCOUNTS: set[str] = set()
_accounts_lock = threading.Lock()


# ── Symbol cache ───────────────────────────────────────────────────────────────
EXISTING_SYMBOLS: set[str] = set()
_symbols_lock = threading.Lock()


# ── Backtest cache ─────────────────────────────────────────────────────────────
_active_backtests: dict[str, int] = {}  # "strategy_id:run_id" → backtest DB id
_backtests_lock = threading.Lock()


# ── Deal counters (for drift checking) ─────────────────────────────────────────
_deal_counters: dict[str, int] = {}  # strategy_id → count
_counters_lock = threading.Lock()


def invalidate_cache(
    strategy_id: str | None = None, account_id: str | None = None
) -> None:
    """Remove entries from in-memory strategy/account caches.

    Call this whenever a strategy or account is deleted so that the next
    incoming message triggers a fresh DB lookup instead of using a stale
    cache entry.
    """
    if strategy_id is not None:
        with _strategies_lock:
            EXISTING_STRATEGIES.discard(strategy_id)
    if account_id is not None:
        with _accounts_lock:
            EXISTING_ACCOUNTS.discard(account_id)
