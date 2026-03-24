# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TradingMonitor is a Python CLI tool that ingests real-time trading data from MetaTrader 5 (MT5) via TCP and stores/analyzes it in TimescaleDB (PostgreSQL with time-series extensions).

**Este é um projeto pessoal, usado exclusivamente pelo próprio desenvolvedor. Não há múltiplos usuários, equipe, nem uso em produção compartilhado.** Decisões de design devem priorizar simplicidade e praticidade acima de escalabilidade, segurança multi-tenant ou robustez enterprise.

## Commands

All CLI commands require `uv run` or `PYTHONPATH=.`.

```bash
# Start the database
docker-compose up -d

# Initialize database schema (creates hypertables)
uv run trading-monitor setup-db

# Start the ingestion daemon (long-running TCP server)
uv run trading-monitor start-ingestion

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
uv run pytest tests/
```

## Architecture

### Data Flow

```
MT5 EA (MQL5) → TCP PUB (port 5555) → Python TCP Server → Pydantic validation → TimescaleDB
```

The `src/mql5/MetricsPublisher.mq5` Expert Advisor publishes messages in the format `"{TOPIC} {JSON}"` with three topics: `DEAL`, `EQUITY`, `ACCOUNT`.

### Layer Responsibilities

- **`src/ingestion/tcp_server.py`** — Subscribes to TCP, routes messages by topic, auto-creates strategies/accounts on first encounter, transactional commit/rollback
- **`src/ingestion/schemas.py`** — Pydantic models validating incoming TCP payloads before DB writes
- **`src/db/models.py`** — SQLAlchemy ORM: `Account`, `Strategy`, `Deal`, `EquityCurve`, `Portfolio` (many-to-many via `portfolio_strategy`)
- **`src/db/database.py`** — Engine/session factory + `init_db()` which creates TimescaleDB hypertables via raw SQL
- **`src/metrics/calculator.py`** — Pandas/quantstats analytics: fetches deals + equity curve, computes Sharpe, drawdown, win rate, profit factor; portfolio mode aligns multi-strategy equity via forward-fill
- **`src/cli/main.py`** — Typer CLI wiring all commands together

### Key Design Decisions

- **Strategy ID = MT5 Magic Number** — the magic number used in MT5 EAs is the primary key used to identify strategies throughout the system
- **TimescaleDB hypertables** — `deals` and `equity_curve` are hypertables partitioned by timestamp; created imperatively in `init_db()`, not via Alembic
- **Auto-discovery** — `tcp_server.py` calls `ensure_strategy_exists()` to create unknown strategies/accounts automatically when their first trade arrives
- **PYTHONPATH dependency** — no package install; all imports use `src.` prefix, requiring `PYTHONPATH=.` or `uv run` at runtime

### Environment

- **`DATABASE_URL`** env var — defaults to `postgresql://postgres:password@localhost:5432/tradingmonitor`
- **TCP Ingestion** — hardcoded to `127.0.0.1:5555`
- **Docker** — `docker-compose.yml` runs TimescaleDB on port 5432 with persistent volume `timescaledb_data`

## Gemini Pipeline

Ao finalizar uma implementação, avalie se houve **nova feature** (novo método público, nova rota, nova classe, novo comportamento observável). Refatorações, correções de bug, ajustes de config e formatação **não** disparam o pipeline.

Se houver nova feature, execute os dois passos abaixo **em sequência**:

### 1. Gemini Tests

```bash
gemini -p "Voce e um Engenheiro de QA senior do projeto TradingMonitor (Python, uv, src/). Crie ou atualize testes unitarios em tests/ para cobrir a seguinte nova feature: <descreva a feature>. Use pytest, siga os padroes de tests/ (fixtures, mocks). Execute 'uv run pytest tests/ -v' para verificar que todos os testes passam. Se algum teste falhar, corrija-o. Apos escrever os testes, pare imediatamente." --yolo
```

### 2. Gemini Docs

```bash
gemini -p "Voce e um Engenheiro de Documentacao senior do projeto TradingMonitor (Python, uv, src/). DIFF: \$(git diff HEAD -- src/ 2>/dev/null | head -300). Leia apenas README.md, CODEBASE_DOCS.md e docs/ para entender o que ja esta documentado — NAO leia arquivos em src/ nem em tests/. Atualize README.md, CODEBASE_DOCS.md e/ou docs/ refletindo as mudancas tecnicas — documente comportamento e arquitetura, nunca codigo linha por linha. Em seguida execute 'git add' em todos os arquivos modificados neste pipeline (docs/** + README.md + CODEBASE_DOCS.md + tests/**) e faca um unico 'git commit' com prefixo 'chore:' e rodape 'Pipeline-by: Gemini CLI'. Se nao houver mudancas pendentes, responda apenas SKIP. Apos o commit, pare imediatamente." --yolo
```

## Ruff Workflow

Always run Ruff after implementing or editing Python files.

```bash
# Lint and auto-fix
uv run ruff check --fix .

# Format
uv run ruff format .

# Full run (recommended)
uv run ruff check --fix . && uv run ruff format .
```

### Workflow Rules
1. Implement the requested functionality.
2. Run `uv run ruff check --fix . && uv run ruff format .`
3. Check if any warnings remain.
