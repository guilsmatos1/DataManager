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

**Responsibility:** Manages recurring data update tasks using APScheduler. Supports Cron and Intervals.

---

### 3.5 `core/config.py` — Centralized Settings

**Responsibility:** Manages application configuration via Pydantic Settings.
- **`api_key`**: `DATAMANAGER_API_KEY`.
- **`host` / `port`**: `HOST`, `PORT`.
- **`is_api_key_configured`**: Helper to check if a custom key is set.

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
- **Restoration:** Supports restoring the latest or a specific version.

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
- Support for 100+ crypto exchanges.
- Syntax: `exchange:SYMBOL` (e.g., `binance:BTC/USDT`). Defaults to binance.
- Automatically handles rate limits and chunked OHLCV fetching.

---

### 3.11 `api/router.py` — REST API (FastAPI)

**Responsibility:** Exposes functionalities via HTTP with enhanced security and performance.

#### New Enhancements:
- **Dashboard (`GET /`)**: Overview of instance status and storage statistics.
- **Health Check (`GET /health`)**: Basic connectivity test.
- **Rate Limiting**: Rolling window (60 requests per minute per IP).
- **Data Streaming**: `GET /.../stream` returns line-by-line CSV, ideal for very large datasets.
- **Pagination**: `/list` supports `skip` and `limit`.

---

## 5. Storage System

### Directory Hierarchy:
```
database/
  .versions/                 # Internal: storage for backups
  {source}/
    {ASSET}/
      {TIMEFRAME}/
        data.parquet
```

---

## 6. Metadata Catalog (SQLite)

**File:** `metadata/catalog.db`

The catalog is a SQLite database with a `catalog` table:
- **WAL Mode**: Enabled for maximum performance in concurrent environments.
- **Fast Read**: `list_databases()` is an O(1) database query instead of scanning files.
- **Sync**: `rebuild` command synchronizes the DB with actual disk state.

---

## 7. Supported Data Sources

| Key | Fetcher | Backend | Notes |
|-----|---------|---------|-------|
| `DUKASCOPY` | `DukascopyFetcher` | `dukascopy-python` | Forex/Indices. Full history. |
| `OPENBB` | `OpenBBFetcher` | `openbb` + `yfinance` | Stocks/ETFs. ~30d limit for M1. |
| `CCXT` | `CcxtFetcher` | `ccxt` | Crypto. Supports `exchange:SYMBOL`. |
