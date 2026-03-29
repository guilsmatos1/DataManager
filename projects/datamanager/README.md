# DataManager

## Overview
**DataManager** is a centralized service for fetching, storing, and managing financial OHLCV (Open, High, Low, Close, Volume) data. Built on **Polylith architecture**, it uses **TimescaleDB (PostgreSQL)** with hypertables and continuous aggregates for efficient storage and querying of millions of records.

**Supported Data Sources:**
- **OpenBB** — Stocks, ETFs, and indices (via yfinance).
- **Dukascopy** — Forex, commodities, and indices.
- **CCXT** — Cryptocurrency across 100+ exchanges.

---

## Key Features
- **TimescaleDB Storage:** OHLCV data stored in a TimescaleDB hypertable (`ohlcv_m1`) with automatic time-based partitioning.
- **Continuous Aggregates:** Higher timeframes (M5, M15, H1, H4, D1) materialized as TimescaleDB continuous aggregates — zero-runtime-cost derived timeframes.
- **Idempotent Downloads:** Supports chunked, resumable downloads with automatic deduplication logic (no data duplication).
- **Persistent Scheduler:** Cron and interval-based recurring updates are stored in SQLite, surviving service restarts.
- **REST API & Client:** A high-performance FastAPI server (port 8686) with a Python client (`DataManagerClient`) for seamless integration.

---

## Architecture (Polylith)
The project follows the **Polylith Architecture**, organized into:
- **Components:** Pure business logic (`trademachine.datamanager.*`).
- **Bases:** Entry points (`trademachine.datamanager_api`, `trademachine.datamanager_cli`).

### Directory Structure
```
components/datamanager/src/trademachine/datamanager/
├── core/config.py       → Pydantic settings (env vars / .env loading)
├── db/
│   ├── database.py     → SQLAlchemy async engine + session
│   ├── models.py       → SQLAlchemy ORM models (Source, Asset, OhlcvM1)
│   ├── processor.py    → OHLCV gap filling (data quality)
│   └── storage.py      → StorageManager: TimescaleDB I/O + upsert logic
├── fetchers/
│   ├── base.py         → BaseFetcher ABC
│   ├── ccxt.py         → CCXT integration (crypto)
│   ├── dukascopy.py    → Dukascopy integration (forex, commodities)
│   └── openbb.py       → OpenBB/YFinance integration (equities, ETFs)
├── schemas/             → Pydantic request/response models for the REST API
├── services/
│   ├── manager.py      → DataManager: central orchestrator
│   └── scheduler.py    → Background job scheduler (APScheduler)
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

### 3. Run Migrations
```bash
uv run alembic upgrade head
```

---

## Usage

### Interactive CLI
```bash
uv run datamanager -i
```
Inside the CLI:
```bash
# Download data (auto-idempotent)
download dukascopy EURUSD 2020-01-01 2025-01-01

# Search for available assets
search --source ccxt --query BTC/USDT

# Schedule recurring updates
schedule add dukascopy EURUSD M1 --interval 60

# Data quality report
quality dukascopy EURUSD M1
```

### Server Mode (REST API)
```bash
uv run uvicorn trademachine.datamanager_api.router:app --host 0.0.0.0 --port 8686
```

---

## Python Client
Integrate data directly into your scripts or notebooks:

```python
from trademachine.datamanager.client import DataManagerClient

client = DataManagerClient(base_url="http://localhost:8686", api_key="YOUR_KEY")

# Fetch data as a Pandas DataFrame
df = client.get_data(
    source="dukascopy",
    asset="EURUSD",
    timeframe="H1",
    timezone="America/Sao_Paulo"
)

# Save as CSV locally
client.get_data("ccxt", "binance:BTC/USDT", "M1", save_path="btc.csv")
```

---

## Testing & Quality
```bash
# Run the test suite
uv run pytest components/datamanager/test/

# Lint and Format
uv run ruff check --fix . && uv run ruff format .

# Type Checking
uv run mypy components/datamanager/src/
```

---

## Database Schema (TimescaleDB)
- **Hypertable:** `ohlcv_m1` — partitioned by `timestamp`, stores raw 1-minute OHLCV data.
- **Continuous Aggregates:** `ohlcv_m5`, `ohlcv_m15`, `ohlcv_h1`, `ohlcv_h4`, `ohlcv_d1` — automatically refreshed materialized views.
- **Catalog Tables:** `sources` and `assets` — metadata for sources and ticker symbols.
- **Migrations:** Alembic migrations in `alembic/versions/` create the hypertable and continuous aggregates.
