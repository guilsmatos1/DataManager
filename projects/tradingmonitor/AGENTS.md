# TradingMonitor Project Context

## Overview

TradingMonitor is the MT5 monitoring project in this workspace. It receives
real-time events from a MetaTrader 5 Expert Advisor over TCP/JSON, persists
them in TimescaleDB, and exposes operational workflows through a Typer CLI and
a FastAPI dashboard.

The main interface is a Typer CLI plus a web dashboard. The current feature set
includes live ingestion, strategy/account/portfolio management, metrics and
QuantStats reports, benchmark tracking, backtest storage, performance drift
checks, Telegram notifications, and DataManager integration.

This is a personal single-user project. Prefer simple local workflows over
multi-tenant, distributed, or enterprise-style designs.

## Main Commands

All commands are run from the workspace root.

```bash
# Install dependencies
uv sync --dev

# Start TimescaleDB
docker compose up -d

# Initialize schema and hypertables
uv run trading-monitor setup-db

# Start only the TCP ingestion server
uv run trading-monitor start-ingestion

# Start the dashboard with ingestion enabled by default
uv run trading-monitor start-dashboard

# Check ingestion heartbeat
uv run trading-monitor status

# Register entities
uv run trading-monitor register-account <login> --name "Name" --broker "Broker" --currency USD
uv run trading-monitor register-strategy <magic_number> --name "Name" --symbol EURUSD --timeframe M15
uv run trading-monitor create-portfolio --name "Portfolio1" --balance 100000
uv run trading-monitor add-to-portfolio <portfolio_id> <strategy_id>

# Reports
uv run trading-monitor report <strategy_id>
uv run trading-monitor portfolio-report <portfolio_id>
uv run trading-monitor send-report --strategy-id <strategy_id>

# Tests
uv run pytest components/tradingmonitor_storage/test components/tradingmonitor_ingestion/test components/tradingmonitor_analytics/test bases/trading_monitor_cli/test bases/trading_monitor_dashboard/test

# Lint and format after Python changes
uv run ruff check --fix . && uv run ruff format .
```

## Architecture

TradingMonitor follows the Polylith layout used across the monorepo.

- `components/tradingmonitor_storage` contains configuration, persistence, ORM
  models, repository logic, and API-facing schemas.
- `components/tradingmonitor_ingestion` contains the TCP ingestion runtime,
  payload validation, heartbeat, and dead-letter flow.
- `components/tradingmonitor_analytics` contains metrics, QuantStats reports,
  benchmark sync, and drift analysis.
- `bases/trading_monitor_cli` contains the CLI command wiring.
- `bases/trading_monitor_dashboard` contains the FastAPI dashboard, HTML pages,
  API routes, and websocket bridge.
- `projects/tradingmonitor/mt5/MetricsPublisher.mq5` is the MT5 EA used to send
  telemetry into the ingestion server.

### Important Modules

- `bases/trading_monitor_cli/src/trademachine/trading_monitor_cli/main.py`
  defines CLI commands for setup, ingestion, entity registration, reports, and
  dashboard startup.
- `bases/trading_monitor_dashboard/src/trademachine/trading_monitor_dashboard/app.py`
  creates the FastAPI application and optionally boots ingestion in the same
  process.
- `bases/trading_monitor_dashboard/src/trademachine/trading_monitor_dashboard/routes.py`
  contains dashboard and API routes for accounts, strategies, portfolios,
  backtests, settings, ingestion, and benchmarks.
- `components/tradingmonitor_ingestion/src/trademachine/tradingmonitor_ingestion/ingestion/tcp_server.py`
  handles TCP ingestion, heartbeat, dead-letter flow, and event dispatch.
- `components/tradingmonitor_ingestion/src/trademachine/tradingmonitor_ingestion/ingestion/schemas.py`
  validates incoming MT5 payloads.
- `components/tradingmonitor_storage/src/trademachine/tradingmonitor_storage/db/models.py`
  defines ORM models for accounts, strategies, deals, equity, portfolios,
  backtests, symbols, benchmarks, and related entities.
- `components/tradingmonitor_storage/src/trademachine/tradingmonitor_storage/db/repository.py`
  contains the repository layer used by CLI and dashboard flows.
- `components/tradingmonitor_analytics/src/trademachine/tradingmonitor_analytics/metrics/`
  contains metric calculation and QuantStats report generation logic.
