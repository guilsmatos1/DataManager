from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

import pandas as pd


class BaseMetric(ABC):
    """Base class for all metrics plugins."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the metric to be displayed in the results dictionary."""
        pass

    @property
    def is_advanced(self) -> bool:
        """Whether this metric is only calculated in advanced mode."""
        return False

    def _safe_calc(
        self, func: Callable[[pd.Series], Any], returns: pd.Series | None
    ) -> float | None:
        """Guard-and-call helper shared by all quantstats-based plugins."""
        if returns is None or returns.empty:
            return None
        try:
            return float(func(returns))
        except (ValueError, ZeroDivisionError):
            return None

    @abstractmethod
    def calculate(
        self,
        deals_df: pd.DataFrame,
        daily_returns: pd.Series | None = None,
        **kwargs: Any,
    ) -> Any:
        """
        Calculate the metric.
        :param deals_df: DataFrame containing all trades.
        :param daily_returns: Optional pandas Series of daily returns from the equity curve.
        :param kwargs: Additional arguments for specific metrics.
        :return: The calculated value (float, int, or None).
        """
        pass
