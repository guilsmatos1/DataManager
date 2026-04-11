from typing import Literal

from pydantic import BaseModel, field_validator, model_validator

_MIN_TS = 946_684_800  # 2000-01-01 UTC — reject clearly invalid timestamps
_MAX_TS = 4_102_444_800  # 2100-01-01 UTC


class _TimestampMixin(BaseModel):
    """Validates any field named 'time', 'start_date', or 'end_date' as a unix timestamp."""

    @field_validator(
        "time", "start_date", "end_date", mode="before", check_fields=False
    )
    @classmethod
    def _validate_unix_ts(cls, v: int) -> int:
        if not (_MIN_TS <= v <= _MAX_TS):
            raise ValueError(f"timestamp {v} is out of valid range [2000, 2100]")
        return v


class _TradingFieldsMixin(BaseModel):
    """Mixin that validates trading fields. Subclasses must define type, volume, price."""

    type: str
    volume: float
    price: float

    @model_validator(mode="after")
    def _validate_trading_fields(self) -> "_TradingFieldsMixin":
        if self.type != "balance":
            if self.volume <= 0:
                raise ValueError(
                    f"volume must be > 0 for trading deals, got {self.volume}"
                )
            if self.price < 0:
                raise ValueError(f"price cannot be negative, got {self.price}")
        return self


class _RuntimeContextMixin(BaseModel):
    """Optional runtime context that may piggyback on any MT5 payload."""

    open_profit: float | None = None
    open_trades_count: int | None = None
    pending_orders_count: int | None = None

    @field_validator("open_trades_count", "pending_orders_count")
    @classmethod
    def _validate_optional_non_negative_counts(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError(f"count must be >= 0, got {v}")
        return v


class DealSchema(_TimestampMixin, _TradingFieldsMixin, _RuntimeContextMixin):
    time: int
    ticket: int
    magic: int
    symbol: str
    type: Literal["buy", "sell", "balance"]
    volume: float
    price: float
    profit: float
    commission: float = 0.0
    swap: float = 0.0


class EquitySchema(_TimestampMixin, _RuntimeContextMixin):
    time: int
    magic: int
    balance: float
    equity: float


class AccountSchema(_TimestampMixin, _RuntimeContextMixin):
    time: int | None = None
    magic: int | None = None
    login: int
    broker: str
    balance: float
    free_margin: float
    deposits: float = 0.0
    withdrawals: float = 0.0


class StrategyRuntimeSchema(_TimestampMixin):
    time: int
    magic: int
    open_profit: float = 0.0
    open_trades_count: int = 0
    pending_orders_count: int = 0

    @field_validator("open_trades_count", "pending_orders_count")
    @classmethod
    def _validate_non_negative_counts(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"count must be >= 0, got {v}")
        return v


# ── Backtest schemas ──────────────────────────────────────────────────────────


class BacktestStartSchema(_TimestampMixin):
    magic: int
    run_id: int  # EA-generated unique ID for this run (e.g. unix timestamp)
    symbol: str
    timeframe: str
    start_date: int  # unix timestamp
    end_date: int  # unix timestamp
    initial_balance: float
    name: str | None = None
    parameters: dict | None = None  # EA input parameters (sent as JSON object)


class BacktestDealSchema(_TimestampMixin, _TradingFieldsMixin):
    magic: int
    run_id: int
    time: int
    ticket: int
    symbol: str
    type: Literal["buy", "sell", "balance"]
    volume: float
    price: float
    profit: float
    commission: float = 0.0
    swap: float = 0.0


class BacktestEquitySchema(_TimestampMixin):
    magic: int
    run_id: int
    time: int
    balance: float
    equity: float


class BacktestEndSchema(BaseModel):
    magic: int
    run_id: int
    status: Literal["complete", "failed"] = "complete"
