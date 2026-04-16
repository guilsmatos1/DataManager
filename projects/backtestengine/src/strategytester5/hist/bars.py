"""Legacy bars module compatibility."""

from trademachine.backtestengine_history.public import (
    bars_to_polars,
    get_bars_from_history,
    get_bars_from_mt5,
)

__all__ = ["bars_to_polars", "get_bars_from_history", "get_bars_from_mt5"]