- `components/tradingmonitor_analytics/src/trademachine/tradingmonitor_analytics/analysis/`
  contains higher-level analysis such as benchmarks and drift detection.

## Core Workflows

### Loading and Cache

TradingMonitor does not use a portfolio cache like PortfolioMaster. Its
operational equivalent is the ingestion runtime state plus durable persistence
in TimescaleDB.

`start_ingestion()` and `start_dashboard()` start the TCP server, validate MT5
payloads, persist them to the database, and keep operational state through:

- TimescaleDB tables and hypertables for long-lived history;
- `HEARTBEAT_FILE` for daemon health checks;
- `DEAD_LETTER_FILE` for invalid ingestion payloads;
- in-memory caches in the TCP server for known strategies, accounts, symbols,
  active backtests, and recent event metadata.

### Optimization

TradingMonitor does not perform combinatorial optimization. Its closest
calculation workflow is metrics and report generation over live strategies,
portfolios, and backtests.

Important characteristics:

- repository-backed retrieval of deals and equity curves;
- vectorized metrics calculation through pandas and QuantStats;
- individual strategy reports;
- aggregate portfolio reports;
- HTML QuantStats export through `generate_qs_report()`;
- support for both CLI reporting and dashboard-driven visualization.

### Pairing

TradingMonitor does not implement drawdown pairing. Its closest orchestration
workflow is portfolio composition and comparative analysis.

Relevant capabilities include:

- registering strategies and linking them to accounts;
- creating portfolios and attaching strategies to them;
- computing aggregate metrics for strategy groups;
- comparing portfolio performance against synced benchmarks from DataManager;
- exposing portfolio state to both CLI and dashboard/API consumers.

### Adherence

TradingMonitor does not compare SQX and MT5 reports. Its equivalent
adherence-style workflow is drift detection and live-vs-reference monitoring.

This workflow:

- stores backtest runs and backtest-derived datasets;
- compares live behavior with expected historical behavior;
- evaluates drift thresholds such as win-rate drop, profit-factor drop, and
  drawdown expansion;
- can trigger notifications when drift alerts are enabled;
- complements benchmark syncing for external reference comparison.

## Outputs

TradingMonitor can generate:

- TimescaleDB-backed history for deals, equity, runtimes, backtests, and
  benchmarks;
- CLI summaries for status, entity listings, and performance reports;
- HTML QuantStats reports for strategies and portfolios;
- dashboard pages, API responses, and websocket events for live monitoring;
- JSONL dead-letter output for invalid ingestion payloads.

When the dashboard is running, the project exposes both rendered HTML views and
API endpoints instead of relying only on terminal output.

## Configuration

Configuration is defined in
`components/tradingmonitor_storage/src/trademachine/tradingmonitor_storage/config.py` through
`Settings`.

Priority order:

1. environment variables / `.env`
2. code defaults for optional fields

Required fields such as `DATABASE_URL` and `API_KEY` must be supplied through
the environment.

Common fields:

- `DATABASE_URL`, `API_KEY`
- `SERVER_HOST`, `SERVER_PORT`
- `DASHBOARD_HOST`, `DASHBOARD_PORT`
- `HEARTBEAT_FILE`, `DEAD_LETTER_FILE`
- `DATAMANAGER_URL`, `DATAMANAGER_API_KEY`, `DATAMANAGER_TIMEOUT`
- `ENABLE_NOTIFICATIONS`, `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`
- `ENABLE_DRIFT_ALERTS`, `DRIFT_*`
- `MARGIN_THRESHOLD_PCT`, `VAR_95_THRESHOLD`

## Development Rules

- Keep reusable domain logic in `components/`; keep CLI and HTTP concerns in
  `bases/`.
- Do not import from bases into components.
- Use the `trademachine` namespace for internal imports.
- Treat MT5 magic number as the strategy identifier and MT5 login as the
  account identifier.
- Prefer the split component APIs that already exist today
  (`tradingmonitor_storage`, `tradingmonitor_ingestion`,
  `tradingmonitor_analytics`) instead of reintroducing a synthetic monolithic
  `tradingmonitor` package path in new code or docs.
- Be careful with ingestion, persistence, and route logic that directly affects
  operator workflows; this project is optimized for a single-user local setup.

## Testing Focus

