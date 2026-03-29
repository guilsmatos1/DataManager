# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies (including dev tools)
uv sync --dev

# Run the interactive CLI
uv run datamanager -i

# Run a single CLI command directly
uv run datamanager download dukascopy EURUSD 2024-01-01 2024-12-31

# Start the REST API server (port 8686)
uv run uvicorn trademachine.datamanager_api.router:app --reload

# Run all tests
uv run pytest tests/

# Run a single test file
uv run pytest tests/unit/test_processor.py -v

# Lint (with auto-fix) and format
uv run ruff check --fix . && uv run ruff format .

# Docker (REST API mode)
docker-compose up -d
```

## Architecture

**DataManager** is a financial data management system that fetches, stores, and manages OHLCV (Open/High/Low/Close/Volume) candlestick data. The system exposes two independent interfaces (CLI and REST API) that share the same core orchestrator.

### Core Principle

All data is always fetched and stored at **M1 (1-minute) resolution first**. Higher timeframes (M5, M15, H1, D1, etc.) are derived via resampling — they are never fetched directly from sources.

### Module Responsibilities

```
bases/datamanager_cli/src/trademachine/datamanager_cli/cli.py
                                      → Interactive shell (cmd.Cmd); all user-facing CLI commands

bases/datamanager_api/src/trademachine/datamanager_api/router.py
                                      → FastAPI REST API (port 8686)

components/datamanager/src/trademachine/datamanager/
  ├── client.py                       → Python HTTP client for the API
  ├── core/config.py                  → Pydantic settings (DATABASE_URL, DATAMANAGER_API_KEY)
  ├── db/
  │   ├── database.py                 → SQLAlchemy async engine + session
  │   ├── models.py                  → ORM models (OHLCV, assets, sources)
  │   ├── processor.py                → DataProcessor: OHLCV resampling + gap filling
  │   └── storage.py                  → StorageManager: TimescaleDB I/O (hypertable + continuous aggregates)
  ├── fetchers/
  │   ├── base.py                    → BaseFetcher ABC
  │   ├── ccxt.py                    → CCXT integration (crypto; exchange:SYMBOL)
  │   ├── dukascopy.py               → Dukascopy integration (forex, commodities)
  │   └── openbb.py                 → OpenBB/YFinance integration (equities, ETFs)
  ├── schemas/                        → Pydantic request/response models
  └── services/
      ├── manager.py                  → DataManager: central orchestrator
      └── scheduler.py                → Background job scheduler (APScheduler)
```

### Data Flow

```
User (CLI or API)
  → DataManager (trademachine.datamanager.services.manager)
    → Fetcher.fetch_data() → M1 DataFrame
    → StorageManager.save_data() → TimescaleDB hypertable (ohlcv_m1)
    → TimescaleDB continuous aggregates → M5, M15, H1, H4, D1 (automatic refresh)
```

### Storage Layout (TimescaleDB)

```
TimescaleDB (PostgreSQL):
  ├── ohlcv_m1        — Hypertable: raw 1-minute OHLCV data (primary write target)
  ├── ohlcv_m5        — Continuous aggregate: 5-minute OHLCV
  ├── ohlcv_m15       — Continuous aggregate: 15-minute OHLCV
  ├── ohlcv_h1        — Continuous aggregate: 1-hour OHLCV
  ├── ohlcv_h4        — Continuous aggregate: 4-hour OHLCV
  ├── ohlcv_d1        — Continuous aggregate: 1-day OHLCV
  ├── sources         — Catalog: data source names
  └── assets         — Catalog: tickers per source with min/max/row_count

metadata/
metadata/dukas_assets.csv      # ~3,000 valid Dukascopy asset symbols
```

Use `DataManager.update_stats()` / CLI `rebuild` command to recalculate asset statistics after bulk loads.

### Adding a New Fetcher

Create a class in `components/datamanager/src/trademachine/datamanager/fetchers/` that extends `BaseFetcher` and implements:
- `source_name` property (string identifier)
- `fetch_data(asset, start_date, end_date) -> pd.DataFrame` (must return M1 OHLCV data)
- `search(query) -> pd.DataFrame` (optional; raises `NotImplementedError` by default)

The DataFrame returned by `fetch_data` must have:
- Index: `datetime` timezone-naive
- Columns: `Open`, `High`, `Low`, `Close`, `Volume` (capitalized)

The fetcher is auto-discovered via `pkgutil`/`importlib` in `trademachine.datamanager.fetchers` — no registration required. Modules that fail to import (e.g. missing optional dependencies) are skipped with a warning.

**Important**: `download_data` raises an exception if an M1 database for that asset/source already exists. Use the `update` command to append newer data to an existing database.

### Supported Timeframes

`M1, M2, M5, M10, M15, M30, H1, H2, H3, H4, H6, D1, W1`

- **TimescaleDB native (continuous aggregates):** M1 (hypertable), M5, M15, H1, H4, D1
- **Derived via resampling:** M2, M10, M30, H2, H3, H6, W1 (via `DataProcessor` from M1 data)

Mapping to pandas resample strings is defined in `DataProcessor.TF_MAPPING`.

## Gemini Pipeline

Ao finalizar uma implementação, avalie se houve **nova feature** (novo método público, nova rota, nova classe, novo comportamento observável). Refatorações, correções de bug, ajustes de config e formatação **não** disparam o pipeline.

Se houver nova feature, execute os dois passos abaixo **em sequência**:

### 1. Gemini Tests

```bash
gemini -p "Voce e um Engenheiro de QA senior do projeto DataManager (Python, uv, src/datamanager/). Crie ou atualize testes unitarios em tests/unit/ para cobrir a seguinte nova feature: <descreva a feature>. Use pytest e unittest.mock, siga os padroes de tests/unit/ (fixtures, mocks, tmp_path). Execute 'uv run pytest tests/ -v' para verificar que todos os testes passam. Se algum teste falhar, corrija-o. Apos escrever os testes, pare imediatamente." --yolo
```

### 2. Gemini Docs

```bash
gemini -p "Voce e um Engenheiro de Documentacao senior do projeto DataManager (Python, uv, src/datamanager/). DIFF: $(git diff HEAD -- src/ 2>/dev/null | head -300). Leia apenas README.md e docs/ para entender o que ja esta documentado — NAO leia arquivos em src/ nem em tests/. Atualize README.md e/ou docs/ refletindo as mudancas tecnicas — documente comportamento e arquitetura, nunca codigo linha por linha. Em seguida execute 'git add' em todos os arquivos modificados neste pipeline (docs/** + README.md + tests/**) e faca um unico 'git commit' com prefixo 'chore:' e rodape 'Pipeline-by: Gemini CLI'. Se nao houver mudancas pendentes, responda apenas SKIP. Apos o commit, pare imediatamente." --yolo
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

### REST API Auth

Set `DATAMANAGER_API_KEY` in `.env` (see `.env.example`). All API requests require the header `X-API-Key: <value>`.
