# DataManager — Reference Guide

## Overview
Centralized financial data management system that fetches, stores, and manages OHLCV candlestick data and FRED economic series. Exposes a CLI and a REST API (port 8686).

**Stack:** Python ≥3.12 · FastAPI/Uvicorn · TimescaleDB (PostgreSQL) · Pandas · Ruff · Pytest · uv

## Architecture (Polylith)
- **bases/datamanager_cli** — Interactive shell (cmd.Cmd); all user-facing CLI commands
- **bases/datamanager_api** — FastAPI REST API (port 8686)
- **components/datamanager** — All business logic: fetchers, db, services, schemas

### Core Principle — M1-First
All data is fetched and stored at **M1 (1-minute)** resolution. Higher timeframes are derived — never fetched directly:
- **TimescaleDB continuous aggregates:** M2, M5, M10, M15, M30, H1, H2, H3, H4, H6, D1, W1

### Module Map
```
components/datamanager/src/trademachine/datamanager/
  client.py           → HTTP client for the API
  db/database.py      → SQLAlchemy async engine + session
  db/models.py        → ORM models (OHLCV, assets, sources, FRED)
  db/processor.py     → DataProcessor: resampling + gap filling (TF_MAPPING)
  db/storage.py       → StorageManager: TimescaleDB OHLCV I/O
  db/series_storage.py→ SeriesStorageManager: FRED persistence
  fetchers/base.py    → BaseFetcher ABC
  fetchers/ccxt.py    → Crypto (exchange:SYMBOL)
  fetchers/dukascopy.py → Forex/commodities
  fetchers/openbb.py  → Equities/ETFs (yfinance)
  fetchers/fred.py    → FRED economic series
  services/manager.py → DataManager: OHLCV orchestrator
  services/series_manager.py → FRED orchestrator
  services/scheduler.py → Background scheduler (APScheduler)
  schemas/            → Pydantic request/response models
```

## Commands
```bash
uv sync --dev                                                 # install deps
uv run pytest components/datamanager/test/                   # run tests
uv run datamanager -i                                        # interactive CLI
uv run datamanager download dukascopy EURUSD 2024-01-01 2024-12-31
uv run uvicorn trademachine.datamanager_api.router:app --host 0.0.0.0 --port 8686
docker compose up -d                                         # API via Docker
```

## Environment Variables
| Variable              | Description                                      |
|-----------------------|--------------------------------------------------|
| `DATABASE_URL`        | PostgreSQL/TimescaleDB connection string         |
| `DATAMANAGER_API_KEY` | Secret key — required for all authenticated APIs |
| `DATAMANAGER_HOST`    | API host (default `0.0.0.0`)                     |
| `DATAMANAGER_PORT`    | API port (default `8686`)                        |
| `FRED_API_KEY`        | FRED API key (required for economic series)      |

## REST API — Key Endpoints (all require `X-API-Key` header)
- `POST /download` · `POST /update` · `POST /delete` · `GET /list`
- `GET /info/{source}/{asset}/{timeframe}` · `GET /data/{source}/{asset}/{timeframe}`
- `GET /data/.../stream` (CSV) · `GET /search`
- `POST /series/download` · `POST /series/update` · `GET /series/list`
- `GET /series/data/{source}/{series_id}` · `POST /series/delete`
- `GET|POST /schedule` · `DELETE /schedule/{job_id}`

## Adding a New Fetcher
1. Create class in `fetchers/` extending `BaseFetcher`.
2. Implement `source_name` property and `fetch_data(asset, start, end) → pd.DataFrame`.
3. DataFrame must have: capitalized `Open/High/Low/Close/Volume` columns + timezone-naive
   `datetime` index at M1 resolution.
4. Auto-discovered via `pkgutil`/`importlib` — no registration needed.

## Key Rules
- `download_data` raises if M1 data for that asset/source already exists → use `update`.
- Run `update all` CLI command after bulk loads to recalculate asset statistics.
- FRED uses overlap window on updates to absorb historical revisions.
- Never commit `.env`, API keys, logs, or generated DB contents.
- New timeframe → add to `DataProcessor.TF_MAPPING` in `db/processor.py`.
- API changes → update schemas in `schemas/` and routes in `datamanager_api/router.py`.
- Tests: `test_<feature>.py` in `components/datamanager/test/`; use `tmp_path` fixtures.
- Conventional Commits: `feat:`, `fix:`, `refactor:`, `chore:`, `docs:`.
