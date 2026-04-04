from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class AccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str | None = None
    broker: str | None = None
    account_type: str | None = None
    currency: str | None = None
    balance: float | None = 0.0
    free_margin: float | None = 0.0
    total_deposits: float | None = 0.0
    total_withdrawals: float | None = 0.0
    net_profit: float | None = None


class StrategyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str | None = None
    symbol: str | None = None
    timeframe: str | None = None
    operational_style: str | None = None
    trade_duration: str | None = None
    initial_balance: float | None = None
    base_currency: str | None = None
    description: str | None = None
    live: bool = False
    real_account: bool = False
    account_id: str | None = None
    account_name: str | None = None
    account_type: str | None = None
    net_profit: float | None = None
    backtest_net_profit: float | None = None
    trades_count: int | None = None
    max_drawdown: float | None = None  # 0-1 fraction
    last_seen_at: datetime | None = None
    last_trade_at: datetime | None = None
    zombie_alert: bool = False
    max_allowed_drawdown: float | None = None  # % limit, e.g. 20.0 = 20%


class DealResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    timestamp: datetime
    ticket: int
    strategy_id: str
    symbol: str | None = None
    type: str
    volume: float | None = None
    price: float | None = None
    profit: float | None = None
    commission: float | None = None
    swap: float | None = None

    @classmethod
    def from_orm_deal(cls, deal):
        return cls(
            timestamp=deal.timestamp,
            ticket=deal.ticket,
            strategy_id=deal.strategy_id,
            symbol=deal.symbol,
            type=deal.type.value if deal.type else "",
            volume=deal.volume,
            price=deal.price,
            profit=deal.profit,
            commission=deal.commission,
            swap=deal.swap,
        )


class EquityPointResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    timestamp: datetime
    strategy_id: str
    balance: float | None = None
    equity: float | None = None


class PortfolioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str | None = None
    initial_balance: float | None = None
    description: str | None = None
    live: bool = False
    real_account: bool = False
    strategy_ids: list[str] = []
    net_profit: float | None = None
    max_drawdown: float | None = None
    backtest_net_profit: float | None = None
    demo_net_profit: float | None = None
    real_net_profit: float | None = None

    @classmethod
    def from_orm_portfolio(cls, portfolio):
        return cls(
            id=portfolio.id,
            name=portfolio.name,
            initial_balance=portfolio.initial_balance,
            description=portfolio.description,
            live=portfolio.live,
            real_account=portfolio.real_account,
            strategy_ids=[s.id for s in portfolio.strategies],
        )


class SymbolResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    market: str | None = None
    lot: float | None = None
    strategies_count: int = 0


class BenchmarkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    source: str
    asset: str
    timeframe: str
    description: str | None = None
    is_default: bool = False
    enabled: bool = True
    last_synced_at: datetime | None = None
    last_error: str | None = None
    local_points: int = 0
    latest_price_timestamp: datetime | None = None


class BenchmarkRemoteDatabaseResponse(BaseModel):
    source: str
    asset: str
    timeframe: str
    status: str | None = None
    rows: int | None = None
    last_timestamp: str | None = None


class PaginatedDeals(BaseModel):
    items: list[DealResponse]
    total: int
    page: int
    page_size: int


class SummaryResponse(BaseModel):
    strategies_count: int
    portfolios_count: int
    accounts_count: int
    by_symbol: dict[str, int]
    by_style: dict[str, int]
    by_duration: dict[str, int]


class BacktestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    strategy_id: str
    client_run_id: int
    name: str | None = None
    symbol: str | None = None
    timeframe: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    initial_balance: float | None = None
    parameters: dict | None = None
    status: str | None = None
    created_at: datetime | None = None
    net_profit: float | None = None  # computed and injected in route


class BacktestDealResponse(BaseModel):
    backtest_id: int
    timestamp: datetime
    ticket: int
    symbol: str | None = None
    type: str
    volume: float | None = None
    price: float | None = None
    profit: float | None = None
    commission: float | None = None
    swap: float | None = None

    @classmethod
    def from_orm(cls, d):
        return cls(
            backtest_id=d.backtest_id,
            timestamp=d.timestamp,
            ticket=d.ticket,
            symbol=d.symbol,
            type=d.type.value if d.type else "",
            volume=d.volume,
            price=d.price,
            profit=d.profit,
            commission=d.commission,
            swap=d.swap,
        )


class BacktestEquityPointResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    backtest_id: int
    timestamp: datetime
    balance: float | None = None
    equity: float | None = None


class PaginatedBacktestDeals(BaseModel):
    items: list[BacktestDealResponse]
    total: int
    page: int
    page_size: int


# ── Request / write schemas ───────────────────────────────────────────────────


class AccountUpdate(BaseModel):
    name: str | None = None
    account_type: str | None = None
    currency: str | None = None


class StrategyUpdate(BaseModel):
    name: str | None = None
    symbol: str | None = None
    timeframe: str | None = None
    operational_style: str | None = None
    trade_duration: str | None = None
    initial_balance: float | None = None
    description: str | None = None
    live: bool | None = None
    real_account: bool | None = None
    max_allowed_drawdown: float | None = None


class PortfolioCreate(BaseModel):
    name: str
    description: str | None = None
    live: bool = False
    real_account: bool = False
    strategy_ids: list[str] = []
    initial_balance: float | None = None


class PortfolioUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    live: bool | None = None
    real_account: bool | None = None
    strategy_ids: list[str] | None = None
    initial_balance: float | None = None


class SymbolCreate(BaseModel):
    name: str
    market: str | None = None
    lot: float | None = None


class SymbolUpdate(BaseModel):
    name: str | None = None
    market: str | None = None
    lot: float | None = None


class BenchmarkCreate(BaseModel):
    name: str
    source: str
    asset: str
    timeframe: str = "D1"
    description: str | None = None
    enabled: bool = True
    is_default: bool = False


class BenchmarkUpdate(BaseModel):
    name: str | None = None
    source: str | None = None
    asset: str | None = None
    timeframe: str | None = None
    description: str | None = None
    enabled: bool | None = None
    is_default: bool | None = None


class TelegramSettings(BaseModel):
    bot_token: str | None = None
    chat_id: str | None = None
    notify_closed_trades: bool = False
    notify_system_errors: bool = False
    var_95_threshold: float | None = None
    default_initial_balance: float | None = None
    real_page_mode: Literal["real", "demo"] = "real"


class DataManagerSettings(BaseModel):
    url: str = "http://127.0.0.1:8686"
    api_key: str = ""
    timeout: float = 30.0
