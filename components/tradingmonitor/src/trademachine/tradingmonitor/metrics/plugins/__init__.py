from __future__ import annotations

import warnings
from importlib.metadata import entry_points
from typing import TYPE_CHECKING

# Import all metric classes for backward compatibility
# These imports allow: from trademachine.tradingmonitor.metrics.plugins import SharpeRatio
from trademachine.tradingmonitor.metrics.plugins.base import BaseMetric
from trademachine.tradingmonitor.metrics.plugins.calmar import CalmarRatio
from trademachine.tradingmonitor.metrics.plugins.cvar95 import CVaR95
from trademachine.tradingmonitor.metrics.plugins.expected_value import ExpectedValue
from trademachine.tradingmonitor.metrics.plugins.max_drawdown import MaxDrawdown
from trademachine.tradingmonitor.metrics.plugins.recovery import RecoveryFactor
from trademachine.tradingmonitor.metrics.plugins.risk_reward import RiskRewardRatio
from trademachine.tradingmonitor.metrics.plugins.sharpe import SharpeRatio
from trademachine.tradingmonitor.metrics.plugins.sortino import SortinoRatio
from trademachine.tradingmonitor.metrics.plugins.var95 import VaR95

if TYPE_CHECKING:
    pass

# Default plugins list (used as fallback and for documentation)
DEFAULT_PLUGINS: list[type[BaseMetric]] = [
    SharpeRatio,
    MaxDrawdown,
    RecoveryFactor,
    SortinoRatio,
    CalmarRatio,
    VaR95,
    CVaR95,
    RiskRewardRatio,
    ExpectedValue,
]


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
    seen: set[str] = set()

    try:
        eps = entry_points(group="trademachine.metrics")
        for ep in eps:
            try:
                plugin_cls = ep.load()
                if isinstance(plugin_cls, type) and issubclass(plugin_cls, BaseMetric):
                    plugins.append(plugin_cls)
                    seen.add(ep.name)
                else:
                    warnings.warn(
                        f"Entry point '{ep.name}' is not a BaseMetric subclass, skipping.",
                        stacklevel=2,
                    )
            except Exception as e:
                warnings.warn(f"Failed to load plugin '{ep.name}': {e}", stacklevel=2)
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
    "MaxDrawdown",
    "RecoveryFactor",
    "SortinoRatio",
    "CalmarRatio",
    "VaR95",
    "CVaR95",
    "RiskRewardRatio",
    "ExpectedValue",
    "PLUGINS",
    "DEFAULT_PLUGINS",
    "discover_plugins",
]
