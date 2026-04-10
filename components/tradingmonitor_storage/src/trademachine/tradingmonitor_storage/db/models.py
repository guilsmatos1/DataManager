import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class DealType(enum.Enum):
    BUY = "BUY"
    SELL = "SELL"
    BALANCE = "BALANCE"


# Association table for Portfolio-Strategy many-to-many relationship
portfolio_strategy = Table(
    "portfolio_strategy",
    Base.metadata,
    Column("portfolio_id", ForeignKey("portfolios.id"), primary_key=True),
    Column("strategy_id", ForeignKey("strategies.id"), primary_key=True),
    Index("ix_portfolio_strategy_strategy_id", "strategy_id"),
)


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(
        String, primary_key=True
    )  # Account Number (MT5 Login)
    name: Mapped[str | None] = mapped_column(String)
    broker: Mapped[str | None] = mapped_column(String)
    account_type: Mapped[str | None] = mapped_column(String)  # Real, Demo, etc.
    currency: Mapped[str | None] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(String)
    balance: Mapped[float] = mapped_column(
        Numeric(18, 8), default=0.0, server_default=text("0")
    )
    free_margin: Mapped[float] = mapped_column(
        Numeric(18, 8), default=0.0, server_default=text("0")
    )
    total_deposits: Mapped[float] = mapped_column(
        Numeric(18, 8), default=0.0, server_default=text("0")
    )
    total_withdrawals: Mapped[float] = mapped_column(
        Numeric(18, 8), default=0.0, server_default=text("0")
    )

    strategies: Mapped[list["Strategy"]] = relationship(back_populates="account")


class Strategy(Base):
    __tablename__ = "strategies"
    __table_args__ = (
        Index("ix_strategies_account_id", "account_id"),
        Index("ix_strategies_symbol_id", "symbol_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)  # MT5 Magic Number
    name: Mapped[str | None] = mapped_column(String)
    symbol: Mapped[str | None] = mapped_column(String)
    symbol_id: Mapped[int | None] = mapped_column(
        ForeignKey("symbols.id", ondelete="RESTRICT")
    )
    timeframe: Mapped[str | None] = mapped_column(String)
    operational_style: Mapped[str | None] = mapped_column(String)
    trade_duration: Mapped[str | None] = mapped_column(String)
    initial_balance: Mapped[float | None] = mapped_column(
        Numeric(18, 8), default=100_000.0
    )
    base_currency: Mapped[str | None] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(String)
    live: Mapped[bool] = mapped_column(
        default=False, nullable=False, server_default=text("false")
    )  # False = Incubação
    real_account: Mapped[bool] = mapped_column(
        default=False, nullable=False, server_default=text("false")
    )  # False = Demo
    max_allowed_drawdown: Mapped[float | None] = mapped_column(
        Numeric(6, 2), nullable=True
    )  # % limit, e.g. 20.0 = 20%

    account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id"))

    account: Mapped["Account"] = relationship(back_populates="strategies")
    symbol_record: Mapped["Symbol | None"] = relationship(
        foreign_keys=[symbol_id], back_populates="strategies"
    )
    deals: Mapped[list["Deal"]] = relationship(
        back_populates="strategy", cascade="all, delete-orphan"
    )
    equity_curve: Mapped[list["EquityCurve"]] = relationship(
        back_populates="strategy", cascade="all, delete-orphan"
    )
    portfolios: Mapped[list["Portfolio"]] = relationship(
        secondary=portfolio_strategy, back_populates="strategies"
    )
    backtests: Mapped[list["Backtest"]] = relationship(
        back_populates="strategy", cascade="all, delete-orphan"
    )


class Portfolio(Base):
    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str | None] = mapped_column(String)
    initial_balance: Mapped[float | None] = mapped_column(Numeric(18, 8))
    description: Mapped[str | None] = mapped_column(String)
    live: Mapped[bool] = mapped_column(default=False)
    real_account: Mapped[bool] = mapped_column(default=False)

    strategies: Mapped[list["Strategy"]] = relationship(
        secondary=portfolio_strategy, back_populates="portfolios"
    )


class Benchmark(Base):
    __tablename__ = "benchmarks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    asset: Mapped[str] = mapped_column(String, nullable=False)
    timeframe: Mapped[str] = mapped_column(String, default="D1")
    description: Mapped[str | None] = mapped_column(String)
    is_default: Mapped[bool] = mapped_column(default=False)
    enabled: Mapped[bool] = mapped_column(default=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)

    prices: Mapped[list["BenchmarkPrice"]] = relationship(
        back_populates="benchmark", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "source", "asset", "timeframe", name="uq_benchmark_source_asset_tf"
        ),
    )


class BenchmarkPrice(Base):
    __tablename__ = "benchmark_prices"

    benchmark_id: Mapped[int] = mapped_column(
        ForeignKey("benchmarks.id"), primary_key=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    close: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)

    benchmark: Mapped["Benchmark"] = relationship(back_populates="prices")