When changing TradingMonitor, add tests near the affected area under
`components/tradingmonitor_storage/test/`,
`components/tradingmonitor_ingestion/test/`,
`components/tradingmonitor_analytics/test/`,
`bases/trading_monitor_cli/test/`, or
`bases/trading_monitor_dashboard/test/`. Prioritize coverage for CLI
validation, ingestion parsing, repository behavior, metrics and report
calculations, dashboard routes, drift logic, benchmark syncing, and
integrations with DataManager or Telegram.

## Additional Operational Notes

### What The Project Does

- receives trade deals, account updates, equity events, and runtime snapshots
  from an MT5 Expert Advisor over TCP;
- stores those events in TimescaleDB for durable monitoring history;
- exposes a FastAPI dashboard for real-time visualization;
- provides CLI flows for operational setup, entity registration, and reporting;
- supports benchmark syncing and comparison against market data from
  DataManager;
- tracks live strategy runtime state, including open-profit and open/pending
  order counts;
- integrates Telegram notifications for selected operational alerts.

### Installation Notes

TradingMonitor requires Python 3.12+, `uv`, Docker/Docker Compose for the local
database, and a MetaTrader 5 terminal as the event source.

Typical local setup:

```bash
uv sync --dev
docker compose up -d
uv run trading-monitor setup-db
uv run trading-monitor start-dashboard
```

This project assumes a local operator workflow where the MT5 Expert Advisor is
compiled from `projects/tradingmonitor/mt5/MetricsPublisher.mq5`, attached to a
chart inside MT5, and then begins pushing telemetry into the TCP server.

### Typical Workflow

The current operator docs use this common operator flow:

```bash
uv sync --dev
docker compose up -d
uv run trading-monitor setup-db
uv run trading-monitor start-dashboard
```

At runtime, the expected sequence is:

1. start TimescaleDB locally;
2. initialize the schema and hypertables;
3. start the dashboard, which also starts ingestion unless disabled;
4. compile and attach `MetricsPublisher.mq5` inside MT5;
5. observe deals, equity, and runtime data arriving in the dashboard.

### Additional Command Reference

#### `load <dir>`

TradingMonitor has no `load <dir>` command. The operational equivalent is
starting ingestion and receiving MT5 data in real time through:

- `uv run trading-monitor start-ingestion`
- `uv run trading-monitor start-dashboard`
- `uv run trading-monitor status`

#### `optimize`

TradingMonitor has no `optimize` command. The closest operational commands are:

- `report <strategy_id>` for per-strategy metrics;
- `portfolio-report <portfolio_id>` for aggregate metrics;
- `send-report --strategy-id ...` or `--portfolio-id ...` for QuantStats HTML
  generation and Telegram delivery.

#### `benchmark`

TradingMonitor has no throughput benchmark command in the PortfolioMaster
meaning. Instead, it has a benchmark domain for market-comparison assets that
are created, listed, synced, and compared through dashboard/API flows backed by
`analysis/benchmarks.py`.

#### Shell And CLI Subcommands

The CLI currently exposes these operator-facing commands:

```bash
uv run trading-monitor status
uv run trading-monitor setup-db
uv run trading-monitor start-ingestion
uv run trading-monitor register-account <login> --name "Name" --broker "Broker" --currency USD
uv run trading-monitor list-accounts
uv run trading-monitor register-strategy <strategy_id> --name "Name" --symbol EURUSD --timeframe M15
uv run trading-monitor create-portfolio --name "Portfolio1" --balance 100000
uv run trading-monitor add-to-portfolio <portfolio_id> <strategy_id>
uv run trading-monitor list-portfolios
uv run trading-monitor report <strategy_id>
uv run trading-monitor portfolio-report <portfolio_id>
uv run trading-monitor send-report --strategy-id <strategy_id>
uv run trading-monitor start-dashboard
uv run trading-monitor test-telegram
```

Behavior notes:

- `status` reads the heartbeat file and reports daemon health;
- `setup-db` initializes schema and hypertables;
- `start-ingestion` runs only the TCP ingestion server;
- `start-dashboard` runs the web app and enables ingestion by default;
- `register-account` and `register-strategy` create or update entity metadata;
- `create-portfolio` and `add-to-portfolio` manage strategy grouping;
- `report` and `portfolio-report` print calculated metrics to the terminal;
- `send-report` writes an HTML report and optionally sends it to Telegram;
- `test-telegram` validates Telegram integration using current settings.

#### `adherence`

TradingMonitor has no `adherence` command. The closest documented equivalent is
performance drift monitoring.

Operationally, drift monitoring:

