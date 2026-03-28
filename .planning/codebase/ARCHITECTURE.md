# Architecture

**Analysis Date:** 2026-03-28

## Pattern Overview

**Overall:** Polylith monorepo — a component-based architecture where reusable business logic lives in `components/` and entry points live in `bases/`. Projects in `projects/` are build configurations that assemble components + bases into deployable units.

**Key Characteristics:**
- Strict layer isolation enforced by `import-linter` and pre-commit hooks: components cannot import from bases
- Single shared Python namespace `trademachine.*` across all packages
- Four independent domain subsystems (DataManager, TradingMonitor, PortfolioMaster, BacktestEngine) sharing a common `core` component
- Personal/single-user project — simplicity over enterprise patterns; no distributed caching, no multi-tenant concerns

## Layers

**Components (Business Logic):**
- Purpose: Reusable domain logic, persistence, data processing — all framework-agnostic
- Location: `components/<name>/src/trademachine/<name>/`
- Contains: Services, models, repositories, fetchers, calculators, config
- Depends on: Other components (allowed), external libraries
- Used by: Bases (entry points)

**Bases (Entry Points):**
- Purpose: Interface adapters — translate user interactions (HTTP, CLI, TCP) into component calls
- Location: `bases/<name>/src/trademachine/<name>/`
- Contains: FastAPI routers, Typer CLI commands, TCP server wrappers, Jinja2 dashboard
- Depends on: Components only (never other bases)
- Used by: End users / deployment

**Projects (Build Configurations):**
- Purpose: Declare which bases + components to bundle for a deployable artifact; hold migrations and Docker config
- Location: `projects/<name>/`
- Contains: `pyproject.toml` (dependency declaration), Alembic migrations, `docker-compose.yml`, scripts
- No Python source code of their own

## Data Flow

**DataManager — OHLCV Fetch/Store:**
1. User invokes CLI (`datamanager_cli`) or REST API (`datamanager_api`, port 8686)
2. Base delegates to `DataManager` orchestrator at `components/datamanager/src/trademachine/datamanager/services/manager.py`
3. `DataManager` selects a `BaseFetcher` subclass (auto-discovered via `pkgutil`) and calls `fetch_data()` → M1 DataFrame
4. `StorageManager` writes M1 rows to TimescaleDB hypertable `ohlcv_m1`; higher timeframes served via Continuous Aggregates
5. Metadata catalog (`sources`, `assets` tables in TimescaleDB) tracks what is stored

**TradingMonitor — Real-Time Ingestion:**
1. MT5 EA publishes `"{TOPIC} {JSON}"` messages (DEAL, EQUITY, ACCOUNT, BACKTEST_*) over TCP to port 5555
2. `trading_monitor_cli` base starts the TCP daemon; `trading_monitor_dashboard` base can optionally embed it in-process
3. `tcp_server.py` in `components/tradingmonitor/src/trademachine/tradingmonitor/ingestion/` receives and routes messages
4. Pydantic schemas (`ingestion/schemas.py`) validate payloads; SQLAlchemy ORM commits to TimescaleDB hypertables (`deals`, `equity_curve`)
5. Dashboard base receives live events via an internal bridge (`bridge.py`) and pushes to connected browsers over WebSocket

**TradingMonitor — Analytics Path:**
1. `TradingMonitorFacade` (`components/tradingmonitor/src/trademachine/tradingmonitor/facade.py`) aggregates all repositories
2. `metrics/calculator.py` fetches deals + equity curve DataFrames and dispatches to `BaseMetric` plugin instances
3. Results returned as plain dicts to the base layer (dashboard routes or CLI)

**PortfolioMaster — Optimization:**
1. User loads MT5 HTML backtest reports via CLI (`portifolio_master_cli`)
2. `mt5` component parser (`components/mt5/src/trademachine/mt5/parser.py`) extracts deals DataFrames
3. `PortfolioManager` stores strategies; `BruteForceEngine` generates combinations, filters by correlation, ranks by RetDD
4. Results exported as CSV, JSON, Parquet, or HTML via `visualizer.py`

**State Management:**
- No application-level in-memory state management; all persistent state is in the database
- `DataManager` instance is module-level singleton in the API base (`router.py`)
- TradingMonitor uses in-memory caches (per-strategy and per-account) in `ingestion/cache.py` for hot-path deduplication only
- Settings are loaded once via `pydantic-settings` with `@lru_cache` and read from `.env` files

## Key Abstractions

**BaseFetcher (DataManager):**
- Purpose: Abstract interface for all OHLCV data sources
- Location: `components/datamanager/src/trademachine/datamanager/fetchers/base.py`
- Pattern: ABC with `source_name` property + `fetch_data()` method; concrete classes in `fetchers/openbb.py`, `fetchers/dukascopy.py`, `fetchers/ccxt.py`; auto-discovered via `pkgutil` — no registration required

