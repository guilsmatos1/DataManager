import logging
from datetime import datetime

import pandas as pd
from sqlalchemy import text
from trademachine.core.logger import LOGGER_NAME
from trademachine.tradingmonitor_storage.public import engine

logger = logging.getLogger(LOGGER_NAME)


class MetricsRepositoryError(RuntimeError):
    """Raised when TradingMonitor metrics queries fail unexpectedly."""


def _read_dataframe(
    query_name: str,
    query,
    params: dict[str, object],
) -> pd.DataFrame:
    try:
        return pd.read_sql(query, engine, params=params, index_col="timestamp")
    except Exception as exc:
        logger.exception("Failed to fetch metrics data for %s", query_name)
        raise MetricsRepositoryError(
            f"Failed to fetch metrics data for {query_name}"
        ) from exc


def get_strategy_deals(strategy_id: str, since: datetime | None = None) -> pd.DataFrame:
    """Fetch deals for a specific strategy into a pandas DataFrame."""
    if since is not None:
        query = text(
            "SELECT * FROM deals WHERE strategy_id = :sid AND timestamp >= :since ORDER BY timestamp"
        )
        params = {"sid": strategy_id, "since": since}
    else:
        query = text("SELECT * FROM deals WHERE strategy_id = :sid ORDER BY timestamp")
        params = {"sid": strategy_id}
    return _read_dataframe(f"strategy deals for {strategy_id}", query, params)


def get_strategy_equity_curve(strategy_id: str) -> pd.DataFrame:
    """Fetch the equity curve for a specific strategy."""
    query = text(
        "SELECT * FROM equity_curve WHERE strategy_id = :sid ORDER BY timestamp"
    )
    return _read_dataframe(
        f"strategy equity for {strategy_id}", query, {"sid": strategy_id}
    )


def get_backtest_deals(backtest_id: int) -> pd.DataFrame:
    """Fetch all deals for a backtest run."""
    query = text(
        "SELECT * FROM backtest_deals WHERE backtest_id = :bid ORDER BY timestamp"
    )
    return _read_dataframe(
        f"backtest deals for {backtest_id}", query, {"bid": backtest_id}
    )


def get_backtest_equity(backtest_id: int) -> pd.DataFrame:
    """Fetch the equity curve for a backtest run."""
    query = text(
        "SELECT * FROM backtest_equity WHERE backtest_id = :bid ORDER BY timestamp"
    )
    return _read_dataframe(
        f"backtest equity for {backtest_id}", query, {"bid": backtest_id}
    )
