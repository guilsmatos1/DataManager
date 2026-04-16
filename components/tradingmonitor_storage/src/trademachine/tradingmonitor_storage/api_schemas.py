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
    ret_dd: float | None = None
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
    metrics_error: str | None = None

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
    bot_token_configured: bool = False
    chat_id_configured: bool = False
    bot_token_masked: str | None = None
    chat_id_masked: str | None = None
    notify_closed_trades: bool = False
    notify_system_errors: bool = False
    var_95_threshold: float | None = None
    default_initial_balance: float | None = None
    real_page_mode: Literal["real", "demo"] = "real"


class DataManagerSettings(BaseModel):
    url: str = "http://127.0.0.1:8686"
    api_key: str = ""
    api_key_configured: bool = False
    timeout: float = 30.0


class BenchmarkSchedulerSettings(BaseModel):
    enabled: bool = False
    interval_hours: float = 24.0


# ── Typed response models for previously untyped endpoints ───────────────────


class MetricsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class DailyProfitRow(BaseModel):
    date: str
    net_profit: float
    trades_count: int | None = None


class EquityTimestampPoint(BaseModel):
    timestamp: str | None = None
    equity: float | None = None


class CorrelationInsights(BaseModel):
    avg_correlation: float | None = None
    most_positive: list = []
    most_negative: list = []


class CorrelationResponse(BaseModel):
    strategies: list[str] = []
    matrix: list[list[float | None]] = []
    data_points: int | None = None
    period: str | None = None
    date_range: list[str | None] = []
    insights: CorrelationInsights | None = None
    error: str | None = None


class DynamicCorrelationResponse(BaseModel):
    window_days: int | None = None
    strategies: list[str] = []
    matrix: list[list[float | None]] = []
    error: str | None = None


class ConcurrencyInsights(BaseModel):
    top_hour: list = []
    top_day: list = []
    top_week: list = []


class ConcurrencyResponse(BaseModel):
    strategies: list[str] = []
    same_hour: list[list[float]] = []
    same_day: list[list[float]] = []
    same_week: list[list[float]] = []
    insights: ConcurrencyInsights | None = None
    error: str | None = None


class ContributionsResponse(BaseModel):
    positive: dict[str, float] = {}
    negative: dict[str, float] = {}


class StrategyEquityBreakdown(BaseModel):
    name: str | None = None
    points: list[EquityTimestampPoint] = []


class EquityBreakdownResponse(BaseModel):
    total: list[EquityTimestampPoint] = []
    strategies: dict[str, StrategyEquityBreakdown] = {}


class AdvancedAnalysisBenchmark(BaseModel):
    model_config = ConfigDict(extra="allow")


class StrategyContribution(BaseModel):
    strategy_id: str
    name: str
    profit: float


class DailyPnlPoint(BaseModel):
    date: str
    net_profit: float


class TradeStatsByHour(BaseModel):
    hour: int
    count: int
    net_profit: float


class TradeStatsByDow(BaseModel):
    dow: int
    label: str
    count: int
    net_profit: float


class TradeStats(BaseModel):
    by_hour: list[TradeStatsByHour] = []
    by_dow: list[TradeStatsByDow] = []


class StrategyEquityCurve(BaseModel):
    strategy_id: str
    name: str
    points: list[EquityTimestampPoint] = []


class AdvancedAnalysisResponse(BaseModel):
    metrics: dict[str, object] = {}
    equity_curve: list[EquityTimestampPoint] = []
    comparison_curve: list = []
    benchmark: dict | None = None
    selected_strategies: list[str] = []
    history_type: str = ""
    strategy_contributions: list[StrategyContribution] = []
    daily_pnl: list[DailyPnlPoint] = []
    trade_stats: TradeStats = TradeStats()
    per_strategy_equity: list[StrategyEquityCurve] = []


class RealStrategyOverview(BaseModel):
    model_config = ConfigDict(extra="allow")


class RealOverviewTotals(BaseModel):
    net_profit: float = 0.0
    floating_pnl: float = 0.0
    day_pnl: float = 0.0
    open_trades_count: int | None = None
    pending_orders_count: int | None = None
    counts_available: bool = False


class RealOverviewResponse(BaseModel):
    mode: str
    strategies: list[dict] = []
    totals: RealOverviewTotals = RealOverviewTotals()


class RecentDeal(BaseModel):
    timestamp: str | None = None
    ticket: int
    strategy_id: str
    strategy_name: str | None = None
    symbol: str | None = None
    type: str
    profit: float = 0.0
    commission: float = 0.0
    swap: float = 0.0
    net_profit: float = 0.0


class FloatingPosition(BaseModel):
    strategy_id: str
    strategy_name: str | None = None
    balance: float
    equity: float
    floating_pnl: float


class FloatingPnlResponse(BaseModel):
    total_floating_pnl: float
    positions: list[FloatingPosition] = []


class HealthResponse(BaseModel):
    status: str
    db_ok: bool
    heartbeat: str | None = None
    heartbeat_age_seconds: float | None = None
    uptime_seconds: float | None = None


class IngestionClient(BaseModel):
    ip: str
    port: int


class IngestionStatusResponse(BaseModel):
    connected_clients: int = 0
    clients: list[IngestionClient] = []
    last_event_at: dict[str, str] = {}
    uptime_seconds: float = 0.0
    heartbeat: str | None = None


class IngestionErrorResponse(BaseModel):
    id: int
    timestamp: str | None = None
    topic: str | None = None
    error_message: str | None = None
    raw_message: str | None = None
