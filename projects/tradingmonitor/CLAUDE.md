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
uv run pytest components/tradingmonitor/test
```

## Architecture (Polylith)

### Data Flow

```
MT5 EA (MQL5) → TCP PUB (port 5555) → components/tradingmonitor (TCP Server) → TimescaleDB
```

### Layer Responsibilities

- **`components/tradingmonitor`** — Core logic component.
    - `ingestion/tcp_server.py` — TCP server, routes messages, auto-creates strategies/accounts.
    - `ingestion/schemas.py` — Pydantic models for TCP payloads.
    - `db/models.py` — SQLAlchemy ORM: `Account`, `Strategy`, `Deal`, `EquityCurve`, `Portfolio`.
    - `db/database.py` — Engine/session factory + `init_db()` for hypertables.
    - `metrics/calculator.py` — Pandas/quantstats analytics.
- **`bases/trading_monitor_cli`** — Typer CLI wiring (`main.py`).
- **`bases/trading_monitor_dashboard`** — FastAPI web dashboard (`app.py`, `routes.py`).

### Key Design Decisions

- **Namespace: `trademachine`** — All imports use `from trademachine.<brick> import ...`.
- **Strategy ID = MT5 Magic Number** — Magic number is the primary key for strategies.
- **TimescaleDB hypertables** — `deals` and `equity_curve` are hypertables partitioned by timestamp.
- **Auto-discovery** — Unknown strategies/accounts are created automatically on the first trade.

## Gemini Pipeline

Ao finalizar uma implementação, avalie se houve **nova feature** (novo método público, nova rota, nova classe, novo comportamento observável). Refatorações, correções de bug, ajustes de config e formatação **não** disparam o pipeline.

Se houver nova feature, execute os dois passos abaixo **em sequência**:

### 1. Gemini Tests

```bash
gemini -p "Voce e um Engenheiro de QA senior do projeto TradingMonitor (Python, uv, Polylith). Crie ou atualize testes unitarios em components/tradingmonitor/test para cobrir a seguinte nova feature: <descreva a feature>. Use pytest, siga os padroes de tests/ (fixtures, mocks). Execute 'uv run pytest components/tradingmonitor/test -v' para verificar que todos os testes passam. Se algum teste falhar, corrija-o. Apos escrever os testes, pare imediatamente." --yolo
```

### 2. Gemini Docs

```bash
gemini -p "Voce e um Engenheiro de Documentacao senior do projeto TradingMonitor (Python, uv, Polylith). DIFF: \$(git diff HEAD -- components/tradingmonitor/ bases/trading_monitor_* 2>/dev/null | head -300). Leia apenas README.md, GEMINI.md e CLAUDE.md para entender o que ja esta documentado. Atualize README.md, GEMINI.md e/ou CLAUDE.md refletindo as mudancas tecnicas — documente comportamento e arquitetura, nunca codigo linha por linha. Em seguida execute 'git add' em todos os arquivos modificados e faca um unico 'git commit' com prefixo 'chore:' e rodape 'Pipeline-by: Gemini CLI'. Se nao houver mudancas pendentes, responda apenas SKIP. Apos o commit, pare imediatamente." --yolo
```

## Ruff Workflow

Always run Ruff after implementing or editing Python files.

```bash
uv run ruff check --fix . && uv run ruff format .
```
