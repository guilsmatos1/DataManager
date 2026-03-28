# Technology Stack

**Analysis Date:** 2026-03-28

## Languages

**Primary:**
- Python 3.12+ — entire codebase; enforced via `requires-python = ">=3.12"` in `pyproject.toml`

**Secondary:**
- MQL5 — MetaTrader 5 Expert Advisor (`src/mql5/MetricsPublisher.mq5`) that publishes trade data to TCP; not part of the Python build

## Runtime

**Environment:**
- CPython 3.12 (slim Docker image: `python:3.12-slim` in `projects/datamanager/Dockerfile`)

**Package Manager:**
- `uv` — manages the entire workspace; replaces pip/venv
- Lockfile: `uv.lock` (present, committed)
- Workspace mode: `[tool.uv.workspace]` with 16 member packages defined in root `pyproject.toml`

## Frameworks

**Web API:**
- FastAPI `>=0.128.8` — DataManager REST API (`bases/datamanager_api/src/trademachine/datamanager_api/router.py`, port 8686) and TradingMonitor dashboard (`bases/trading_monitor_dashboard/`)
- Uvicorn `>=0.40.0` — ASGI server for FastAPI

**CLI:**
- Typer `>=0.24.1` — TradingMonitor and PortfolioMaster CLIs
- Python `cmd.Cmd` (stdlib) — DataManager interactive shell

**Data Validation:**
- Pydantic `>=2.12.5` — all request/response schemas and settings
- pydantic-settings `>=2.13.1` — `BaseSettings` for environment-based config in all components

**Database ORM / Migrations:**
- SQLAlchemy `>=2.0.48` — ORM for both DataManager and TradingMonitor
- Alembic `>=1.18.4` — schema migrations; migrations in `projects/datamanager/alembic/versions/`

**Scheduling:**
- APScheduler `>=3.11.2` — job scheduling in DataManager API (`services/scheduler.py`)

**Backtesting:**
- NautilusTrader `>=1.224.0` — institutional-grade backtesting framework used by BacktestEngine component (`components/backtestengine/`)

**Rate Limiting:**
- slowapi `>=0.1.9` — in-memory rate limiting on DataManager API (60 req/min per IP)

**Templates:**
- Jinja2 `>=3.1.6` — HTML templates for TradingMonitor dashboard

## Data & Analytics Libraries

**DataFrames:**
- pandas `>=2.2.3,<3.0.0` — primary DataFrame library across all components
- Polars `>=1.39.3` — used in PortfolioMaster for high-performance portfolio optimization
- NumPy `>=2.4.3` — vectorized metric calculations

**Storage Formats:**
- PyArrow `>=23.0.1` — Parquet I/O (PortfolioMaster cache: `cache.parquet`)
- fastparquet `>=2025.12.0` — Parquet I/O alternative used in DataManager project

**Financial Analytics:**
- QuantStats `>=0.0.81` — portfolio analytics and HTML report generation (TradingMonitor metrics)
- Plotly `>=6.6.0` — interactive charts in PortfolioMaster reports

**HTML Parsing:**
- BeautifulSoup4 `>=4.14.3` — MT5 HTML report parsing in PortfolioMaster
- lxml `>=6.0.2` — HTML/XML parser backend for BeautifulSoup4

**HTTP:**
- httpx `>=0.28.1` — async HTTP client for Telegram notification API
- requests `>=2.32.5` — sync HTTP client

**Retry / Resilience:**
- tenacity `>=9.0.0` — retry logic with exponential jitter on CCXT and OpenBB fetchers

**Progress:**
- tqdm `>=4.67.3` — progress bars in PortfolioMaster brute-force optimization

**Logging:**
- python-json-logger `>=2.0.7` — structured JSON logging (`pythonjsonlogger.json.JsonFormatter`)
- colorama `>=0.4.6` — colored terminal output in CLIs

**Date utilities:**
- python-dateutil `>=2.9.0.post0` — date parsing in fetchers and CLI

## Database / Storage Technologies

**Primary Database (TradingMonitor + DataManager):**
- TimescaleDB `latest-pg15` (Docker: `timescale/timescaledb:latest-pg15`) — PostgreSQL with time-series hypertables
  - `ohlcv_m1` hypertable partitioned by timestamp (DataManager)
  - `deals` and `equity_curve` hypertables (TradingMonitor)
  - Continuous Aggregates for M5, M15, H1, H4, D1 timeframes (DataManager)
