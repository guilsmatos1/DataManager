"""
Unit tests for components/tradingmonitor_ingestion/src/trademachine/tradingmonitor_ingestion/ingestion/schemas.py

These tests cover Pydantic validation logic only — no DB, no network.
Each test exercises a specific validation rule or default value.
"""

import pytest
from pydantic import ValidationError
from trademachine.tradingmonitor_ingestion.ingestion.schemas import (
    AccountSchema,
    BacktestEndSchema,
    BacktestStartSchema,
    DealSchema,
    EquitySchema,
)

# ── Shared valid timestamps ────────────────────────────────────────────────────

_VALID_TS = 1_700_000_000  # 2023-11-14 — well within [2000, 2100]
_BEFORE_2000 = 946_684_799  # 1999-12-31 23:59:59 — one second before minimum
_AFTER_2100 = 4_102_444_801  # one second after maximum


# ── DealSchema ────────────────────────────────────────────────────────────────


class TestDealSchema:
    def _valid(self, **overrides) -> dict:
        base = dict(
            time=_VALID_TS,
            ticket=1001,
            magic=42,
            symbol="EURUSD",
            type="buy",
            volume=0.1,
            price=1.0800,
            profit=50.0,
        )
        base.update(overrides)
        return base

    def test_valid_buy_deal_parses_correctly(self):
        # Arrange
        data = self._valid()
        # Act
        deal = DealSchema(**data)
        # Assert
        assert deal.ticket == 1001
        assert deal.magic == 42
        assert deal.type == "buy"
        assert deal.commission == 0.0  # default
        assert deal.swap == 0.0  # default

    def test_valid_sell_deal_parses_correctly(self):
        deal = DealSchema(**self._valid(type="sell"))
        assert deal.type == "sell"

    def test_balance_type_is_accepted(self):
        deal = DealSchema(**self._valid(type="balance"))
        assert deal.type == "balance"

    def test_invalid_type_raises_validation_error(self):
        # Arrange — "long" is not a valid literal
        data = self._valid(type="long")
        # Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            DealSchema(**data)
        errors = exc_info.value.errors()
        assert any("type" in str(e["loc"]) for e in errors)

    def test_timestamp_before_year_2000_is_rejected(self):
        data = self._valid(time=_BEFORE_2000)
        with pytest.raises(ValidationError) as exc_info:
            DealSchema(**data)
        assert any("time" in str(e["loc"]) for e in exc_info.value.errors())

    def test_timestamp_after_year_2100_is_rejected(self):
        data = self._valid(time=_AFTER_2100)
        with pytest.raises(ValidationError):
            DealSchema(**data)

    def test_timestamp_at_exact_lower_bound_is_accepted(self):
        deal = DealSchema(**self._valid(time=946_684_800))  # 2000-01-01 00:00:00
        assert deal.time == 946_684_800

    def test_timestamp_at_exact_upper_bound_is_accepted(self):
        deal = DealSchema(**self._valid(time=4_102_444_800))  # 2100-01-01 00:00:00
        assert deal.time == 4_102_444_800

    def test_commission_and_swap_have_zero_defaults(self):
        data = {
            k: v for k, v in self._valid().items() if k not in ("commission", "swap")
        }
        deal = DealSchema(**data)
        assert deal.commission == 0.0
        assert deal.swap == 0.0

    def test_explicit_commission_and_swap_are_stored(self):
        deal = DealSchema(**self._valid(commission=-2.5, swap=-0.3))
        assert deal.commission == -2.5
        assert deal.swap == -0.3

    def test_optional_runtime_context_is_accepted(self):
        deal = DealSchema(
            **self._valid(
                open_profit=12.5,
                open_trades_count=2,
                pending_orders_count=1,
            )
        )
        assert deal.open_profit == 12.5
        assert deal.open_trades_count == 2
        assert deal.pending_orders_count == 1

    def test_missing_required_field_raises_validation_error(self):
        data = self._valid()
        del data["symbol"]
        with pytest.raises(ValidationError):
            DealSchema(**data)

    def test_negative_profit_is_accepted(self):
        # Losses are a normal trading outcome — not a validation error
        deal = DealSchema(**self._valid(profit=-75.0))
        assert deal.profit == -75.0

    def test_magic_number_zero_is_accepted_by_schema(self):
        # Schema accepts magic=0; the processor layer filters it out for EQUITY
        deal = DealSchema(**self._valid(magic=0))
        assert deal.magic == 0


