# DataManager

## Overview
**DataManager** is a centralized tool to fetch, store, update, and resample financial OHLCV (Open, High, Low, Close, Volume) data. It provides an interactive CLI, a single-command mode, and a REST API for programmatic access.

**Supported data sources:**
- **OpenBB** — Stocks, ETFs, indices (via yfinance)
- **Dukascopy** — Forex, commodities, indices
- **CCXT** — Crypto across multiple exchanges (e.g. `binance:BTC/USDT`) — optional extra

## Key Features
- **M1-First principle:** All data is fetched at 1-minute resolution. Higher timeframes are always derived via resampling — never fetched directly.
- **Smart updating:** `update` always refreshes the M1 base first and then rebuilds any requested higher timeframe from it, guaranteeing consistency.
- **Parquet storage** with atomic writes, cross-platform file locking, and automatic versioned backups (up to 5 per asset/timeframe).
- **SQLite catalog** (`metadata/catalog.db`, WAL mode) for fast, concurrent-safe metadata reads.
- **Scheduler** — cron or interval-based recurring updates, persisted to disk and restored on restart.
- **REST API** — FastAPI on port 8686, API key auth, rate limiting, pagination, and data streaming.
- **Python client** — `DataManagerClient` for direct integration with backtesting scripts.

## Architecture

```
src/datamanager/
├── main.py              # Entry point (CLI / direct command)
├── cli.py               # Interactive shell (cmd.Cmd)
├── client.py            # Python SDK for the REST API
├── api/router.py        # FastAPI REST API
├── services/
│   ├── manager.py       # Central orchestrator (DataManager class)
│   └── scheduler.py     # APScheduler background jobs (persistent)
├── db/
│   ├── storage.py       # Parquet I/O + SQLite catalog
│   └── processor.py     # OHLCV resampling + gap filling
├── fetchers/            # One module per source (base, openbb, dukascopy, ccxt)
├── core/config.py       # Settings via pydantic-settings (.env)
└── utils/               # logger.py, retry.py

metadata/
├── catalog.db           # SQLite catalog (source of truth)
└── dukas_assets.csv     # Dukascopy asset list for validation

database/
└── {source}/{ASSET}/{TF}/data.parquet
```

## Installation

Requires [uv](https://docs.astral.sh/uv/) and Python ≥ 3.12.

```bash
# Standard
uv sync --dev

# With crypto support (CCXT)
uv sync --dev --extra crypto
```

## Configuration

```bash
cp .env.example .env
```

Set `DATAMANAGER_API_KEY` in `.env`. The REST API requires this key in the `X-API-Key` header. You can also set `DATAMANAGER_HOST` and `DATAMANAGER_PORT` (default: `0.0.0.0:8686`).

> **Warning:** If `DATAMANAGER_API_KEY` is not set, the API logs a warning at startup and accepts any request — never expose it publicly without a key.

## Running

### Docker (recommended for server mode)
```bash
# Interactive CLI
docker compose run --rm datamanager uv run datamanager -i

# REST API (background)
docker compose up -d
```

### Native

```bash
# Interactive CLI shell
uv run datamanager -i

# Single command (no shell)
uv run datamanager download OPENBB AAPL 2023-01-01 2024-01-01

# REST API
uv run uvicorn datamanager.api.router:app --host 0.0.0.0 --port 8686 --reload
```

## CLI Commands

| Command | Description |
|---|---|
| `download <source> <assets> [start] [end] [-timeframe tf1,tf2]` | Download M1 data (and optionally resample) |
| `update <source> <assets> [timeframe]` | Update M1, then rebuild the requested TF |
| `update all` | Update all M1 databases and reconstruct all higher TFs |
| `resample <source> <assets> <timeframes>` | Rebuild a TF from existing M1 |
| `list` | List all saved databases |
| `info <source> <asset> <timeframe>` | Show metadata for a specific database |
| `search [--source] [--query] [--exchange]` | Search available assets |
| `quality <source> <assets> [timeframe]` | Data integrity report (gaps, duplicates, OHLC) |
| `delete <source> <assets> [timeframe]` | Delete one database (or `delete all`) |
| `schedule add/list/remove` | Manage persistent scheduled updates |
| `rebuild` | Resync `catalog.db` with files on disk |

### Examples

```bash
# Download multi-asset, full history, with resampling
download DUKASCOPY EURUSD,GBPUSD -timeframe M15,H1

# Update M1 and rebuild H1 in one command
update DUKASCOPY EURUSD H1

# Schedule EURUSD to update every hour
schedule add DUKASCOPY EURUSD M1 --interval 60

# Data quality report
quality DUKASCOPY EURUSD M1
```

## REST API

All endpoints (except `/` and `/health`) require the `X-API-Key` header.

| Method | Route | Description |
|---|---|---|
| `GET` | `/` | Dashboard stats (no auth) |
| `GET` | `/health` | Health check (no auth) |
| `POST` | `/download` | Download asset (background) |
| `POST` | `/update` | Update asset (background) |
| `POST` | `/resample` | Resample asset (background) |
| `POST` | `/rebuild` | Rebuild catalog from disk |
| `GET` | `/list` | List databases (paginated) |
| `GET` | `/info/{source}/{asset}/{tf}` | Database metadata |
| `GET` | `/search` | Search assets |
| `POST` | `/delete` | Delete database(s) |
| `GET` | `/data/{source}/{asset}/{tf}` | Download Parquet file |
| `GET` | `/data/{source}/{asset}/{tf}/stream` | Stream as CSV |
| `POST` | `/schedule` | Add scheduled job |
| `GET` | `/schedule` | List scheduled jobs |
| `DELETE` | `/schedule/{job_id}` | Remove scheduled job |

## Python Client

```python
from datamanager.client import DataManagerClient

client = DataManagerClient(base_url="http://localhost:8686", api_key="YOUR_KEY")

# Load into DataFrame (with optional timezone conversion)
df = client.get_data("DUKASCOPY", "EURUSD", "H1", timezone="America/Sao_Paulo")

# Save as CSV
client.get_data("DUKASCOPY", "EURUSD", "H1", save_path="eurusd_h1.csv", save_format="csv")

# Trigger a server-side download
client.download("DUKASCOPY", "EURUSD", start_date="2020-01-01", end_date="2026-01-01")

# Update and rebuild H1
client.update("DUKASCOPY", "EURUSD", timeframe="H1")
```

## Development

```bash
# Run unit tests (fast, no external deps)
uv run pytest

# Run integration tests (requires network / OpenBB)
uv run pytest tests/integration/

# Lint
uv run ruff check .

# Fix + format
uv run ruff check --fix . && uv run ruff format .
```

> **Tests:** Unit tests live in `tests/unit/` and run in under 10 seconds with no external services.
> Integration tests (`tests/integration/`) require OpenBB/network access and are excluded from the default run.

## Data Layout

```
database/
  {source}/
    {ASSET}/
      M1/data.parquet       ← source of truth
      H1/data.parquet       ← derived via resample
      .versions/M1/         ← automatic backups (up to 5)

metadata/
  catalog.db                ← SQLite (WAL), fast catalog reads
  scheduler_jobs.json       ← persisted scheduler jobs
  dukas_assets.csv          ← Dukascopy asset validation list
```