- compares live results against stored backtest expectations;
- applies configured thresholds for deteriorating behavior;
- can notify through Telegram when alerts are enabled.

The runtime snapshot payload used to populate the
`/real` dashboard with open trade and pending-order counts:

```text
STRATEGY_RUNTIME {"time":1711737600,"magic":123456,"open_profit":48.35,"open_trades_count":2,"pending_orders_count":1}
```

#### `pairing`

TradingMonitor has no `pairing` command. The closest portfolio-level operation
is adding strategies into a portfolio and then inspecting combined performance
through CLI or dashboard reporting.

### Artifact Layout

The operational artifact layout is:

- TimescaleDB stores deals, equity, runtime snapshots, accounts, strategies,
  portfolios, backtests, and benchmarks;
- `/tmp/trademachine.tradingmonitor_heartbeat` is the default daemon heartbeat
  file;
- `/tmp/trademachine.tradingmonitor_dead_letters.jsonl` is the default sink for
  invalid payloads;
- generated HTML reports are written to the output path provided to
  `send-report`;
- the dashboard serves HTML templates and static assets directly from the base
  package.

### Example Config

The closest equivalent to a PortfolioMaster-style example config is the set of
environment variables consumed by `Settings`:

```bash
DATABASE_URL=postgresql://postgres:password@localhost:5432/tradingmonitor
API_KEY=change-me
SERVER_HOST=127.0.0.1
SERVER_PORT=5555
DASHBOARD_HOST=127.0.0.1
DASHBOARD_PORT=8000
HEARTBEAT_FILE=/tmp/trademachine.tradingmonitor_heartbeat
DEAD_LETTER_FILE=/tmp/trademachine.tradingmonitor_dead_letters.jsonl
DATAMANAGER_URL=http://127.0.0.1:8686
DATAMANAGER_API_KEY=YOUR_API_KEY_HERE
DATAMANAGER_TIMEOUT=30
ENABLE_NOTIFICATIONS=false
TELEGRAM_TOKEN=
TELEGRAM_CHAT_ID=
ENABLE_DRIFT_ALERTS=true
DRIFT_WIN_RATE_THRESHOLD=15
DRIFT_PF_THRESHOLD=20
DRIFT_DD_MULTIPLIER=1.2
DRIFT_MIN_TRADES=20
```

### Additional Structure And Development Notes

The current codebase structure implies this layout:

```text
components/tradingmonitor_storage/src/trademachine/tradingmonitor_storage/
  db/
    database.py
    models.py
    repository.py
  utils/
    notifications.py
  api_schemas.py
  config.py
  constants.py
  facade.py

components/tradingmonitor_ingestion/src/trademachine/tradingmonitor_ingestion/
  ingestion/
    cache.py
    schemas.py
    tcp_server.py

components/tradingmonitor_analytics/src/trademachine/tradingmonitor_analytics/
  analysis/
    benchmarks.py
    drift.py
  metrics/
    calculator.py
    repository.py
    plugins/

bases/trading_monitor_cli/src/trademachine/trading_monitor_cli/
  main.py

bases/trading_monitor_dashboard/src/trademachine/trading_monitor_dashboard/
  app.py
  routes.py
  websocket.py
  bridge.py

projects/tradingmonitor/mt5/
  MetricsPublisher.mq5
```

Additional development commands that fit the current project setup:

```bash
cd projects/tradingmonitor
uv run alembic upgrade head
cd ../..
uv run pytest components/tradingmonitor_storage/test components/tradingmonitor_ingestion/test components/tradingmonitor_analytics/test bases/trading_monitor_cli/test bases/trading_monitor_dashboard/test
```

## Additional Codebase Notes

This section mirrors the PortfolioMaster structure and consolidates equivalent
codebase-level notes from the repository itself.

### Main Technologies

- Python 3.12+
- `sqlalchemy`, `alembic`, `psycopg2-binary`
- `fastapi`, `uvicorn`, `jinja2`
- `pandas`, `numpy`, `quantstats`
- `pydantic`, `pydantic-settings`
- `typer`
- TimescaleDB / PostgreSQL
- TCP/JSON ingestion from MT5

The current codebase is centered on a local operator workflow that combines a
CLI, a dashboard, and a TCP ingestion daemon around a single local database.

### Expanded Module Notes

The repository adds these module-level responsibilities:

