"""
SQX Parser Module
=================
Parses StrategyQuant X CSV export files into numpy returns arrays.

SQX format: semicolon-delimited CSV, quoted fields, 20 columns.
Each row represents a complete round-trip trade (open + close).
"""

import glob
import logging
import os
from pathlib import Path

import numpy as np
import pandas as pd

from portifoliomaster.utils.logger import LOGGER_NAME

logger = logging.getLogger(LOGGER_NAME)

# Column indices (0-based) used for parsing.
# The SQX CSV has duplicate column names ("Close type" appears twice, "Close time" appears twice),
# so positional access is safer than label access for those columns.
_COL_CLOSE_TIME = 6  # "Close time" (first occurrence, index 6)
_COL_PROFIT_LOSS = 8  # "Profit/Loss"
_COL_COMM_SWAP = 19  # "Comm/Swap"


def parse_sqx_csv(filepath: str) -> tuple[str, np.ndarray, list[str]]:
    """Parses a single SQX CSV file.

    Args:
        filepath: Path to the SQX semicolon-delimited CSV file.

    Returns:
        Tuple of (strategy_name, net_returns_array, close_timestamps_list).
        net_returns_array: float64 array where each element = Profit/Loss + Comm/Swap.
        close_timestamps_list: list of close time strings (format "YYYY.MM.DD HH:MM:SS").

    Raises:
        ValueError: If the file cannot be parsed or required columns are missing.
    """
    strategy_name = Path(filepath).stem

    try:
        df = pd.read_csv(filepath, sep=";", quotechar='"', header=0)
    except Exception as e:
        raise ValueError(f"Failed to read SQX CSV '{filepath}': {e}") from e

    if df.empty:
        logger.warning(f"SQX file '{filepath}' contains no trades.")
        return strategy_name, np.array([], dtype=np.float64), []

    # Use positional access for duplicate-named columns
    profit_loss = pd.to_numeric(df.iloc[:, _COL_PROFIT_LOSS], errors="coerce").fillna(0.0)
    comm_swap = pd.to_numeric(df.iloc[:, _COL_COMM_SWAP], errors="coerce").fillna(0.0)
    net_profit = (profit_loss + comm_swap).to_numpy(dtype=np.float64)

    timestamps = df.iloc[:, _COL_CLOSE_TIME].astype(str).tolist()

    return strategy_name, net_profit, timestamps


def parse_sqx_directory(directory: str) -> dict[str, tuple[np.ndarray, list[str]]]:
    """Parses all SQX CSV files in a directory.

    Args:
        directory: Path to directory containing SQX CSV files.

    Returns:
        Dict mapping strategy_name → (returns_array, timestamps_list).
        Skips files that fail to parse (logs a warning).
    """
    if not os.path.isdir(directory):
        raise ValueError(f"SQX directory not found: '{directory}'")

    csv_files = glob.glob(os.path.join(directory, "*.csv"))
    if not csv_files:
        logger.warning(f"No CSV files found in SQX directory: '{directory}'")
        return {}

    result: dict[str, tuple[np.ndarray, list[str]]] = {}
    for filepath in sorted(csv_files):
        try:
            name, returns, timestamps = parse_sqx_csv(filepath)
            result[name] = (returns, timestamps)
        except ValueError as e:
            logger.warning(f"Skipped SQX file '{os.path.basename(filepath)}': {e}")

    logger.info(f"[SQX] Parsed {len(result)} strategies from '{directory}'.")
    return result