# ── EquitySchema ──────────────────────────────────────────────────────────────


class TestEquitySchema:
    def test_valid_equity_parses_correctly(self):
        equity = EquitySchema(
            time=_VALID_TS, magic=100, balance=10000.0, equity=10050.0
        )
        assert equity.balance == 10000.0
        assert equity.equity == 10050.0

    def test_magic_zero_is_valid_at_schema_level(self):
        # magic=0 means account-level; the processor skips it, but schema allows it
        equity = EquitySchema(time=_VALID_TS, magic=0, balance=50000.0, equity=50100.0)
        assert equity.magic == 0

    def test_equity_less_than_balance_is_accepted(self):
        # Equity < balance when there are open losing positions — valid
        equity = EquitySchema(time=_VALID_TS, magic=42, balance=10000.0, equity=9500.0)
        assert equity.equity < equity.balance

    def test_invalid_timestamp_raises_validation_error(self):
        with pytest.raises(ValidationError):
            EquitySchema(time=_BEFORE_2000, magic=42, balance=1.0, equity=1.0)


# ── AccountSchema ─────────────────────────────────────────────────────────────


class TestAccountSchema:
    def test_valid_account_parses_correctly(self):
        acc = AccountSchema(
            login=123456, broker="XPTO", balance=10000.0, free_margin=8000.0
        )
        assert acc.login == 123456
        assert acc.deposits == 0.0  # default
        assert acc.withdrawals == 0.0  # default

    def test_missing_broker_raises_validation_error(self):
        with pytest.raises(ValidationError):
            AccountSchema(login=1, balance=1.0, free_margin=1.0)

    def test_explicit_deposits_and_withdrawals(self):
        acc = AccountSchema(
            login=1,
            broker="B",
            balance=5000.0,
            free_margin=4000.0,
            deposits=10000.0,
            withdrawals=5000.0,
        )
        assert acc.deposits == 10000.0
        assert acc.withdrawals == 5000.0

    def test_optional_runtime_context_is_accepted(self):
        acc = AccountSchema(
            time=_VALID_TS,
            magic=42,
            login=1,
            broker="B",
            balance=5000.0,
            free_margin=4000.0,
            open_profit=25.0,
            open_trades_count=3,
            pending_orders_count=2,
        )
        assert acc.time == _VALID_TS
        assert acc.magic == 42
        assert acc.open_profit == 25.0
        assert acc.open_trades_count == 3
        assert acc.pending_orders_count == 2


# ── BacktestStartSchema ───────────────────────────────────────────────────────


class TestBacktestStartSchema:
    def test_valid_backtest_start_parses_correctly(self):
        bt = BacktestStartSchema(
            magic=99,
            run_id=1000,
            symbol="GBPUSD",
            timeframe="H1",
            start_date=_VALID_TS,
            end_date=_VALID_TS + 86400,
            initial_balance=50000.0,
        )
        assert bt.name is None  # optional
        assert bt.parameters is None  # optional

    def test_optional_name_and_parameters_accepted(self):
        bt = BacktestStartSchema(
            magic=1,
            run_id=2,
            symbol="X",
            timeframe="M15",
            start_date=_VALID_TS,
            end_date=_VALID_TS + 1,
            initial_balance=1000.0,
            name="Run Alpha",
            parameters={"risk": 1.0, "tp": 50},
        )
        assert bt.name == "Run Alpha"
        assert bt.parameters["risk"] == 1.0

    def test_invalid_start_date_raises_validation_error(self):
        with pytest.raises(ValidationError):
            BacktestStartSchema(
                magic=1,
                run_id=2,
                symbol="X",
                timeframe="M15",
                start_date=_BEFORE_2000,
                end_date=_VALID_TS,
                initial_balance=1000.0,
            )


# ── BacktestEndSchema ─────────────────────────────────────────────────────────


class TestBacktestEndSchema:
    def test_default_status_is_complete(self):
        bt = BacktestEndSchema(magic=1, run_id=42)
        assert bt.status == "complete"

    def test_failed_status_accepted(self):
        bt = BacktestEndSchema(magic=1, run_id=42, status="failed")
        assert bt.status == "failed"

    def test_invalid_status_raises_validation_error(self):
        with pytest.raises(ValidationError):
            BacktestEndSchema(magic=1, run_id=42, status="cancelled")
