# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TradingMonitor is a Python CLI tool that ingests real-time trading data from MetaTrader 5 (MT5) via TCP and stores/analyzes it in TimescaleDB. Built using the **Polylith Architecture**.

**Este é um projeto pessoal, usado exclusivamente pelo próprio desenvolvedor. Não há múltiplos usuários, equipe, nem uso em produção compartilhado.** Decisões de design devem priorizar simplicidade e praticidade acima de escalabilidade, segurança multi-tenant ou robustez enterprise.

## Commands

All CLI commands require `uv run`.

```bash
# Start the database
docker-compose up -d

# Initialize database schema (creates hypertables)
uv run trading-monitor setup-db

# Start the ingestion daemon (long-running TCP server)
uv run trading-monitor start-ingestion

# Start the dashboard (includes ingestion)
uv run trading-monitor start-dashboard

# Register entities
uv run trading-monitor register-account <login> --name "Name" --broker "Broker" --currency USD
uv run trading-monitor register-strategy <magic_number> --name "Name" --symbol EURUSD --timeframe M15
uv run trading-monitor create-portfolio --name "Portfolio1" --balance 100000
uv run trading-monitor add-to-portfolio <portfolio_id> <strategy_id>

# Reports
uv run trading-monitor report <magic_number>
uv run trading-monitor portfolio-report <portfolio_id>

# Database migrations
alembic revision --autogenerate -m "description"
alembic upgrade head

# Tests
uv run pytest components/tradingmonitor_storage/test components/tradingmonitor_ingestion/test components/tradingmonitor_analytics/test bases/trading_monitor_cli/test bases/trading_monitor_dashboard/test
```

## Architecture (Polylith)

### Data Flow

```
MT5 EA (MQL5) → components/tradingmonitor_ingestion (TCP server) → components/tradingmonitor_storage (TimescaleDB) → components/tradingmonitor_analytics (metrics, benchmarks, drift)
```

### Layer Responsibilities

- **`components/tradingmonitor_ingestion`** — TCP server, payload validation, heartbeat and dead-letter handling.
    - `ingestion/tcp_server.py` — TCP server, routes messages, auto-creates strategies/accounts.
    - `ingestion/schemas.py` — Pydantic models for TCP payloads.
- **`components/tradingmonitor_storage`** — Config, SQLAlchemy models, sessions and repositories.
    - `db/models.py` — SQLAlchemy ORM: `Account`, `Strategy`, `Deal`, `EquityCurve`, `Portfolio`.
    - `db/database.py` — Engine/session factory + `init_db()` for hypertables.
- **`components/tradingmonitor_analytics`** — Metrics, benchmarks, drift and reporting logic.
    - `metrics/calculator.py` — Pandas/quantstats analytics.
- **`bases/trading_monitor_cli`** — Typer CLI wiring (`main.py`).
- **`bases/trading_monitor_dashboard`** — FastAPI web dashboard (`app.py`, `routes.py`).

### Key Design Decisions

- **Namespace: `trademachine`** — All imports use `from trademachine.<brick> import ...`.
- **Strategy ID = MT5 Magic Number** — Magic number is the primary key for strategies.
- **TimescaleDB hypertables** — `deals` and `equity_curve` are hypertables partitioned by timestamp.
- **Auto-discovery** — Unknown strategies/accounts are created automatically on the first trade.

## Ruff Workflow

Always run Ruff after implementing or editing Python files.

```bash
uv run ruff check --fix . && uv run ruff format .
```
