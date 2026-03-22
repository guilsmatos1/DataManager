# GEMINI.md

This file provides foundational instructions and project context for Gemini CLI when working within the **DataManager** repository.

## Project Overview

**DataManager** is a centralized financial data management system designed to fetch, store, update, and resample OHLCV (Open, High, Low, Close, Volume) candlestick data. It provides both a Command-Line Interface (CLI) and a REST API for managing local financial databases.

### Core Technologies
- **Language:** Python >= 3.12
- **Package Manager:** [uv](https://docs.astral.sh/uv/)
- **Data Processing:** Pandas, Fastparquet
- **Data Sources:** OpenBB (yfinance), Dukascopy
- **Web Framework:** FastAPI, Uvicorn
- **Storage:** Parquet (data files) and JSON (metadata catalog)
- **Dev Tools:** Ruff (linting/formatting), Pytest (testing), Docker

### Key Architecture
- **Source Layout:** `src/datamanager/`
- **Core Orchestrator:** `src/datamanager/services/manager.py` (`DataManager` class) coordinates all sub-systems.
- **M1-First Principle:** All data is fetched and stored at **1-minute (M1) resolution** first. Higher timeframes are always derived via resampling.
- **Modular Fetchers:** Located in `src/datamanager/fetchers/`, extending `BaseFetcher`.
- **Storage Management:** `src/datamanager/db/storage.py` handles I/O and the `metadata/catalog.json` index.
- **Resampling Logic:** `src/datamanager/db/processor.py` handles OHLCV resampling using Pandas.

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
- **Start Server:** `uv run uvicorn datamanager.api.router:app --host 0.0.0.0 --port 8686 --reload`
- **Authentication:** Requires `X-API-Key` header (set `DATAMANAGER_API_KEY` in `.env`).

### Docker
- **CLI Mode:** `docker compose run --rm datamanager`
- **API Mode:** `docker compose up -d`

## Development Conventions

### Coding Standards
- **Linting & Formatting:** Use **Ruff**.
  - Check: `uv run ruff check .`
  - Fix & Format: `uv run ruff check --fix . && uv run ruff format .`
- **Type Safety:** Use type hints and Pydantic models (found in `src/datamanager/schemas/`).
- **Logging:** Use the custom logger in `src/datamanager/utils/logger.py` which outputs to both stdout and `log.log`.

### Testing
- **Framework:** Pytest
- **Run all tests:** `uv run pytest tests/`
- **Run specific test:** `uv run pytest tests/unit/test_processor.py`

### Adding New Features
1. **New Fetcher:** Implement `BaseFetcher` in `src/datamanager/fetchers/`. Ensure it returns M1 DataFrames with capitalized OHLCV columns and a `datetime` index.
2. **New Timeframe:** Add to `DataProcessor.TF_MAPPING` in `src/datamanager/db/processor.py`.
3. **API Changes:** Update schemas in `src/datamanager/schemas/` and routes in `src/datamanager/api/router.py`.

### Data Integrity
- Use `uv run datamanager rebuild` to resync the `catalog.json` with physical files on disk.
- All fetched DataFrames must have: `Open`, `High`, `Low`, `Close`, `Volume` (Capitalized) and a timezone-naive `datetime` index.
