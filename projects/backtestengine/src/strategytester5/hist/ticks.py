"""Legacy ticks module compatibility."""

from trademachine.backtestengine_history.public import (
    generate_ticks_from_bar,
    generate_ticks_from_bars,
    get_ticks_from_history,
    get_ticks_from_mt5,
    ticks_to_polars,
)

__all__ = [
    "generate_ticks_from_bar",
    "generate_ticks_from_bars",
    "get_ticks_from_history",
    "get_ticks_from_mt5",
    "ticks_to_polars",
]
