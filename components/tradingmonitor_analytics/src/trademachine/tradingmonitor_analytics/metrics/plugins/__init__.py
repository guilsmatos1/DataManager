from __future__ import annotations

import warnings
from importlib.metadata import EntryPoint, entry_points
from typing import TYPE_CHECKING

# Import all metric classes for backward compatibility
# These imports allow: from trademachine.tradingmonitor_analytics.metrics.plugins import SharpeRatio
from trademachine.tradingmonitor_analytics.metrics.plugins.base import BaseMetric
from trademachine.tradingmonitor_analytics.metrics.plugins.calmar import CalmarRatio
from trademachine.tradingmonitor_analytics.metrics.plugins.cvar95 import CVaR95
from trademachine.tradingmonitor_analytics.metrics.plugins.max_drawdown import (
    DrawdownMetric,
)
from trademachine.tradingmonitor_analytics.metrics.plugins.recovery import (
    RetDDMetric,
)
from trademachine.tradingmonitor_analytics.metrics.plugins.risk_reward import (
    RiskRewardRatio,
)
from trademachine.tradingmonitor_analytics.metrics.plugins.sharpe import SharpeRatio
from trademachine.tradingmonitor_analytics.metrics.plugins.sortino import SortinoRatio
from trademachine.tradingmonitor_analytics.metrics.plugins.var95 import VaR95

if TYPE_CHECKING:
    pass

# Default plugins list (used as fallback and for documentation)
DEFAULT_PLUGINS: list[type[BaseMetric]] = [
    SharpeRatio,
    DrawdownMetric,
    RetDDMetric,
    SortinoRatio,
    CalmarRatio,
    VaR95,
    CVaR95,
    RiskRewardRatio,
]

LEGACY_PLUGIN_NAME_ALIASES = {
    "max_drawdown": "drawdown",
    "recovery": "ret_dd",
}


def _entry_point_priority(entry_point: EntryPoint) -> tuple[int, str]:
    """Prefer current analytics plugins over legacy duplicates with the same name."""
    return (
        0
        if entry_point.value.startswith("trademachine.tradingmonitor_analytics.")
        else 1,
        entry_point.value,
    )


def discover_plugins() -> list[type[BaseMetric]]:
    """Discover metric plugins via entry points.

    Allows external packages to register metrics by adding entry points
    under 'trademachine.metrics' in their pyproject.toml:

        [project.entry-points."trademachine.metrics"]
        my_metric = "my_package.metrics:MyMetric"

    Returns:
        List of metric class types discovered via entry points.
        Falls back to DEFAULT_PLUGINS if discovery fails.
    """
    plugins: list[type[BaseMetric]] = []

    try:
        grouped_entry_points: dict[str, list[EntryPoint]] = {}
        for entry_point in entry_points(group="trademachine.metrics"):
            canonical_name = LEGACY_PLUGIN_NAME_ALIASES.get(
                entry_point.name, entry_point.name
            )
            grouped_entry_points.setdefault(canonical_name, []).append(entry_point)

        for name, candidates in grouped_entry_points.items():
            errors: list[str] = []
            for candidate in sorted(candidates, key=_entry_point_priority):
                try:
                    plugin_cls = candidate.load()
                    if not (
                        isinstance(plugin_cls, type)
                        and issubclass(plugin_cls, BaseMetric)
                    ):
                        errors.append(f"{candidate.value} is not a BaseMetric subclass")
                        continue
                    plugins.append(plugin_cls)
                    break
                except Exception as exc:
                    errors.append(f"{candidate.value}: {exc}")
            else:
                warnings.warn(
                    f"Failed to load plugin '{name}': {'; '.join(errors)}",
                    stacklevel=2,
                )
    except Exception as e:
        warnings.warn(
            f"Entry point discovery failed: {e}. Using default plugins.", stacklevel=2
        )

    # If no plugins discovered via entry points, fall back to defaults
    if not plugins:
        plugins = DEFAULT_PLUGINS.copy()
    else:
        # Ensure default plugins are included (in case entry points miss some)
        for plugin_cls in DEFAULT_PLUGINS:
            if plugin_cls not in plugins:
                plugins.append(plugin_cls)

    return plugins


# PLUGINS is the main interface used by the calculator
PLUGINS = discover_plugins()

__all__ = [
    "BaseMetric",
    "SharpeRatio",
    "DrawdownMetric",
    "RetDDMetric",
    "SortinoRatio",
    "CalmarRatio",
    "VaR95",
    "CVaR95",
    "RiskRewardRatio",
    "PLUGINS",
    "DEFAULT_PLUGINS",
    "discover_plugins",
]