- psycopg2-binary `>=2.9.11` — PostgreSQL adapter

**File Storage (PortfolioMaster):**
- Parquet files — `cache.parquet` for parsed MT5 HTML report data

**Legacy / Partial (DataManager historical):**
- SQLite — previously used as catalog (`metadata/catalog.db`), being replaced by TimescaleDB

## Architecture Pattern

**Polylith Monorepo:**
- `bases/` — entry points (API, CLI, TCP daemon, dashboard) — 7 bases
- `components/` — reusable business logic — 6 components (`datamanager`, `tradingmonitor`, `portifoliomaster`, `backtestengine`, `mt5`, `core`)
- `projects/` — build configurations per deployable unit — 4 projects
- Namespace: `trademachine` — all imports follow `from trademachine.<component> import ...`
- Layer isolation enforced via import-linter: components cannot import from bases

## Build / Dev Toolchain

**Linting & Formatting:**
- Ruff `v0.9.9` (pre-commit), target Python 3.12, line-length 88
  - Rules: `E, F, I, W, B, UP, S`

**Type Checking:**
- mypy — `python_version = "3.12"`, `pydantic.mypy` plugin, `check_untyped_defs = true`

**Testing:**
- pytest `>=latest` — test runner
- pytest-cov `>=7.1.0` — coverage reporting (`--cov=components`)
- Test markers: `integration` (requires real database)
- Test directories: `components/datamanager/test`, `components/portifoliomaster/test`, `components/tradingmonitor/test`
- `--import-mode=importlib` to support Polylith namespace packages

**Mutation Testing:**
- mutmut `>=3.5.0` — mutation testing on `components/`

**Code Quality:**
- radon `>=6.0.1` — cyclomatic complexity and maintainability index
- xenon `>=0.9.3` — complexity thresholds: `--max-absolute E --max-modules D --max-average B`
- vulture `>=2.15` — dead code detection (80% confidence threshold)
- deptry `>=0.25.1` — unused/missing dependency detection

**Architecture Validation:**
- polylith-cli — `poly check` and `poly info` for workspace integrity
- import-linter `>=2.11` — enforces layer isolation contracts

**Pre-commit:**
- pre-commit `>=4.5.1` with hooks: trailing-whitespace, end-of-file-fixer, check-yaml, check-ast, ruff, ruff-format, gitleaks, polylith-check, import-linter, xenon, vulture

**Secrets Scanning:**
- gitleaks `v8.24.0` — prevents secrets from being committed

**Containerization:**
- Docker — DataManager API production image (`projects/datamanager/Dockerfile`), multi-stage Python 3.12-slim build
- Docker Compose — TradingMonitor (`projects/tradingmonitor/docker-compose.yml`), DataManager (`projects/datamanager/docker-compose.yml`)

## Configuration

**Environment:**
- `.env` file loaded via pydantic-settings `SettingsConfigDict(env_file=".env")`
- DataManager uses `DATAMANAGER_` prefix for env vars
- TradingMonitor uses unprefixed env vars
- Template: `.env.example` at workspace root

**Key Config Files:**
- `pyproject.toml` — workspace root config (uv workspace, ruff, mypy, pytest, polylith, mutmut, deptry, vulture)
- `.pre-commit-config.yaml` — pre-commit hook definitions
- `projects/datamanager/alembic.ini` — Alembic migration config
- `.importlinter` — layer isolation rules (referenced by pre-commit)

## Platform Requirements

**Development:**
- Python 3.12+, uv installed
- Docker + Docker Compose (for TimescaleDB)
- `.env` file configured

**Production (DataManager):**
- Docker image: `ghcr.io/guilsmatos1/datamanager:latest`
- Docker Compose deployment via `projects/datamanager/docker-compose.yml`
- Exposes port 8686

**Production (TradingMonitor):**
- Docker Compose: `projects/tradingmonitor/docker-compose.yml`
- TimescaleDB on `localhost:5433` (mapped from container port 5432)
- TCP ingestion server on `127.0.0.1:5555`
- Dashboard on `127.0.0.1:8000`

---

*Stack analysis: 2026-03-28*
