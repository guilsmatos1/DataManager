# DataManager

## Overview
**DataManager** is a centralized service for fetching, storing, and managing financial OHLCV (Open, High, Low, Close, Volume) data and FRED economic series. Built on **Polylith architecture**, it uses **TimescaleDB (PostgreSQL)** with hypertables and continuous aggregates for efficient storage and querying of millions of records.

**Supported Data Sources:**
- **OpenBB** — Stocks, ETFs, and indices (via yfinance).
- **Dukascopy** — Forex, commodities, and indices.
- **CCXT** — Cryptocurrency across 100+ exchanges.
- **FRED** — Economic and macro series via OpenBB/FRED.

---

## Key Features
- **TimescaleDB Storage:** OHLCV data stored in a TimescaleDB hypertable (`ohlcv_m1`) with automatic time-based partitioning.
- **On-demand Continuous Aggregates:** Higher timeframes (M5, M15, H1, H4, D1) are created per user request via the `resample` command and materialized as TimescaleDB continuous aggregates.
- **Idempotent Downloads:** Supports chunked, resumable downloads with automatic deduplication logic (no data duplication).
- **Persistent Scheduler:** Cron and interval-based recurring updates are stored in SQLite, surviving service restarts.
- **REST API & Client:** A high-performance FastAPI server (port 8686) with a Python client (`DataManagerClient`) for seamless integration.
- **Parallel FRED Track:** Economic series are stored separately from OHLCV in `economic_series` and `economic_observations`, with dedicated API/CLI commands.

---

## Architecture (Polylith)
The project follows the **Polylith Architecture**, organized into:
- **Components:** Pure business logic (`trademachine.datamanager.*`).
- **Bases:** Entry points (`trademachine.datamanager_api`, `trademachine.datamanager_cli`).

### Directory Structure
```
components/datamanager/src/trademachine/datamanager/
├── infrastructure/
│   └── config.py       → Pydantic settings (env vars / .env loading)
├── db/
│   ├── database.py     → SQLAlchemy engine + session
│   ├── models.py       → SQLAlchemy ORM models (Source, Asset, OhlcvM1, EconomicSeries, EconomicObservation)
│   ├── series_storage.py → TimescaleDB I/O for FRED/economic series
│   ├── processor.py    → OHLCV gap filling (data quality)
│   └── storage.py      → StorageManager: TimescaleDB I/O + upsert logic
├── fetchers/
│   ├── base.py         → BaseFetcher ABC
│   ├── ccxt.py         → CCXT integration (crypto)
│   ├── dukascopy.py    → Dukascopy integration (forex, commodities)
│   ├── openbb.py       → OpenBB/YFinance integration (equities, ETFs)
│   └── fred.py         → OpenBB/FRED integration (economic series)
├── schemas/             → Pydantic request/response models for the REST API
├── services/
│   ├── manager.py      → DataManager: central orchestrator
│   ├── scheduler.py    → Background job scheduler (APScheduler)
│   └── series_manager.py → FRED/economic-series orchestrator
└── client.py           → Python HTTP client for the REST API

bases/datamanager_api/src/trademachine/datamanager_api/
└── router.py           → FastAPI REST API (port 8686)

bases/datamanager_cli/src/trademachine/datamanager_cli/
└── cli.py              → Interactive CLI shell

projects/datamanager/
├── pyproject.toml      → Project config + entry points
├── docker-compose.yml   → API deployment
└── alembic.ini         → DB migrations (TimescaleDB schema)
```

---

## Installation & Setup

