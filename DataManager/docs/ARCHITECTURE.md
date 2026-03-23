# DataManager — Codebase Technical Documentation

> **Version:** v1.2.0
> **Python:** 3.12
> **Purpose:** Tool for downloading, storing, and managing OHLCV (Open, High, Low, Close, Volume) data of financial assets, with support for multiple data sources, timeframe resampling, and a network API.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Directory Structure](#2-directory-structure)
3. [Modules and Files](#3-modules-and-files)
   - [main.py](#31-mainpy--entry-point)
   - [cli.py](#32-clipy--command-line-interface)
   - [services/manager.py](#33-servicesmanagerpy--central-controller)
   - [services/scheduler.py](#34-servicesschedulerpy--background-job-manager)
   - [core/config.py](#35-coreconfigpy--centralized-settings)
   - [db/storage.py](#36-dbstoragepy--persistence-layer)
   - [db/processor.py](#37-dbprocessorpy--timeframe-resampling)
   - [fetchers/base.py](#38-fetchersbasepy--abstract-interface)
   - [fetchers/dukascopy.py](#39-fetchersdukascopypy)
   - [fetchers/openbb.py](#310-fetchersopenbbpy)
   - [api/router.py](#311-apirouterpy--fastapi-rest-api)
   - [schemas/](#312-schemas--data-validation)
   - [client.py](#313-clientpy--python-client-for-the-api)
   - [utils/logger.py](#314-utilsloggerpy--centralized-logging)
   - [utils/retry.py](#315-utilsretrypy--exponential-backoff)
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

DataManager has **two independent operation modes** that share the same core (`services/manager.py`):

```
┌─────────────────────────────────────────────────────────────┐
│                        USAGE MODES                          │
│                                                             │
│  ┌──────────────────┐          ┌──────────────────────────┐ │
│  │    Local CLI     │          │    REST API (FastAPI)    │ │
│  │    main.py       │          │    api/router.py         │ │
│  │    cli.py        │          │    client.py             │ │
│  └────────┬─────────┘          └──────────┬───────────────┘ │
│           │                               │                  │
│           └──────────────┬────────────────┘                  │
│                          ▼                                   │
│               ┌─────────────────────────┐                   │
│               │   services/manager.py   │                   │
│               │       DataManager       │                   │
│               └────────┬────────────────┘                   │
│                        │                                     │
│         ┌──────────────┼──────────────┐                      │
│         ▼              ▼              ▼                      │
│  ┌─────────────┐ ┌──────────┐ ┌────────────┐                │
│  │  Fetchers   │ │ Storage  │ │ Processor  │                │
│  │ (Dukascopy) │ │ Manager  │ │ (Resample) │                │
│  │ (OpenBB)    │ │          │ │            │                │
│  └─────────────┘ └──────────┘ └────────────┘                │
└─────────────────────────────────────────────────────────────┘
```

**Fundamental Principle:** All data is always downloaded and stored in **M1 (1 minute)** first. Higher timeframes (H1, D1, etc.) are generated via **resampling** from the base M1 data.

---

## 2. Directory Structure

```
DataManager/
│
├── pyproject.toml             # Project config: dependencies, build, ruff, pytest
├── uv.lock                    # Locked dependency versions (managed by uv)
├── Dockerfile                 # Application Docker image (uses uv)
├── docker-compose.yml         # Deployment configuration (API mode)
├── .env.example               # Environment variables example
│
├── src/
│   └── datamanager/           # Main package (src layout)
│       ├── main.py            # Application entry point (CLI)
│       ├── cli.py             # Interactive command interface (cmd.Cmd)
│       ├── client.py          # Python client for consuming the API
│       │
│       ├── api/
│       │   └── router.py      # FastAPI HTTP server (API mode, port 8686)
│       │
│       ├── core/
│       │   └── config.py      # Pydantic Settings (env vars / .env loading)
│       │
│       ├── db/
│       │   ├── storage.py     # StorageManager: Parquet read/write + SQLite catalog + Versioning
│       │   └── processor.py   # DataProcessor: OHLCV resampling + Gap filling
│       │
│       ├── fetchers/
│       │   ├── __init__.py    # Auto-discovery of fetcher classes via pkgutil
│       │   ├── base.py        # BaseFetcher: abstract interface (ABC)
│       │   ├── dukascopy.py   # Integration with dukascopy-python
│       │   ├── openbb.py      # Integration with OpenBB (yfinance as backend)
│       │   └── ccxt.py        # Crypto support across multiple exchanges
│       │
│       ├── schemas/
│       │   └── __init__.py    # Pydantic models for the API
│       │
│       ├── services/
│       │   ├── manager.py     # DataManager: central logic controller
│       │   └── scheduler.py   # SchedulerService: background job manager
│       │
│       └── utils/
│           ├── logger.py      # Structured logging (Console + JSON)
│           └── retry.py       # Exponential backoff retry logic
│
├── tests/
│   ├── conftest.py            # Shared pytest fixtures
│   └── unit/                  # Isolated unit tests
│
├── metadata/
│   ├── catalog.db             # SQLite index of all saved databases (WAL mode)
│   └── dukas_assets.csv       # List of ~3,000 valid Dukascopy assets
│
└── database/
    ├── .versions/             # Timestamped backups for asset recovery
    └── {source}/
        └── {ASSET}/
            └── {TIMEFRAME}/
                └── data.parquet   # OHLCV data file
```

---

## 3. Modules and Files

### 3.1 `main.py` — Entry Point

**Responsibility:** Parses command-line arguments and decides the execution mode.

**Logic:**
- `uv run datamanager -i` → Opens the interactive shell (`cli.cmdloop()`)
- `uv run datamanager download DUKASCOPY EURUSD` → Executes a command directly (`cli.onecmd()`)
- `uv run datamanager` (no arguments) → Displays argparse help

**Special Handling:** `KeyboardInterrupt` (Ctrl+C) is caught globally and exits with `sys.exit(0)`.

---

### 3.2 `cli.py` — Command Line Interface

**Responsibility:** Defines all commands available to the user using Python stdlib's `cmd.Cmd`.

**Class:** `DataManagerCLI(cmd.Cmd)`

**Internally Instantiates:** `DataManager` (from `services/manager.py`)

#### Available Commands:

| Method | Command | Description |
|--------|---------|-------------|
| `do_download` | `download` | Downloads new data for one or more assets |
| `do_update` | `update` | Updates existing databases with recent data |
| `do_delete` | `delete` | Removes databases from disk |
| `do_info` | `info` | Displays metadata for a specific database |
| `do_list` | `list` | Lists all saved databases in a formatted table |
| `do_rebuild` | `rebuild` | Rebuilds the SQLite `catalog.db` by scanning the disk |
| `do_search` | `search` | Searches for available assets in sources |
| `do_resample` | `resample` | Converts M1 to other timeframes |
| `do_quality` | `quality` | Data integrity report |
| `do_schedule` | `schedule` | Manages background update jobs |
| `do_exit` / `do_quit` | `exit` / `quit` | Exits the program |

---

### 3.3 `services/manager.py` — Central Controller

**Responsibility:** Orchestrates all business operations, coordinating Fetchers, Storage, and Processor.

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

### 3.4 `services/scheduler.py` — Background Job Manager

**Responsibility:** Manages recurring data update tasks using APScheduler.

**Features:**
- Supports **Cron** expressions (5 fields) and **Intervals** (minutes).
- Jobs run in background daemon threads.
- In-memory job storage (does not persist across restarts).

---

### 3.5 `core/config.py` — Centralized Settings

**Responsibility:** Manages application configuration via Pydantic Settings.

**Settings:**
- `api_key`: Secret for REST API authentication (`DATAMANAGER_API_KEY`).
- `host` / `port`: Network server configuration.
- Loads from `.env` file automatically.

---

### 3.6 `db/storage.py` — Persistence Layer

**Responsibility:** Parquet I/O, SQLite catalog management, and data versioning.

**Class:** `StorageManager`

#### Concurrency & Safety:
- **File Locking:** Sidecar `.lock` files with platform-specific locking.
- **Atomic Writes:** Saves to `.tmp.parquet` before atomic rename.
- **SQLite Catalog:** Replaces `catalog.json` with `catalog.db` using WAL mode for concurrent read/write.

#### Data Versioning:
- **Automatic Backups:** Every `save_data` call creates a timestamped backup in `database/.versions/`.
- **Rotation:** Keeps the last 5 versions for each asset/timeframe combination.
- **Restoration:** Supports restoring the latest or a specific version (internal method).

---

### 3.7 `db/processor.py` — Timeframe Resampling & Gap Filling

**Responsibility:** Converts OHLCV timeframes and repairs data gaps.

**Class:** `DataProcessor`

#### Gap Filling:
**`fill_gaps(df, timeframe, method="ffill")`**
- **`ffill`**: Forward-fills prices, zero-fills volume (default).
- **`drop`**: Removes rows with missing data.
- **`none`**: Reindexes with NaN.

---

### 3.8 `fetchers/` — Data Integration

**`CcxtFetcher` (new):**
- Support for 100+ crypto exchanges via `ccxt` library.
- Syntax: `exchange:SYMBOL` (e.g., `binance:BTC/USDT`). Defaults to binance.
- Automatically handles rate limits and chunked OHLCV fetching.

**BaseFetcher**:
- Abstract base class defining `fetch_data` and `search` interfaces.

---

### 3.9 `fetchers/dukascopy.py` — Forex & Commodities

**Responsibility:** Interface with the `dukascopy-python` library.

- Downloads tick-level data and aggregates to M1.
- Supports ~3,000 assets (defined in `metadata/dukas_assets.csv`).
- Reliable source for long-term Forex history.

---

### 3.10 `fetchers/openbb.py` — Stocks & ETFs

**Responsibility:** Interface with the `OpenBB` platform.

- Uses `yfinance` as the primary backend for M1 data.
- Supports major global stock exchanges and ETFs.
- Note: M1 history for stocks is typically limited to the last 7-30 days by the provider.

---

### 3.11 `api/router.py` — REST API (FastAPI)

**Responsibility:** Exposes functionalities via HTTP with enhanced security and performance.

#### Features:
- **Dashboard (`GET /`)**: Overview of instance status and storage statistics.
- **Health Check (`GET /health`)**: Basic connectivity and database count.
- **Asset Search (`GET /search`)**: Discover available assets via source/query/exchange.
- **Data Management**: API endpoints for `/download`, `/update`, `/resample`, and `/delete`.
- **Flexible Retrieval**: 
  - `GET /data/...`: Download the full Parquet file.
  - `GET /data/.../stream`: High-performance line-by-line CSV streaming.
- **Automated Scheduling**: REST interface for managing recurring update tasks (`/schedule`).
- **Rate Limiting**: Sliding window protection (60 requests per 60 seconds per IP).
- **Background Tasks**: Long-running operations (download, update, resample) are offloaded to avoid blocking the server.

---

### 3.12 `schemas/` — Data Validation

**Responsibility:** Defines Pydantic models for structured API communication.

- Ensures all incoming requests have valid data types.
- Provides consistent error messages for invalid API calls.

---

### 3.13 `client.py` — Python Client for the API

**Responsibility:** High-level library to consume the REST API from other Python applications.

**Class:** `DataManagerClient`

- Handles authentication (`X-API-Key`).
- Provides methods for downloading data directly to Pandas DataFrames.
- Includes automatic timezone conversion.

---

### 3.14 `utils/logger.py` — Centralized Logging

**Responsibility:** Standardizes output across CLI and API.

- **Console:** Colorized, human-readable logs.
- **File (`log.log`):** Structured JSON logs for machine analysis and persistence.

---

### 3.15 `utils/retry.py` — Exponential Backoff

**Responsibility:** Ensures network resiliency.

- Utility function `with_retry` used by Fetchers.
- Default: 3 attempts with increasing delays (1s, 2s, 4s).

---

## 4. Data Flow

1. **Request:** User triggers a command (CLI) or endpoint (API).
2. **Orchestration:** `DataManager` service identifies the required `Fetcher`.
3. **Fetching:** `Fetcher` downloads `M1` data in chunks from the provider.
4. **Storage:** `StorageManager` saves/appends data as `.parquet` and updates the SQLite catalog.
5. **Post-processing:** If a higher timeframe was requested, `DataProcessor` resamples the `M1` file.

---

## 5. Storage System

### Directory Hierarchy:
```
database/
  .versions/                 # Internal: storage for backups
  {source}/
    {ASSET}/
      {TIMEFRAME}/
        data.parquet         # Fastparquet engine
```

---

## 6. Metadata Catalog (SQLite)

**File:** `metadata/catalog.db`

The catalog uses SQLite with **WAL (Write-Ahead Logging)** mode.
- Table: `catalog` (source, asset, timeframe, rows, start_date, end_date, file_size_kb).
- Primary Key: `(source, asset, timeframe)`.

---

## 7. Supported Data Sources

| Source | Library | Markets | Notes |
|--------|---------|---------|-------|
| `DUKASCOPY` | `dukascopy-python` | Forex, Commodities | High quality, full history. |
| `OPENBB` | `openbb` | Stocks, ETFs, Crypto | Uses yfinance proxy for M1. |
| `CCXT` | `ccxt` | Crypto | Supports multi-exchange prefix. |

---

## 8. Supported Timeframes

Standard OHLCV resampling rules:
- **Intraday:** `M1` (base), `M2`, `M5`, `M10`, `M15`, `M30`.
- **Hourly:** `H1`, `H2`, `H3`, `H4`, `H6`.
- **Daily/Weekly:** `D1`, `W1`.

---

## 9. API Security

1. **API Key Authentication:** Requires `X-API-Key` header matching `DATAMANAGER_API_KEY`.
2. **Rate Limiting:** Sliding window protection (60 req/min) per source IP.
3. **Input Validation:** Strict Pydantic models for all request bodies and path parameters.

---

## 10. Docker Deployment

- **Base Image:** `python:3.12-slim`.
- **Package Manager:** `uv` (installs from `uv.lock`).
- **Volumes:** `./database` and `./metadata` should be persisted for data durability.

---

## 11. Main Dependencies

- **FastAPI / Uvicorn**: Web server.
- **Pandas / Fastparquet**: Data processing and storage.
- **APScheduler**: Background task scheduling.
- **ccxt / openbb / dukascopy-python**: Data providers.
- **Pydantic / Pydantic-Settings**: Validation and configuration.

---

## 12. CLI Command Reference

| Command | Usage Example |
|---------|---------------|
| `download` | `download CCXT binance:BTC/USDT 2024-01-01` |
| `update` | `update DUKASCOPY EURUSD M1` |
| `resample` | `resample OPENBB AAPL H1` |
| `search` | `search --source dukascopy --query gold` |
| `list` | `list` |
| `schedule` | `schedule add CCXT BTC/USDT --interval 60` |
| `quality` | `quality DUKASCOPY EURUSD M1` |

---

## 13. REST API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | `GET` | Dashboard and instance statistics |
| `/health` | `GET` | Basic instance health check |
| `/list` | `GET` | List all databases (with pagination) |
| `/info/{s}/{a}/{t}` | `GET` | Metadata for a specific database |
| `/search` | `GET` | Search for assets in OpenBB, Dukascopy, or CCXT |
| `/download` | `POST` | Trigger a background download task |
| `/update` | `POST` | Trigger a background update task |
| `/resample` | `POST` | Trigger a background resample task |
| `/delete` | `POST` | Delete specific or all databases |
| `/data/{s}/{a}/{t}` | `GET` | Download a Parquet data file |
| `/data/.../stream` | `GET` | Stream data as CSV (chunked) |
| `/schedule` | `GET` | List all active scheduled jobs |
| `/schedule` | `POST` | Create a new recurring update job |
| `/schedule/{job_id}` | `DELETE` | Remove a scheduled job by its ID |

