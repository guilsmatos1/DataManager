"""Thin compatibility layer for the legacy StrategyTester5 package."""

from __future__ import annotations

import logging as logging
import warnings

from trademachine.backtestengine.public import (
    BUY_ACTIONS,
    DEAL_TYPE_MAP,
    MT5_AVAILABLE,
    ORDER_TYPE_MAP,
    REQUIRED_TESTER_CONFIG_KEYS,
    SELL_ACTIONS,
    STRING2TIMEFRAME_MAP,
    SUPPORTED_TESTER_MODELLING,
    TIMEFRAME2STRING_MAP,
    AccountInfo,
    BacktestConfig,
    BacktestEngine,
    HistoryManager,
    MarginEvent,
    MetaTrader5,
    PeriodSeconds,
    SnapshotExporters,
    SnapshotImporters,
    SymbolInfo,
    Tick,
    TradeDeal,
    TradeExecutor,
    TradeOrder,
    TradePosition,
    ensure_utc,
    evaluate_margin_state,
    make_tick,
    make_tick_from_dict,
    make_tick_from_tuple,
    month_bounds,
    no_mt5_runtime_error,
)
from trademachine.core.logger import setup_logger

__version__ = "0.1.0"
__author__ = "TradeMachine"


def _warn_deprecated() -> None:
    warnings.warn(
        "strategytester5 compatibility imports are deprecated. Prefer trademachine.backtestengine.public.",
        DeprecationWarning,
        stacklevel=2,
    )


def get_logger(name: str, logfile: str = "log.log", level: int = logging.INFO):
    """Compatibility helper matching the legacy package."""
    _warn_deprecated()
    return setup_logger(name=name, log_path=logfile, level=level)


StrategyTester = BacktestEngine
CTrade = TradeExecutor
Importers = SnapshotImporters
Exporters = SnapshotExporters

__all__ = [
    "AccountInfo",
    "BUY_ACTIONS",
    "BacktestConfig",
    "CTrade",
    "DEAL_TYPE_MAP",
    "Exporters",
    "HistoryManager",
    "Importers",
    "MT5_AVAILABLE",
    "MarginEvent",
    "MetaTrader5",
    "ORDER_TYPE_MAP",
    "PeriodSeconds",
    "REQUIRED_TESTER_CONFIG_KEYS",
    "SELL_ACTIONS",
    "STRING2TIMEFRAME_MAP",
    "SUPPORTED_TESTER_MODELLING",
    "SnapshotExporters",
    "SnapshotImporters",
    "StrategyTester",
    "SymbolInfo",
    "TIMEFRAME2STRING_MAP",
    "Tick",
    "TradeDeal",
    "TradeOrder",
    "TradePosition",
    "ensure_utc",
    "evaluate_margin_state",
    "get_logger",
    "logging",
    "make_tick",
    "make_tick_from_dict",
    "make_tick_from_tuple",
    "month_bounds",
    "no_mt5_runtime_error",
]
