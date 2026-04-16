"""Legacy tester config validator compatibility."""

from __future__ import annotations

from typing import Any

from trademachine.backtestengine.public import BacktestConfig


class TesterConfigValidators:
    """Compatibility wrapper around BacktestConfig."""

    @staticmethod
    def parse_tester_configs(raw_config: dict[str, Any]) -> dict[str, Any]:
        return BacktestConfig.from_legacy_dict(raw_config).to_legacy_dict()