**BaseMetric (TradingMonitor):**
- Purpose: Plugin interface for all performance metrics calculations
- Location: `components/tradingmonitor/src/trademachine/tradingmonitor/metrics/plugins/base.py`
- Pattern: ABC with `name` property + `calculate(deals_df, daily_returns, **kwargs)` method; plugins in `metrics/plugins/` (sharpe, sortino, calmar, var95, cvar95, max_drawdown, recovery, risk_reward)

**TradingMonitorFacade:**
- Purpose: Single entry point for all TradingMonitor functionality consumed by bases; reduces coupling between bases and internal implementation
- Location: `components/tradingmonitor/src/trademachine/tradingmonitor/facade.py`
- Pattern: Facade aggregating all repositories; lazy imports inside methods to avoid circular dependencies

**DataManager Orchestrator:**
- Purpose: Central controller coordinating fetchers, storage, and processing
- Location: `components/datamanager/src/trademachine/datamanager/services/manager.py`
- Pattern: Service class with injected `StorageManager` and `DataProcessor`; bases instantiate it as a singleton

## Entry Points

**DataManager API:**
- Location: `bases/datamanager_api/src/trademachine/datamanager_api/router.py`
- Triggers: `uvicorn` on port 8686
- Responsibilities: FastAPI REST API with API-key auth (`X-API-Key` header), in-memory rate limiting (60 req/min via `slowapi`), APScheduler background jobs for scheduled updates

**DataManager CLI:**
- Location: `bases/datamanager_cli/src/trademachine/datamanager_cli/cli.py`
- Triggers: `uv run datamanager [-i]`
- Responsibilities: `cmd.Cmd` interactive shell; also accepts single commands non-interactively

**TradingMonitor CLI:**
- Location: `bases/trading_monitor_cli/src/trademachine/trading_monitor_cli/main.py`
- Triggers: `uv run trading-monitor <command>`
- Responsibilities: Typer CLI wiring setup-db, start-ingestion, register-account, register-strategy, report commands

**TradingMonitor Dashboard:**
- Location: `bases/trading_monitor_dashboard/src/trademachine/trading_monitor_dashboard/app.py`
- Triggers: `uvicorn` on port 8000 (configurable)
- Responsibilities: FastAPI + Jinja2 SPA-style dashboard; optionally embeds TCP ingestion as a background thread; WebSocket push to browsers via `bridge.py`

**PortfolioMaster CLI:**
- Location: `bases/portifolio_master_cli/src/trademachine/portifolio_master_cli/cli.py`
- Triggers: `uv run portifoliomaster [-i]`
- Responsibilities: Typer-based CLI for loading reports, running brute-force optimization, exporting results

**BacktestEngine CLI:**
- Location: `bases/backtest_engine_cli/src/trademachine/backtest_engine_cli/main.py`
- Triggers: `uv run backtest-engine`
- Responsibilities: NautilusTrader backtesting orchestration

## Error Handling

**Strategy:** Exceptions propagate naturally; each base layer catches and logs. Components raise domain exceptions or standard Python exceptions — no framework-specific error types except `portifoliomaster/core/exceptions.py`.

**Patterns:**
- DataManager fetchers log `logger.error()` per-chunk on failure, continue with remaining chunks, and raise `RuntimeError` only if all chunks fail
- TradingMonitor TCP server catches per-message exceptions, records them to `ingestion_errors` table (dead-letter pattern), and continues
- Pydantic validation errors are raised at schema boundaries (ingestion schemas, API request models)
- SQLAlchemy `IntegrityError` is caught in ingestion for idempotent upserts (deal deduplication via `UniqueConstraint`)

## Cross-Cutting Concerns

**Logging:**
- Shared logger name `TradeMachine` via `components/core/src/trademachine/core/logger.py`
- `setup_logger()` configures: console handler (human-readable `HH:MM:SS [LEVEL] msg`) + file handler (`log.log`, JSON structured one-per-line)
- All components import `LOGGER_NAME` and call `logging.getLogger(LOGGER_NAME)`

**Configuration:**
- Each component has its own `core/config.py` using `pydantic-settings` (`BaseSettings`) reading from `.env`
- Settings loaded once at import time via module-level `settings = Settings()` or `@lru_cache` getter
- No shared config object across domains — each domain manages its own env vars

**Validation:**
- API boundaries use Pydantic v2 models (request/response schemas in `schemas/__init__.py`)
- TCP ingestion uses Pydantic schemas (`ingestion/schemas.py`) for message validation
- Layer isolation validated at commit time by `import-linter` contracts defined in `.importlinter`

**Database Migrations:**
- DataManager: Alembic migrations in `projects/datamanager/alembic/versions/`; TimescaleDB Continuous Aggregates created in migration `8f52d9a582ce`
- TradingMonitor: Alembic migrations in `projects/tradingmonitor/alembic/versions/`; hypertables for `deals` and `equity_curve` created imperatively in `init_db()` (not via Alembic)

---

*Architecture analysis: 2026-03-28*
