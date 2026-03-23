import logging
from datetime import datetime

import pandas as pd
from sqlalchemy import text
from trademachine.tradingmonitor.db.database import engine

logger = logging.getLogger("Repository")


def get_strategy_deals(strategy_id: str, since: datetime | None = None) -> pd.DataFrame:
    """Fetch deals for a specific strategy into a pandas DataFrame."""
    try:
        if since is not None:
            query = text(
                "SELECT * FROM deals WHERE strategy_id = :sid AND timestamp >= :since ORDER BY timestamp"
            )
            params = {"sid": strategy_id, "since": since}
        else:
            query = text(
                "SELECT * FROM deals WHERE strategy_id = :sid ORDER BY timestamp"
            )
            params = {"sid": strategy_id}
        return pd.read_sql(query, engine, params=params, index_col="timestamp")
    except Exception as e:
        logger.error("Failed to fetch deals for strategy %s: %s", strategy_id, e)
        return pd.DataFrame()


def get_strategy_equity_curve(strategy_id: str) -> pd.DataFrame:
    """Fetch the equity curve for a specific strategy."""
    try:
        query = text(
            "SELECT * FROM equity_curve WHERE strategy_id = :sid ORDER BY timestamp"
        )
        return pd.read_sql(
            query, engine, params={"sid": strategy_id}, index_col="timestamp"
        )
    except Exception as e:
        logger.error("Failed to fetch equity curve for strategy %s: %s", strategy_id, e)
        return pd.DataFrame()


def get_backtest_deals(backtest_id: int) -> pd.DataFrame:
    """Fetch all deals for a backtest run."""
    try:
        query = text(
            "SELECT * FROM backtest_deals WHERE backtest_id = :bid ORDER BY timestamp"
        )
        return pd.read_sql(
            query, engine, params={"bid": backtest_id}, index_col="timestamp"
        )
    except Exception as e:
        logger.error("Failed to fetch deals for backtest %s: %s", backtest_id, e)
        return pd.DataFrame()


def get_backtest_equity(backtest_id: int) -> pd.DataFrame:
    """Fetch the equity curve for a backtest run."""
    try:
        query = text(
            "SELECT * FROM backtest_equity WHERE backtest_id = :bid ORDER BY timestamp"
        )
        return pd.read_sql(
            query, engine, params={"bid": backtest_id}, index_col="timestamp"
        )
    except Exception as e:
        logger.error("Failed to fetch equity for backtest %s: %s", backtest_id, e)
        return pd.DataFrame()
