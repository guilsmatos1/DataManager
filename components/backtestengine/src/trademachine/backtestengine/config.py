"""Configuration model for BacktestEngine."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from trademachine.backtestengine_broker.public import (
    REQUIRED_TESTER_CONFIG_KEYS,
    STRING2TIMEFRAME_MAP,
    SUPPORTED_TESTER_MODELLING,
)


class BacktestConfig(BaseModel):
    """Validated runtime config derived from the legacy StrategyTester schema."""

    model_config = ConfigDict(extra="forbid")

    bot_name: str
    symbols: list[str]
    timeframe: str
    start_date: datetime
    end_date: datetime
    modelling: str
    deposit: float = Field(gt=0)
    leverage: int = Field(gt=0)

    @field_validator("symbols")
    @classmethod
    def _validate_symbols(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item and item.strip()]
        if not cleaned:
            raise ValueError("symbols must contain at least one symbol")
        return cleaned

    @field_validator("timeframe")
    @classmethod
    def _validate_timeframe(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in STRING2TIMEFRAME_MAP:
            raise ValueError(f"Invalid timeframe: {value}")
        return normalized

    @field_validator("modelling")
    @classmethod
    def _validate_modelling(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in SUPPORTED_TESTER_MODELLING:
            raise ValueError(f"Invalid modelling mode: {value}")
        return normalized

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def _parse_legacy_dates(cls, value: Any) -> datetime:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return datetime.strptime(value, "%d.%m.%Y %H:%M")
        raise TypeError("Dates must be datetime or DD.MM.YYYY HH:MM strings")

    @field_validator("leverage", mode="before")
    @classmethod
    def _parse_leverage(cls, value: Any) -> int:
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            left, right = value.split(":")
            if left != "1":
                raise ValueError("Leverage must be in the format 1:100")
            return int(right)
        raise TypeError("Leverage must be an int or 1:100 string")

    @model_validator(mode="after")
    def _validate_range(self) -> BacktestConfig:
        if self.start_date >= self.end_date:
            raise ValueError("start_date must be earlier than end_date")
        return self

    @classmethod
    def from_legacy_dict(cls, raw_config: dict[str, Any]) -> BacktestConfig:
        missing = REQUIRED_TESTER_CONFIG_KEYS - set(raw_config)
        if missing:
            raise ValueError(f"Missing tester config keys: {sorted(missing)}")
        extra = set(raw_config) - REQUIRED_TESTER_CONFIG_KEYS
        if extra:
            raise ValueError(f"Unknown tester config keys: {sorted(extra)}")
        return cls.model_validate(raw_config)

    @classmethod
    def from_json_file(cls, path: str | Path) -> BacktestConfig:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        raw_config = payload.get("tester", payload)
        return cls.from_legacy_dict(raw_config)

    def to_legacy_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="python")
