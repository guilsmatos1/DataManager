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
uv run uvicorn datamanager.api.router:app --reload

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
src/datamanager/main.py              → CLI entry point; routes -i flag to interactive shell or executes single command
src/datamanager/cli.py               → Interactive shell (cmd.Cmd); all user-facing CLI commands
src/datamanager/api/router.py        → FastAPI REST API (port 8686); mirrors CLI capabilities + Dashboard/Stats/Streaming
src/datamanager/client.py            → Python HTTP client for consuming api/router.py
src/datamanager/services/manager.py → DataManager class: central orchestrator coordinating all subsystems
src/datamanager/db/
  storage.py                         → StorageManager: Parquet I/O + SQLite catalog + Data Versioning
  processor.py                       → DataProcessor: OHLCV resampling + Gap filling logic
src/datamanager/fetchers/
  base.py                            → BaseFetcher ABC: interface all fetchers must implement
  openbb.py                          → OpenBB/YFinance integration (equities, ETFs)
  dukascopy.py                       → Dukascopy integration (forex, commodities)
  ccxt.py                            → CCXT integration (crypto; supports exchange:SYMBOL)
src/datamanager/core/config.py       → Pydantic settings (API key, host, port)
src/datamanager/schemas/__init__.py  → Pydantic request/response models for the REST API
src/datamanager/utils/logger.py      → Structured logging (Console + JSON)
```

### Data Flow

```
User (CLI/API)
  → DataManager (src/datamanager/services/manager.py)
    → Fetcher.fetch_data() → M1 DataFrame
    → StorageManager.save_data() → Parquet on disk + Automatic backup
    → DataProcessor.resample_ohlc() → Higher timeframe DataFrames
    → StorageManager.save_data() → Additional Parquet files
```

### Storage Layout

```
database/{source}/{ASSET}/{TIMEFRAME}/data.parquet
database/.versions/            # Timestamped backups (last 5 per asset/TF)
metadata/catalog.db            # SQLite index of all stored databases (WAL mode)
metadata/dukas_assets.csv      # ~3,000 valid Dukascopy asset symbols
```

`catalog.db` (SQLite) stores metadata for every database entry (source, asset, timeframe, date range, row count, size). Use `DataManager.rebuild_catalog()` / CLI `rebuild` command if catalog drifts out of sync with disk.

### Adding a New Fetcher

Create a class in `src/datamanager/fetchers/` that extends `BaseFetcher` and implements:
- `source_name` property (string identifier)
- `fetch_data(asset, start_date, end_date) -> pd.DataFrame` (must return M1 OHLCV data)
- `search(query) -> pd.DataFrame` (optional; raises `NotImplementedError` by default)

The DataFrame returned by `fetch_data` must have:
- Index: `datetime` timezone-naive
- Columns: `Open`, `High`, `Low`, `Close`, `Volume` (capitalized)

The fetcher is auto-discovered via `pkgutil`/`importlib` in `src/datamanager/fetchers/__init__.py` — no registration required. Modules that fail to import (e.g. missing optional dependencies) are skipped with a warning.

**Important**: `download_data` raises an exception if an M1 database for that asset/source already exists. Use the `update` command to append newer data to an existing database.

### Supported Timeframes

`M1, M2, M5, M10, M15, M30, H1, H2, H3, H4, H6, D1, W1`

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
