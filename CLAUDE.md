# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TradeMachine is a Python 3.12+ monorepo for financial trading systems using **Polylith architecture**. It manages:
- **DataManager**: OHLCV data fetching/storage (OpenBB, Dukascopy, CCXT)
- **TradingMonitor**: Real-time MT5 trade monitoring via TimescaleDB
- **PortfolioMaster**: Portfolio optimization and backtesting analysis
- **BacktestEngine**: NautilusTrader-based backtesting

**Personal project** — design decisions prioritize simplicity over enterprise scalability.
- **Single-user** — no multi-user, no commercial deployment
- Rate limiting is in-memory only (no Redis); acceptable for single uvicorn worker
- No horizontal scaling requirements; no distributed caching
- Simplicity over feature completeness in all architectural decisions

---

## Common Commands

```bash
# Install dependencies
uv sync --dev

# Run tests
uv run pytest tests/                          # All tests
uv run pytest tests/unit/test_file.py -v      # Single file
uv run pytest -m not integration              # Skip integration tests

# Lint & format (Ruff)
uv run ruff check --fix . && uv run ruff format .

# Type checking
uv run mypy .

# Architecture validation
uv tool run --from polylith-cli poly info     # Workspace overview
uv tool run --from polylylith-cli poly check   # Validate Polylith integrity
uv run lint-imports                            # Layer isolation contracts

# Quality checks
uv run deptry .                               # Unused/missing dependencies
uv run radon cc . -a                          # Cyclomatic complexity
uv run radon mi .                             # Maintainability index
uv run xenon --max-absolute E .               # Block high complexity
uv run vulture . --min-confidence 80         # Dead code detection
uv run mutmut run && uv run mutmut results    # Mutation testing
```

---

## Architecture

### Polylith Structure

```
bases/        → Entry points (APIs, CLIs, TCP servers)
components/  → Reusable business logic (no base dependencies)
projects/    → Build configurations combining bases + components
```

**Namespace**: `trademachine` — all internal imports follow `from trademachine.<component> import ...`

### Layer Isolation Rules

Components (business logic) are **forbidden** from importing bases (entry points). This keeps logic portable and testable.

- `trademachine.datamanager` → cannot import from any base
- `trademachine.tradingmonitor` → cannot import from any base
- `trademachine.portifoliomaster` → cannot import from any base
- `trademachine.backtestengine` → cannot import from any base
- `trademachine.core` → cannot import from any base
- `trademachine.mt5` → cannot import from any base

### Components

| Component | Purpose |
|-----------|---------|
| `datamanager` | OHLCV fetching, Parquet storage, resampling (M1-first principle) |
| `tradingmonitor` | MT5 TCP ingestion, TimescaleDB storage, metrics (Sharpe, drawdown) |
| `portifoliomaster` | MT5 HTML report parsing, brute-force portfolio optimization |
| `backtestengine` | NautilusTrader-based backtesting |
| `mt5` | MetaTrader 5 data format parsing |
| `core` | Shared logger utilities |

### Bases (Entry Points)

| Base | Interface |
|------|-----------|
| `datamanager_api` | FastAPI REST API (port 8686) |
| `datamanager_cli` | Interactive CLI |
| `trading_monitor_ingestion` | TCP ingestion daemon |
| `trading_monitor_cli` | TradingMonitor CLI |
| `trading_monitor_dashboard` | Dashboard interface |
| `portifolio_master_cli` | PortfolioMaster CLI |
| `backtest_engine_cli` | Backtest CLI |

---

## Key Entry Points

```bash
# DataManager
uv run datamanager -i                         # Interactive CLI
uv run uvicorn datamanager.api.router:app     # REST API

# TradingMonitor
uv run trading-monitor start-ingestion       # TCP ingestion daemon
uv run trading-monitor setup-db               # Initialize TimescaleDB

# PortfolioMaster
uv run portifoliomaster -i                    # Interactive CLI
```

---

## Project-Specific Documentation

Each project has detailed documentation:
- `projects/datamanager/CLAUDE.md` — DataManager architecture and workflows
- `projects/tradingmonitor/CLAUDE.md` — TradingMonitor architecture
- `projects/portifoliomaster/CLAUDE.md` — PortfolioMaster architecture

---

## Quality Enforcement

Pre-commit hooks (`.pre-commit-config.yaml`) run automatically:
- ruff (lint + format)
- import-linter (layer isolation)
- polylith-check
- xenon (complexity)
- vulture (dead code)
- gitleaks (secrets)

Run pre-commit manually: `uv run pre-commit run --all-files`

---

## Ruff Workflow

After implementing or editing Python files:

```bash
uv run ruff check --fix . && uv run ruff format .
```

---

## Environment

Copy `.env.example` to `.env` and configure:
- `DATAMANAGER_API_KEY` — REST API authentication
- `DATABASE_URL` — TimescaleDB connection (TradingMonitor)
- Telegram bot token for notifications
