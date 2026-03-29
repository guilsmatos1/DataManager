# DataManager — Codebase Technical Documentation

> **Version:** v0.1.0
> **Python:** 3.12
> **Purpose:** Tool for downloading, storing, and managing OHLCV (Open, High, Low, Close, Volume) data of financial assets, with support for multiple data sources, timeframe resampling, and a network API.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Directory Structure](#2-directory-structure)
3. [Modules and Files](#3-modules-and-files)
   - [cli.py](#31-basedatamanager_cliclipy--command-line-interface)
   - [services/manager.py](#32-componentsdatamanager/servicesmanagerpy--central-controller)
   - [services/scheduler.py](#33-componentsdatamanager/servicesschedulerpy--background-job-manager)
   - [core/config.py](#34-componentsdatamanagercoreconfigpy--centralized-settings)
   - [db/storage.py](#35-componentsdatamanagerdbstoragepy--persistence-layer)
   - [db/processor.py](#36-componentsdatamanagerdbprocessorpy--timeframe-resampling)
   - [fetchers/](#37-componentsdatamanagerfetchers--data-integration)
   - [fetchers/dukascopy.py](#38-componentsdatamanagerfetchersdukascopypy--forex--commodities)
   - [fetchers/openbb.py](#39-componentsdatamanagerfetchersopenbbpy--stocks--etfs)
   - [api/router.py](#310-basesdatamanager_apirouterpy--fastapi-rest-api)
   - [schemas/](#311-componentsdatamanagerschemas--data-validation)
   - [client.py](#312-componentsdatamanagerclientpy--python-client-for-the-api)
4. [Data Flow](#4-data-flow)
5. [Storage System](#5-storage-system)
6. [Metadata Catalog](#6-metadata-catalog)
7. [Supported Data Sources](#7-supported-data-sources)
8. [Supported Timeframes](#8-supported-timeframes)
9. [API Security](#9-api-security)
10. [Docker Deployment](#10-docker-deployment)
11. [Main Dependencies](#11-main-dependencies)
12. [CLI Command Reference](#12-cli-command-reference)
13. [REST API Reference](#13-rest-api-reference)

---

## 1. Architecture Overview

DataManager follows **Polylith Architecture** with three layers: components (business logic), bases (entry points), and projects (build configs). The CLI and API are **independent entry points** that share the same `DataManager` orchestrator component.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        POLYLITH LAYERS                              │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │                        BASES (Entry Points)                  │ │
│  │  ┌───────────────────────┐       ┌─────────────────────────┐  │ │
│  │  │  datamanager_cli     │       │   datamanager_api      │  │ │
│  │  │  DataManagerCLI      │       │   FastAPI REST API     │  │ │
│  │  │  (cmd.Cmd shell)     │       │   (port 8686)           │  │ │
│  │  └──────────┬──────────┘       └────────────┬────────────┘  │ │
│  └─────────────┼────────────────────────────────┼──────────────┘ │
│                │                                │                  │
│  ┌─────────────▼────────────────────────────────▼──────────────┐  │
│  │              COMPONENTS (shared business logic)              │  │
│  │                                                               │  │
│  │   ┌─────────────────────────────────────────────────────┐   │  │
│  │   │              trademachine.datamanager                │   │  │
│  │   │  ┌──────────┐  ┌──────────┐  ┌────────────┐        │   │  │
│  │   │  │ Fetchers │  │ Storage  │  │ Processor  │        │   │  │
│  │   │  │ Dukascopy│  │ Manager  │  │ Resample   │        │   │  │
│  │   │  │ OpenBB   │  │          │  │            │        │   │  │
│  │   │  │ CCXT     │  │          │  │            │        │   │  │
│  │   │  └──────────┘  └──────────┘  └────────────┘        │   │  │
│  │   └─────────────────────────────────────────────────────┘   │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

**Fundamental Principle:** All data is always downloaded and stored in **M1 (1 minute)** first. Higher timeframes (H1, D1, etc.) are generated via **resampling** from the base M1 data.

---

## 2. Directory Structure

DataManager uses **Polylith Architecture** with three directory types:

- **`components/`** — Reusable business logic (no base dependencies)
- **`bases/`** — Entry points (CLI, API)
- **`projects/`** — Build configurations combining bases + components

```
projects/datamanager/          # This Polylith project (build config)
│
├── pyproject.toml             # Project config: dependencies, entry points (uv)
├── uv.lock                    # Locked dependency versions (managed by uv)
├── Dockerfile                 # Application Docker image (uses uv)
├── docker-compose.yml         # Deployment configuration (API mode)
├── .env.example               # Environment variables example
│
├── alembic/                   # Database migrations
│   ├── alembic.ini            # Alembic configuration
│   └── versions/              # Migration scripts (TimescaleDB schema)
└── metadata/
    └── dukas_assets.csv        # List of ~3,000 valid Dukascopy assets

# Polylith workspace (at workspace root — outside projects/datamanager/)
components/datamanager/src/trademachine/datamanager/
│   ├── client.py              # Python client for consuming the API
│   ├── core/config.py         # Pydantic Settings (env vars / .env)
│   ├── db/
│   │   ├── database.py        # SQLAlchemy async engine + session
│   │   ├── models.py          # ORM models (OHLCV, assets, sources)
│   │   ├── processor.py       # DataProcessor: OHLCV resampling + Gap filling
│   │   └── storage.py         # StorageManager: TimescaleDB I/O (hypertable + upsert)
│   ├── fetchers/
│   │   ├── base.py            # BaseFetcher: abstract interface (ABC)
│   │   ├── ccxt.py            # CCXT (crypto, 100+ exchanges)
│   │   ├── dukascopy.py       # Dukascopy integration (forex, commodities)
│   │   └── openbb.py          # OpenBB/YFinance (stocks, ETFs)
│   ├── schemas/               # Pydantic request/response models
│   └── services/
│       ├── manager.py        # DataManager: central orchestrator
│       └── scheduler.py      # SchedulerService: APScheduler jobs (persisted to TimescaleDB)

bases/datamanager_api/src/trademachine/datamanager_api/
└── router.py                  # FastAPI REST API (port 8686)

bases/datamanager_cli/src/trademachine/datamanager_cli/
└── cli.py                     # Interactive CLI shell (cmd.Cmd)
```

---

## 3. Modules and Files

### 3.1 `bases/datamanager_cli/cli.py` — Command Line Interface

**Responsibility:** Defines all commands available to the user using Python stdlib's `cmd.Cmd`.

**Class:** `DataManagerCLI(cmd.Cmd)`

**Internally Instantiates:** `DataManager` (from `components/datamanager/src/trademachine/datamanager/services/manager.py`)

#### Available Commands:

| Method | Command | Description |
|--------|---------|-------------|
| `do_download` | `download` | Downloads new data for one or more assets |
| `do_update` | `update` | Updates existing databases with recent data (or `update all`) |
| `do_delete` | `delete` | Removes databases from disk (or `delete all`) |
| `do_info` | `info` | Displays metadata for a specific database |
| `do_list` | `list` | Lists all saved databases in a formatted table |
| `do_search` | `search` | Searches for available assets in sources |
| `do_quality` | `quality` | Data integrity report |
| `do_schedule` | `schedule` | Manages background update jobs |
| `do_exit` / `do_quit` | `exit` / `quit` | Exits the program |

---

### 3.2 `components/datamanager/.../services/manager.py` — Central Controller

**Responsibility:** Orchestrates all business operations, coordinating Fetchers, Storage, and Processor.

**Path:** `components/datamanager/src/trademachine/datamanager/services/manager.py`

**Class:** `DataManager`

#### Initialization:
```python
self.storage = StorageManager()
self.processor = DataProcessor()
self._fetchers = get_all_fetchers()  # auto-discovered via pkgutil
```

#### Main Methods:

**`download_data(source, asset, start_date, end_date)`**
- Yearly chunking to minimize memory consumption.
- Progress tracked via `tqdm`.
- Saves via `storage.save_data()` in `M1`.

**`update_data(source, asset, timeframe="M1")`**
- Downloads only new data from `last_date` to `now`.
- Uses `storage.append_data()` to concatenate without duplicates.

---

### 3.3 `components/datamanager/.../services/scheduler.py` — Background Job Manager

**Responsibility:** Manages recurring data update tasks using APScheduler.

**Features:**
- Supports **Cron** expressions (5 fields) and **Intervals** (minutes).
- Jobs run in background daemon threads.
- Jobs are **persisted to TimescaleDB** via SQLAlchemyJobStore, surviving service restarts.

---

### 3.4 `components/datamanager/.../core/config.py` — Centralized Settings

**Path:** `components/datamanager/src/trademachine/datamanager/core/config.py`

**Responsibility:** Manages application configuration via Pydantic Settings.

**Settings:**
- `api_key`: Secret for REST API authentication (`DATAMANAGER_API_KEY`).
- `host` / `port`: Network server configuration.
- Loads from `.env` file automatically.

---

### 3.5 `components/datamanager/.../db/storage.py` — Persistence Layer

**Path:** `components/datamanager/src/trademachine/datamanager/db/storage.py`

**Responsibility:** TimescaleDB I/O, hypertable management, and continuous aggregate queries.

**Class:** `StorageManager`

#### TimescaleDB Architecture:
- **Hypertable:** `ohlcv_m1` — partitioned by `timestamp`, stores raw M1 OHLCV data.
- **Continuous Aggregates:** `ohlcv_m5`, `ohlcv_m15`, `ohlcv_h1`, `ohlcv_h4`, `ohlcv_d1` — automatically refreshed materialized views.
- **Upsert Logic:** Uses PostgreSQL `ON CONFLICT DO UPDATE` to avoid duplicates.
- **Batch Inserts:** Saves in batches of 5,000 rows to stay under PostgreSQL's parameter limit.

#### Catalog Tables:
- **`sources`**: Data source names (Dukascopy, CCXT, OpenBB).
- **`assets`**: Ticker symbols per source with `min_date`, `max_date`, `row_count`.

---

### 3.6 `components/datamanager/.../db/processor.py` — Timeframe Resampling & Gap Filling

**Path:** `components/datamanager/src/trademachine/datamanager/db/processor.py`

**Responsibility:** Converts OHLCV timeframes and repairs data gaps.

**Class:** `DataProcessor`

#### Gap Filling:
**`fill_gaps(df, timeframe, method="ffill")`**
- **`ffill`**: Forward-fills prices, zero-fills volume (default).
- **`drop`**: Removes rows with missing data.
- **`none`**: Reindexes with NaN.

---

### 3.7 `components/datamanager/.../fetchers/` — Data Integration

**Path:** `components/datamanager/src/trademachine/datamanager/fetchers/`

**`CcxtFetcher`:**
- Support for 100+ crypto exchanges via `ccxt` library.
- Syntax: `exchange:SYMBOL` (e.g., `binance:BTC/USDT`). Defaults to binance.
- Automatically handles rate limits and chunked OHLCV fetching.

**BaseFetcher**:
- Abstract base class defining `fetch_data` and `search` interfaces.

---

### 3.8 `components/datamanager/.../fetchers/dukascopy.py` — Forex & Commodities

**Path:** `components/datamanager/src/trademachine/datamanager/fetchers/dukascopy.py`

**Responsibility:** Interface with the `dukascopy-python` library.

- Downloads tick-level data and aggregates to M1.
- Supports ~3,000 assets (defined in `metadata/dukas_assets.csv`).
- Reliable source for long-term Forex history.

---

### 3.9 `components/datamanager/.../fetchers/openbb.py` — Stocks & ETFs

**Path:** `components/datamanager/src/trademachine/datamanager/fetchers/openbb.py`

**Responsibility:** Interface with the `OpenBB` platform.

- Uses `yfinance` as the primary backend for M1 data.
- Supports major global stock exchanges and ETFs.
- Note: M1 history for stocks is typically limited to the last 7-30 days by the provider.

---

### 3.10 `bases/datamanager_api/.../router.py` — REST API (FastAPI)

**Path:** `bases/datamanager_api/src/trademachine/datamanager_api/router.py`

**Responsibility:** Exposes functionalities via HTTP with enhanced security and performance.

#### Features:
- **Dashboard (`GET /`)**: Overview of instance status and storage statistics.
- **Health Check (`GET /health`)**: Basic connectivity and database count.
- **Asset Search (`GET /search`)**: Discover available assets via source/query/exchange.
- **Data Management**: API endpoints for `/download`, `/update`, and `/delete`.
- **Automated Scheduling**: REST interface for managing recurring update tasks (`/schedule`).
- **Rate Limiting**: Sliding window protection (60 requests per 60 seconds per IP).
- **Background Tasks**: Long-running operations (download, update) are offloaded to avoid blocking the server.

---

### 3.11 `components/datamanager/.../schemas/` — Data Validation

**Path:** `components/datamanager/src/trademachine/datamanager/schemas/`

**Responsibility:** Defines Pydantic models for structured API communication.

- Ensures all incoming requests have valid data types.
- Provides consistent error messages for invalid API calls.

---

### 3.12 `components/datamanager/.../client.py` — Python Client for the API

**Path:** `components/datamanager/src/trademachine/datamanager/client.py`

**Responsibility:** High-level library to consume the REST API from other Python applications.

**Class:** `DataManagerClient`

- Handles authentication (`X-API-Key`).
- Provides methods for downloading data directly to Pandas DataFrames.
- Includes automatic timezone conversion.

---

## 4. Data Flow

1. **Request:** User triggers a command (CLI) or endpoint (API).
2. **Orchestration:** `DataManager` service identifies the required `Fetcher`.
3. **Fetching:** `Fetcher` downloads `M1` data in chunks from the provider.
4. **Storage:** `StorageManager` upserts data into the `ohlcv_m1` hypertable (batch inserts).
5. **Post-processing:** TimescaleDB automatically refreshes continuous aggregates (M5, M15, H1, H4, D1). Other timeframes are derived via `DataProcessor.resample_ohlc()` on read.

---

## 5. Storage System

### TimescaleDB Schema:
```
TimescaleDB (PostgreSQL)
  ├── ohlcv_m1        — Hypertable: raw 1-minute OHLCV (primary write target)
  ├── ohlcv_m5        — Continuous aggregate: 5-minute OHLCV
  ├── ohlcv_m15       — Continuous aggregate: 15-minute OHLCV
  ├── ohlcv_h1        — Continuous aggregate: 1-hour OHLCV
  ├── ohlcv_h4        — Continuous aggregate: 4-hour OHLCV
  ├── ohlcv_d1        — Continuous aggregate: 1-day OHLCV
  ├── sources         — Catalog: data source names
  └── assets         — Catalog: tickers per source with min/max/row_count
```

---

## 6. Database Catalog

Asset metadata (sources, tickers, date ranges, row counts) is stored in SQL tables:
- **`sources`**: Source name (Dukascopy, CCXT, OpenBB).
- **`assets`**: Ticker, `source_id`, `min_date`, `max_date`, `row_count`.

Use `update all` CLI command to recalculate asset statistics after bulk loads.

---

## 7. Supported Data Sources

| Source | Library | Markets | Notes |
|--------|---------|---------|-------|
| `DUKASCOPY` | `dukascopy-python` | Forex, Commodities | High quality, full history. |
| `OPENBB` | `openbb` | Stocks, ETFs, Crypto | Uses yfinance proxy for M1. |
| `CCXT` | `ccxt` | Crypto | Supports multi-exchange prefix. |

---

## 8. Supported Timeframes

**TimescaleDB native (continuous aggregates):** `M1` (hypertable), `M5`, `M15`, `H1`, `H4`, `D1`.

**Derived via resampling (DataProcessor.resample_ohlc):** `M2`, `M10`, `M30`, `H2`, `H3`, `H6`, `W1`.

Mapping to pandas resample strings is defined in `DataProcessor.TF_MAPPING`.

| Timeframe | Rule | Type |
|-----------|------|------|
| M1 | 1min | Native (hypertable) |
| M2 | 2min | Resampled |
| M5 | 5min | Native (continuous aggregate) |
| M10 | 10min | Resampled |
| M15 | 15min | Native (continuous aggregate) |
| M30 | 30min | Resampled |
| H1 | 1h | Native (continuous aggregate) |
| H2 | 2h | Resampled |
| H3 | 3h | Resampled |
| H4 | 4h | Native (continuous aggregate) |
| H6 | 6h | Resampled |
| D1 | D | Native (continuous aggregate) |
| W1 | W | Resampled |

---

## 9. API Security

1. **API Key Authentication:** Requires `X-API-Key` header matching `DATAMANAGER_API_KEY`.
2. **Rate Limiting:** Sliding window protection (60 req/min) per source IP.
3. **Input Validation:** Strict Pydantic models for all request bodies and path parameters.

---

## 10. Docker Deployment

- **Base Image:** `python:3.12-slim`.
- **Package Manager:** `uv` (installs from `uv.lock`).
- **Volumes:** Only `./metadata` (for `dukas_assets.csv`) needs to be persisted. TimescaleDB data lives in the database container.

---

## 11. Main Dependencies

- **FastAPI / Uvicorn**: Web server.
- **SQLAlchemy / TimescaleDB**: ORM and time-series database.
- **APScheduler**: Background task scheduling.
- **ccxt / openbb / dukascopy-python**: Data providers.
- **Pydantic / Pydantic-Settings**: Validation and configuration.

---

## 12. CLI Command Reference

| Command | Usage Example |
|---------|---------------|
| `download` | `download CCXT binance:BTC/USDT 2024-01-01 2024-12-31` |
| `update` | `update DUKASCOPY EURUSD M1` |
| `update all` | `update all` (updates all M1s and rebuilds higher TFs) |
| `delete` | `delete DUKASCOPY EURUSD M1` |
| `delete all` | `delete all` (deletes all databases after confirmation) |
| `info` | `info DUKASCOPY EURUSD M1` |
| `list` | `list` |
| `search` | `search --source dukascopy --query gold` |
| `quality` | `quality DUKASCOPY EURUSD M1` |
| `schedule add` | `schedule add DUKASCOPY EURUSD M1 --interval 60` |
| `schedule list` | `schedule list` |
| `schedule remove` | `schedule remove <job_id>` |

---

## 13. REST API Reference

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/` | `GET` | No | Dashboard and instance statistics |
| `/health` | `GET` | No | Basic instance health check |
| `/list` | `GET` | Yes | List all databases (with pagination) |
| `/info/{source}/{asset}/{timeframe}` | `GET` | Yes | Metadata for a specific database |
| `/search` | `GET` | Yes | Search for assets in OpenBB, Dukascopy, or CCXT |
| `/download` | `POST` | Yes | Trigger a background download task |
| `/update` | `POST` | Yes | Trigger a background update task |
| `/delete` | `POST` | Yes | Delete specific or all databases |
| `/data/{source}/{asset}/{timeframe}` | `GET` | Yes | Download data as Parquet |
| `/data/{source}/{asset}/{timeframe}/stream` | `GET` | Yes | Stream data as CSV |
| `/schedule` | `GET` | Yes | List all active scheduled jobs |
| `/schedule` | `POST` | Yes | Create a new recurring update job |
| `/schedule/{job_id}` | `DELETE` | Yes | Remove a scheduled job by its ID |