Requires [uv](https://docs.astral.sh/uv/) and **TimescaleDB** (or PostgreSQL 14+ with TimescaleDB extension).

### 1. Synchronize Dependencies
```bash
uv sync --dev
```

### 2. Configure Environment
```bash
cp .env.example .env
```
Key variables:
- `DATABASE_URL`: PostgreSQL connection string with TimescaleDB (e.g., `postgresql://user:pass@localhost:5432/datamanager`).
- `DATAMANAGER_API_KEY`: Secret key for API authentication.
- `FRED_API_KEY`: Required for all FRED commands. Get a free key at https://fred.stlouisfed.org/docs/api/api_key.html.

### 3. Run Migrations
```bash
cd projects/datamanager && uv run alembic upgrade head
```

---

## Usage

### Interactive CLI
```bash
uv run datamanager -i
```

#### OHLCV Commands
```bash
# Download M1 data (base for all derived timeframes)
download dukascopy EURUSD 2020-01-01 2025-01-01

# Create a higher timeframe from M1 data (continuous aggregate)
resample dukascopy EURUSD H1

# Update M1 + refresh all existing resampled timeframes
update all

# Update a specific asset
update dukascopy EURUSD

# List all databases (OHLCV + FRED in one view)
list

# Data quality report
quality dukascopy EURUSD M1

# Search available assets
search --source dukascopy --query EUR
search --source ccxt --query BTC/USDT

# Schedule recurring updates
schedule add dukascopy EURUSD M1 --interval 60
schedule list
schedule remove <job_id>
```

#### Delete Behavior
```bash
# Remove an asset from ALL timeframes (M1 + all aggregates)
delete dukascopy EURUSD

# Wipe only the M1 rows (keeps the asset record)
delete dukascopy EURUSD M1

# Remove multiple assets at once
delete dukascopy EURUSD,USDJPY
```

> **Note:** Derived timeframes (H1, M15, etc.) are continuous aggregate views shared across all assets and **cannot be deleted per asset**. To remove an asset from all timeframes, omit the timeframe argument.

#### FRED / Economic Series Commands
```bash
# Search available series
search --source fred --query inflation

# Download a series
fred_download CPIAUCSL 2020-01-01 2025-01-01 --frequency m

# Update with overlap (captures historical revisions)
fred_update CPIAUCSL --lookback 30D

# Schedule recurring updates
schedule add-series CPIAUCSL --interval 720

# Delete a stored series
delete fred CPIAUCSL
```

### Server Mode (REST API)
```bash
uv run uvicorn trademachine.datamanager_api.router:app --host 0.0.0.0 --port 8686
```

---

## Resampling / Derived Timeframes

M1 is the **single source of truth**. Higher timeframes are never fetched directly from data providers — they are materialized from M1 via TimescaleDB continuous aggregates.

```
download → stores M1
resample → creates ohlcv_h1 view (all assets, one-time setup per timeframe)
update   → refreshes M1 + refreshes all continuous aggregates with data
```

- Running `resample` on an already-existing aggregate performs a **refresh** (not a no-op).
- Running `update all` **automatically refreshes** all resampled timeframes that have data.
- Continuous aggregates are global (per timeframe, not per asset). Deleting one asset does not affect others.

---

## Python Client
Integrate data directly into your scripts or notebooks:

```python
from trademachine.datamanager.client import DataManagerClient

client = DataManagerClient(base_url="http://localhost:8686", api_key="YOUR_KEY")

# Fetch OHLCV data as a Pandas DataFrame
df = client.get_data(
    source="dukascopy",
    asset="EURUSD",
    timeframe="H1",
    timezone="America/Sao_Paulo"
)

# Save as CSV locally
client.get_data("ccxt", "binance:BTC/USDT", "M1", save_path="btc.csv")

# FRED series
series = client.search_series(query="federal funds rate")
client.download_series("fred", "DFF", start_date="2024-01-01", end_date="2025-01-01")
fred_df = client.get_series_data("fred", "DFF")
```

---

## Testing & Quality
```bash
# Run the test suite
uv run pytest components/datamanager/test/

# Lint and Format
uv run ruff check --fix . && uv run ruff format .
```

---

## Database Schema (TimescaleDB)
- **Hypertable:** `ohlcv_m1` — partitioned by `timestamp`, stores raw 1-minute OHLCV data.
- **Continuous Aggregates:** created on demand via `resample` — e.g. `ohlcv_h1`, `ohlcv_m15`. Each view covers all assets for that timeframe.
- **Catalog Tables:** `sources` and `assets` — metadata for sources and ticker symbols with min/max date and row count.
- **FRED Tables:** `economic_series` and `economic_observations` — separate catalog and hypertable for macro series.
- **Migrations:** Alembic migrations in `alembic/versions/` create the OHLCV schema and FRED tables.

---

## REST API Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/` | GET | No | Dashboard and instance statistics |
| `/health` | GET | No | Health check |
| `/download` | POST | Yes | Download asset data (background) |
| `/update` | POST | Yes | Update existing database (background) |
| `/delete` | POST | Yes | Delete database(s) |
| `/list` | GET | Yes | List all databases (paginated) |
| `/info/{source}/{asset}/{timeframe}` | GET | Yes | Database metadata |
| `/search` | GET | Yes | Search assets by source/query |
| `/data/{source}/{asset}/{timeframe}` | GET | Yes | Download data as Parquet |
| `/data/{source}/{asset}/{timeframe}/stream` | GET | Yes | Stream data as CSV |
| `/series/search` | GET | Yes | Search FRED economic series |
| `/series/download` | POST | Yes | Download and save a FRED series |
| `/series/update` | POST | Yes | Update an existing FRED series |
| `/series/list` | GET | Yes | List stored FRED series |
| `/series/info/{source}/{series_id}` | GET | Yes | Metadata for a stored FRED series |
| `/series/data/{source}/{series_id}` | GET | Yes | Download FRED data as Parquet |
| `/series/delete` | POST | Yes | Delete a stored FRED series |
| `/schedule` | GET | Yes | List scheduled jobs |
| `/schedule` | POST | Yes | Create scheduled job |
| `/schedule/{job_id}` | DELETE | Yes | Remove scheduled job |