class Deal(Base):
    __tablename__ = "deals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, default=func.now()
    )
    ticket: Mapped[int] = mapped_column(BigInteger)
    strategy_id: Mapped[str] = mapped_column(ForeignKey("strategies.id"))

    symbol: Mapped[str] = mapped_column(String)
    type: Mapped[DealType] = mapped_column(Enum(DealType))
    volume: Mapped[float] = mapped_column(Numeric(18, 8))
    price: Mapped[float] = mapped_column(Numeric(18, 8))
    profit: Mapped[float] = mapped_column(Numeric(18, 8))
    commission: Mapped[float] = mapped_column(Numeric(18, 8), default=0)
    swap: Mapped[float] = mapped_column(Numeric(18, 8), default=0)

    strategy: Mapped["Strategy"] = relationship(back_populates="deals")

    __table_args__ = (Index("ix_deals_strategy_timestamp", "strategy_id", "timestamp"),)


class DealIngestionKey(Base):
    __tablename__ = "deal_ingestion_keys"

    strategy_id: Mapped[str] = mapped_column(
        ForeignKey("strategies.id", ondelete="CASCADE"), primary_key=True
    )
    ticket: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    deal_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EquityCurve(Base):
    __tablename__ = "equity_curve"

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, default=func.now()
    )
    strategy_id: Mapped[str] = mapped_column(
        ForeignKey("strategies.id"), primary_key=True
    )

    balance: Mapped[float] = mapped_column(Numeric(18, 8))
    equity: Mapped[float] = mapped_column(Numeric(18, 8))

    strategy: Mapped["Strategy"] = relationship(back_populates="equity_curve")

    __table_args__ = (
        Index("ix_equity_strategy_timestamp", "strategy_id", "timestamp"),
    )


class StrategyRuntimeSnapshot(Base):
    __tablename__ = "strategy_runtime_snapshots"

    strategy_id: Mapped[str] = mapped_column(
        ForeignKey("strategies.id"), primary_key=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        server_default=func.now(),
        nullable=False,
    )
    open_profit: Mapped[float] = mapped_column(
        Numeric(18, 8), default=0.0, server_default=text("0")
    )
    open_trades_count: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    pending_orders_count: Mapped[int] = mapped_column(
        default=0, server_default=text("0")
    )

    strategy: Mapped["Strategy"] = relationship()


class Symbol(Base):
    __tablename__ = "symbols"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    market: Mapped[str | None] = mapped_column(
        String
    )  # Forex, Crypto, Futures, Indices, Stocks, Commodities
    lot: Mapped[float | None] = mapped_column(Numeric(18, 8))

    strategies: Mapped[list["Strategy"]] = relationship(
        foreign_keys=[Strategy.symbol_id],
        back_populates="symbol_record",
    )
    backtests: Mapped[list["Backtest"]] = relationship(
        foreign_keys="Backtest.symbol_id",
        back_populates="symbol_record",
    )


class IngestionError(Base):
    __tablename__ = "ingestion_errors"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    topic: Mapped[str | None] = mapped_column(String(32))
    raw_message: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(
        String(256), default="", server_default=text("''")
    )


class Backtest(Base):
    __tablename__ = "backtests"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    strategy_id: Mapped[str] = mapped_column(ForeignKey("strategies.id"))
    client_run_id: Mapped[int] = mapped_column(BigInteger)  # EA-generated run ID
    name: Mapped[str | None] = mapped_column(String)
    symbol: Mapped[str | None] = mapped_column(String)
    symbol_id: Mapped[int | None] = mapped_column(
        ForeignKey("symbols.id", ondelete="RESTRICT")
    )
    timeframe: Mapped[str | None] = mapped_column(String)
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    initial_balance: Mapped[float | None] = mapped_column(Numeric(18, 8))
    parameters: Mapped[dict | None] = mapped_column(JSONB)  # EA input parameters
    status: Mapped[str | None] = mapped_column(
        String, default="pending", server_default=text("'pending'")
    )  # pending|running|complete|failed
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    strategy: Mapped["Strategy"] = relationship(back_populates="backtests")
    symbol_record: Mapped["Symbol | None"] = relationship(
        foreign_keys=[symbol_id], back_populates="backtests"
    )
    deals: Mapped[list["BacktestDeal"]] = relationship(
        back_populates="backtest", cascade="all, delete-orphan"
    )
    equity: Mapped[list["BacktestEquity"]] = relationship(
        back_populates="backtest", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "strategy_id", "client_run_id", name="_backtest_strategy_run_uc"
        ),
        Index("ix_backtests_strategy_created_at", "strategy_id", "created_at"),
        Index("ix_backtests_symbol_id", "symbol_id"),
    )


class BacktestDeal(Base):
    __tablename__ = "backtest_deals"

    backtest_id: Mapped[int] = mapped_column(
        ForeignKey("backtests.id"), primary_key=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    ticket: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(String)
    type: Mapped[DealType] = mapped_column(Enum(DealType))
    volume: Mapped[float] = mapped_column(Numeric(18, 8))
    price: Mapped[float] = mapped_column(Numeric(18, 8))
    profit: Mapped[float] = mapped_column(Numeric(18, 8))
    commission: Mapped[float] = mapped_column(Numeric(18, 8), default=0)
    swap: Mapped[float] = mapped_column(Numeric(18, 8), default=0)

    backtest: Mapped["Backtest"] = relationship(back_populates="deals")


class BacktestEquity(Base):
    __tablename__ = "backtest_equity"

    backtest_id: Mapped[int] = mapped_column(
        ForeignKey("backtests.id"), primary_key=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    balance: Mapped[float] = mapped_column(Numeric(18, 8))
    equity: Mapped[float] = mapped_column(Numeric(18, 8))

    backtest: Mapped["Backtest"] = relationship(back_populates="equity")
