# GEMINI.md

This file provides foundational instructions and project context for Gemini CLI when working within the **DataManager** repository.

## Project Overview

**DataManager** is a centralized financial data management system designed to fetch, store, update, and resample OHLCV (Open, High, Low, Close, Volume) candlestick data. It provides both a Command-Line Interface (CLI) and a REST API for managing data in TimescaleDB.

### Core Technologies
- **Language:** Python >= 3.12
- **Package Manager:** [uv](https://docs.astral.sh/uv/)
- **Data Processing:** Pandas
- **Data Sources:** OpenBB (yfinance), Dukascopy, CCXT (crypto)
- **Web Framework:** FastAPI, Uvicorn
- **Storage:** TimescaleDB (PostgreSQL) — hypertable `ohlcv_m1` + continuous aggregates
- **Dev Tools:** Ruff (linting/formatting), Pytest (testing), Docker

### Key Architecture
- **Polylith Layout:** Components (`trademachine.datamanager.*`) + Bases (`datamanager_cli`, `datamanager_api`)
- **Core Orchestrator:** `components/datamanager/src/trademachine/datamanager/services/manager.py` (`DataManager` class)
- **M1-First Principle:** All data is fetched and stored at **1-minute (M1) resolution** first. Higher native timeframes (M5, M15, H1, H4, D1) are TimescaleDB continuous aggregates; others are derived via resampling.
- **Modular Fetchers:** Located in `components/datamanager/src/trademachine/datamanager/fetchers/`, extending `BaseFetcher`.
- **Storage Management:** `components/datamanager/src/trademachine/datamanager/db/storage.py` handles TimescaleDB I/O via SQLAlchemy.
- **Resampling Logic:** `components/datamanager/src/trademachine/datamanager/db/processor.py` handles OHLCV resampling using Pandas.

## Building and Running

### Installation
```bash
uv sync --dev
```

### CLI Usage
- **Interactive Mode:** `uv run datamanager -i`
- **Direct Commands:**
  - `uv run datamanager download <source> <assets> <start_date> <end_date>`
  - `uv run datamanager update <source> <assets> [timeframe]`
  - `uv run datamanager list`
  - `uv run datamanager search --query <query>`

### REST API
- **Start Server:** `uv run uvicorn trademachine.datamanager_api.router:app --host 0.0.0.0 --port 8686 --reload`
- **Authentication:** Requires `X-API-Key` header (set `DATAMANAGER_API_KEY` in `.env`).

### Docker
- **CLI Mode:** `docker compose run --rm datamanager`
- **API Mode:** `docker compose up -d`

## Development Conventions

### Coding Standards
- **Linting & Formatting:** Use **Ruff**.
  - Check: `uv run ruff check .`
  - Fix & Format: `uv run ruff check --fix . && uv run ruff format .`
- **Type Safety:** Use type hints and Pydantic models (found in `components/datamanager/src/trademachine/datamanager/schemas/`).
- **Logging:** Use the standard Python `logging` module.

### Testing
- **Framework:** Pytest
- **Run all tests:** `uv run pytest components/datamanager/test/`
- **Run specific test:** `uv run pytest components/datamanager/test/unit/test_processor.py`

### Adding New Features
1. **New Fetcher:** Implement `BaseFetcher` in `components/datamanager/src/trademachine/datamanager/fetchers/`. Ensure it returns M1 DataFrames with capitalized OHLCV columns and a `datetime` index.
2. **New Timeframe:** Add to `DataProcessor.TF_MAPPING` in `components/datamanager/src/trademachine/datamanager/db/processor.py`.
3. **API Changes:** Update schemas in `components/datamanager/src/trademachine/datamanager/schemas/` and routes in `bases/datamanager_api/src/trademachine/datamanager_api/router.py`.

### Database Schema
- TimescaleDB hypertable: `ohlcv_m1` (partitioned by `timestamp`)
- Continuous aggregates: `ohlcv_m5`, `ohlcv_m15`, `ohlcv_h1`, `ohlcv_h4`, `ohlcv_d1`
- All fetched DataFrames must have: `Open`, `High`, `Low`, `Close`, `Volume` (Capitalized) and a timezone-naive `datetime` index.
