"""Public API for the metrics component.

This is the ONLY module bases and other components should import from.
"""

from trademachine.metrics.engine import compute_all, compute_subset
from trademachine.metrics.types import (
    EquityPoint,
    MetricsInput,
    MetricsResult,
    Side,
    TradeRecord,
)

__all__ = [
    "EquityPoint",
    "MetricsInput",
    "MetricsResult",
    "Side",
    "TradeRecord",
    "compute_all",
    "compute_subset",
]