- `tradingmonitor_storage/config.py`: centralized settings for DB, dashboard, ingestion, DataManager,
  Telegram, and drift checks;
- `tradingmonitor_storage/db/database.py`: engine, session factory, and schema initialization;
- `tradingmonitor_storage/db/models.py`: ORM definitions for live and backtest data;
- `tradingmonitor_storage/db/repository.py`: repository helpers for CRUD and query aggregation;
- `tradingmonitor_analytics/metrics/calculator.py`: metric calculation plus QuantStats HTML export;
- `tradingmonitor_analytics/metrics/repository.py`: DataFrame-oriented access to strategy and portfolio
  history;
- `tradingmonitor_analytics/analysis/benchmarks.py`: benchmark definition, DataManager sync, and local
  benchmark statistics;
- `tradingmonitor_analytics/analysis/drift.py`: live-vs-backtest drift detection and notification flow;
- `tradingmonitor_storage/utils/notifications.py`: Telegram delivery helpers;
- `tradingmonitor_ingestion/ingestion/tcp_server.py`: message routing, persistence, heartbeat, and
  connection management;
- `tradingmonitor_ingestion/ingestion/schemas.py`: payload validation for TCP messages.

CLI-specific notes:

- `main.py` is the only CLI entry file and exposes setup, ingestion,
  registration, report, dashboard, and Telegram test commands;
- `start-dashboard` can run ingestion inside the same process;
- dashboard routes are concentrated in `bases/trading_monitor_dashboard/routes.py`;
- benchmark synchronization depends on the DataManager API being reachable.

### Building And Running Notes

Operational patterns consolidated from the current repository:

- `uv run trading-monitor status` is the first health check for ingestion;
- `uv run trading-monitor setup-db` must run before first use on a fresh DB;
- `uv run trading-monitor start-ingestion` runs the TCP daemon only;
- `uv run trading-monitor start-dashboard` is the all-in-one operator mode;
- `uv run trading-monitor send-report --strategy-id ...` and
  `--portfolio-id ...` are the documented HTML-report flows;
- `uv run trading-monitor test-telegram` is the documented notification check;
- `cd projects/tradingmonitor && uv run alembic upgrade head` is the migration
  workflow.

### Development Conventions

#### Performance Standards

- prefer repository and vectorized DataFrame flows over ad hoc Python loops when
  calculating metrics or combining equity series;
- keep ingestion logic resilient and lightweight because it processes live TCP
  traffic continuously;
- preserve TimescaleDB-first persistence for time-series-heavy tables.

#### Data-Handling Rules

- time-series persistence is centered on TimescaleDB hypertables;
- ingestion health is exposed through a heartbeat file;
- malformed payloads are preserved in the dead-letter JSONL sink instead of
  being silently discarded;
- runtime snapshots are used to populate real-account operational views;
- benchmarks are synced from DataManager and stored locally for comparison;
- backtest entities and live entities share the same monitoring environment but
  must remain distinguishable in the data model;
- `TradingMonitorFacade` should remain the preferred high-level access layer for
  base consumers.

#### Validation Rules

- `send-report` requires either `--strategy-id` or `--portfolio-id`;
- `test-telegram` requires notifications enabled plus both Telegram credentials;
- protected dashboard/API routes require a valid `API_KEY`.

### Testing And Validation Contracts

- tests should be run from the repository root;
- coverage exists for ingestion, metrics, drift, notifications, routes,
  benchmarks, migrations, and dashboard behavior;
- `test_live_backend.py` protects dashboard route and live backend behavior;
- `test_ingestion.py` and `test_schemas.py` protect ingestion behavior;
- `test_benchmarks.py` protects benchmark syncing and local benchmark curves;
- `test_qs_report.py` protects QuantStats HTML generation;
- `test_drift.py` protects drift-report structure and threshold behavior.

### Configuration And Precedence Notes

The effective precedence rules in TradingMonitor are:

- environment variables and `.env` configure the application;
- explicit CLI options override defaults supplied by `Settings`;
- required secrets and connection strings must be present before runtime.

### Technical Debt And Caveats

- MT5 integration depends on the EA message format remaining stable;
- long-running ingestion behavior depends on socket reliability and host
  platform behavior;
- benchmark synchronization depends on the availability and correctness of
  DataManager responses;
- Telegram delivery is optional and should not block core monitoring flows;
- dashboard, ingestion, and CLI share the same domain layer, so route or schema
  changes can affect operator workflows quickly.
