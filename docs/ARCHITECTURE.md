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
   - [db/storage.py](#34-dbstoragepy--persistence-layer)
   - [db/processor.py](#35-dbprocessorpy--timeframe-resampling)
   - [fetchers/base.py](#36-fetchersbasepy--abstract-interface)
   - [fetchers/dukascopy.py](#37-fetchersdukascopypy)
   - [fetchers/openbb.py](#38-fetchersopenbbpy)
   - [api/router.py](#39-apirouterpy--fastapi-rest-api)
   - [client.py](#310-clientpy--python-client-for-the-api)
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
│       │   ├── storage.py     # StorageManager: Parquet read/write + catalog
│       │   └── processor.py   # DataProcessor: OHLCV resampling
│       │
│       ├── fetchers/
│       │   ├── __init__.py    # Auto-discovery of fetcher classes via pkgutil
│       │   ├── base.py        # BaseFetcher: abstract interface (ABC)
│       │   ├── dukascopy.py   # Integration with dukascopy-python
│       │   └── openbb.py      # Integration with OpenBB (yfinance as backend)
│       │
│       ├── schemas/
│       │   └── __init__.py    # Pydantic request/response models for the API
│       │
│       ├── services/
│       │   └── manager.py     # DataManager: central logic controller
│       │
│       └── utils/
│           └── logger.py      # Dual-output logging (stdout + log.log)
│
├── tests/
│   ├── conftest.py            # Shared pytest fixtures
│   └── unit/
│       ├── test_processor.py
│       └── test_storage.py
│
├── metadata/
│   ├── catalog.json           # JSON index of all saved databases
│   └── dukas_assets.csv       # List of ~3,000 valid Dukascopy assets
│
└── database/
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

```python
# Simplified structure:
parser.add_argument('-i', '--interactive', action='store_true')
parser.add_argument('command', nargs=argparse.REMAINDER)

if args.interactive:
    cli.cmdloop()
elif args.command:
    cli.onecmd(" ".join(args.command))
else:
    parser.print_help()
```

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
| `do_rebuild` | `rebuild` | Rebuilds the `catalog.json` catalog by scanning the disk |
| `do_search` | `search` | Searches for available assets in sources (OpenBB or Dukascopy) |
| `do_resample` | `resample` | Converts M1 to other timeframes |
| `do_quality` | `quality` | Data integrity report |
| `do_exit` / `do_quit` | `exit` / `quit` | Exits the program |

#### Parsing details per command:

**`download`:**
```
download <source> <asset1,asset2,...> [start_date] [end_date] [-timeframe tf1,tf2,...]
```
- Supports **multiple assets** via comma separation.
- Optional `-timeframe` flag: after M1 download, automatically resamples to specified TFs.
- If `start_date` is omitted → uses `2000-01-01` (full history).
- If `end_date` is omitted → uses `datetime.now()`.
- Protects each asset with individual `try/except` to not abort others.

**`update`:**
```
update <source> <asset1,asset2,...> [timeframe=M1]
update all
```
- `update all` → calls `DataManager.update_all_databases()` which updates all M1s and resamples derived TFs.

**`search`:**
- Uses internal `argparse` with `shlex.split` to support queries with spaces and quotes.
- Parameters: `--source`, `--query`, `--exchange`.

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
Fetchers are auto-discovered from the `fetchers/` package — no manual registration needed.

#### Main Methods:

**`download_data(source, asset, start_date, end_date)`**
- Checks if the M1 database already exists (avoids duplicates).
- Calls `fetcher.fetch_data()`.
- Saves via `storage.save_data()` always in timeframe `M1`.

**`update_data(source, asset, timeframe="M1")`**
- Reads the last date of the existing database via `storage.get_database_info()`.
- Checks if it's up to date (1-hour margin).
- Downloads only new data (from `last_date` to `now`).
- If `timeframe` is different from M1, converts new data before appending.
- Uses `storage.append_data()` to concatenate without duplicates.

**`update_all_databases()`**
- Separates databases into two groups: M1 and higher TFs.
- First updates all M1s.
- Then rebuilds all derived TFs using `resample_database()`.

**`resample_database(source, asset, target_timeframe)`**
- Loads full M1 from disk.
- Uses `DataProcessor.resample_ohlc()` to convert.
- Saves the result (overwrites target TF).

**`check_quality(source, asset, timeframe="M1")`**
Performs 4 checks and reports found errors:
1. **OHLC Relations:** `High >= Low`, `High >= Open/Close`, `Low <= Open/Close`
2. **Duplicates:** Duplicate timestamps in index
3. **Temporal Ordering:** Index must be increasingly monotonic
4. **Gaps:** Detects absences greater than 5x the expected median frequency

**`search_assets(source, query, exchange)`**
- **OpenBB:** Calls `obb.equity.search()` and displays first 20 results.
- **Dukascopy:** Filters local CSV `metadata/dukas_assets.csv` on `ticker`, `alias`, and `nome_do_ativo` fields.

---

### 3.4 `db/storage.py` — Persistence Layer

**Responsibility:** All data read and write operations on disk, and maintenance of the JSON catalog.

**Class:** `StorageManager`

#### Path Structure:
```python
# Data file path:
database/{source_lower}/{ASSET_UPPER}/{TIMEFRAME_UPPER}/data.parquet

# Example:
database/dukascopy/EURUSD/M1/data.parquet
database/openbb/AAPL/H1/data.parquet
```

#### Storage Format:
- **Parquet** via `fastparquet` (default). Index is always a timezone-naive `DatetimeIndex`.
- The single file per source/asset/timeframe combination is always `data.parquet`.

#### Main Methods:

**`save_data(df, source, asset, timeframe)`**
- Ensures index is `DatetimeIndex`.
- Removes timezone from index if present (`tz_convert(None)`).
- Sorts index before saving.
- Updates `catalog.json` after saving.

**`append_data(df, source, asset, timeframe)`**
- Loads existing DataFrame.
- Concatenates with `pd.concat`.
- Removes index duplicates (`keep='last'`).
- Calls `save_data()` to persist.

**`load_data(source, asset, timeframe) → pd.DataFrame`**
- Reads `.parquet` via `fastparquet`.
- Raises `FileNotFoundError` if it doesn't exist.

**`get_database_info(source, asset, timeframe) → dict`**
Returns:
```python
{
    "source": str,
    "asset": str,
    "timeframe": str,
    "rows": int,
    "start_date": str,   # "YYYY-MM-DD HH:MM:SS"
    "end_date": str,     # "YYYY-MM-DD HH:MM:SS"
    "file_size_kb": float
}
```
Or `{"status": "Not Found"}` if the file doesn't exist.

**`rebuild_catalog() → dict`**
- Scans entire `database/` directory recursively.
- Rebuilds `catalog.json` from scratch.
- Useful when files are moved/deleted manually.

**`list_databases() → list`**
- First cleans empty directories (`_cleanup_empty_dirs`).
- Returns content of `catalog.json` (fast read, no Parquet I/O).

**`delete_database(source, asset, timeframe=None) → bool`**
- If `timeframe` provided: deletes only that `.parquet` file.
- If `timeframe=None`: deletes entire asset directory (all TFs).
- Updates catalog after deletion.

---

### 3.5 `db/processor.py` — Timeframe Resampling

**Responsibility:** Converts OHLCV DataFrames from a lower timeframe to a higher one.

**Class:** `DataProcessor`

#### Mapping of timeframes to pandas rules:

```python
TF_MAPPING = {
    'M1':  '1min',   'M2': '2min',   'M5':  '5min',
    'M10': '10min',  'M15': '15min', 'M30': '30min',
    'H1':  '1h',     'H2':  '2h',    'H3':  '3h',
    'H4':  '4h',     'H6':  '6h',
    'D1':  'D',      'W1':  'W',
}
```

**`resample_ohlc(df, target_timeframe) → pd.DataFrame`** (classmethod)
- Automatically detects column names (case-insensitive: `open`, `Open`, `OPEN` → all work).
- Aggregation rules:
  - `Open` → `first`
  - `High` → `max`
  - `Low` → `min`
  - `Close` → `last`
  - `Volume` → `sum`
- Uses `df.resample(rule).agg(agg_dict).dropna()`.
- Raises `ValueError` for unsupported TF or DataFrame without OHLC columns.

---

### 3.6 `fetchers/base.py` — Abstract Interface

**Responsibility:** Defines the contract that all fetchers must implement.

**Class:** `BaseFetcher(ABC)`

```python
@property
@abstractmethod
def source_name(self) -> str:
    """Readable name of the source (e.g., 'Dukascopy')"""

@abstractmethod
def fetch_data(self, asset: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
    """
    Returns DataFrame with:
    - Index: DatetimeIndex timezone-naive
    - Columns: Open, High, Low, Close, Volume (capitalized)
    """
```

**Return contract guaranteed by all fetchers:**
- Index: `DatetimeIndex` without timezone, name `"datetime"`
- Columns: `Open`, `High`, `Low`, `Close`, `Volume` (first letter uppercase)
- Chronologically sorted data
- No index duplicates

---

### 3.7 `fetchers/dukascopy.py`

**Responsibility:** M1 data download via `dukascopy-python` library.

**Class:** `DukascopyFetcher(BaseFetcher)`

#### Chunked download logic:
- Splits total period into **7-day chunks**.
- For each chunk, calls `dukascopy_python.fetch()` with `INTERVAL_MIN_1` and `OFFER_SIDE_BID`.
- Displays **colored progress bar** in terminal (using `colorama`).
- Individual chunk errors are silenced (weekends return empty, which is expected).

#### Ticker Validation:
- Before downloading, checks if ticker exists in `metadata/dukas_assets.csv`.
- Supports searching by both `ticker` field and `alias` field (case-insensitive).
- Raises `ValueError` with guidance message if ticker is not found.

#### Post-processing:
```python
# Remove duplicates (keep last)
df = df[~df.index.duplicated(keep='last')]

# Remove timezone
df.index = df.index.tz_convert(None)

# Standardize column names: open → Open, high → High, etc.
col_map = {c.lower(): c.capitalize() for c in df.columns}
df.rename(columns=col_map, inplace=True)

df.index.name = "datetime"
df.sort_index(inplace=True)
```

---

### 3.8 `fetchers/openbb.py`

**Responsibility:** M1 data download via OpenBB (using YFinance as provider).

**Class:** `OpenBBFetcher(BaseFetcher)`

#### Main Logic:
```python
kwargs = {
    "symbol": asset,
    "interval": "1m",
    "provider": "yfinance"
}
# Dates are included only if user specified (start_date.year > 2000)
res = obb.equity.price.historical(**kwargs)
df = res.to_df()
```

**Important Note:** If `start_date.year <= 2000` (CLI default for full history), dates are omitted from the request so YFinance returns maximum available data.

#### Known Limitation:
YFinance limits intraday data (M1) to approximately the last 30 days. For longer history, use Dukascopy.

#### Post-processing: identical to Dukascopy (timezone and column name standardization).

---

### 3.9 `api/router.py` — REST API (FastAPI)

**Responsibility:** Exposes `DataManager` functionalities as an HTTP API protected by API Key.

**Framework:** FastAPI v0.128
**Default Port:** `8686`
**Global Instance:** `manager = DataManager()` (singleton)

#### Security (3 layers):

1. **API Key Authentication** via `X-API-Key` header
   - Key read from `DATAMANAGER_API_KEY` env var via `core/config.py` (Pydantic Settings)
   - Returns HTTP 403 if key is invalid

2. **Input Validation** via Pydantic schemas (`schemas/`)
   - `source`: `^[a-zA-Z0-9_]+$`
   - `asset`: `^[a-zA-Z0-9_,\s\-]+$`
   - `timeframe`: `^[a-zA-Z0-9_]+$`

3. **Path Traversal Protection** via `re.match()` on URL parameters

#### Endpoints:

| Method | Route | Description | Async |
|--------|-------|-------------|-------|
| `POST` | `/download` | Downloads new asset (background task) | ✅ |
| `POST` | `/update` | Updates database (background task) | ✅ |
| `POST` | `/delete` | Deletes database(s) | ❌ |
| `POST` | `/resample` | Generates derived timeframe (background task) | ✅ |
| `GET` | `/list` | Lists all databases | ❌ |
| `GET` | `/info/{source}/{asset}/{timeframe}` | Database metadata | ❌ |
| `GET` | `/search` | Searches for available assets | ❌ |
| `GET` | `/data/{source}/{asset}/{timeframe}` | Downloads raw `.parquet` file | ❌ |

**Long operations** (`download`, `update`, `resample`) are executed in FastAPI **BackgroundTasks** to not block the server. Endpoint returns immediately with `{"status": "success", "message": "...started in background"}`.

**`GET /data/{source}/{asset}/{timeframe}`:** Returns `.parquet` file as binary stream (`application/octet-stream`) for direct download.

#### Direct Execution:
```bash
uv run uvicorn datamanager.api.router:app --host 0.0.0.0 --port 8686 --reload
```

---

### 3.10 `client.py` — Python Client for the API

**Responsibility:** Python wrapper to consume DataManager REST API programmatically.

**Class:** `DataManagerClient`

#### Initialization:
```python
client = DataManagerClient(
    base_url="http://127.0.0.1:8686",
    api_key="YOUR_API_KEY_HERE"
)
```
Uses `requests.Session` to automatically send `X-API-Key` header in all requests.

#### Methods:

| Method | HTTP | Description | Return |
|--------|------|-------------|--------|
| `download(source, asset, start_date, end_date)` | POST | Triggers server download | `dict` |
| `update(source, asset, timeframe)` | POST | Triggers update | `dict` |
| `delete(source, asset, timeframe)` | POST | Deletes database | `dict` |
| `resample(source, asset, target_timeframe)` | POST | Triggers resample | `dict` |
| `list_databases()` | GET | Lists databases | `list[dict]` |
| `info(source, asset, timeframe)` | GET | Metadata | `dict` |
| `search(source, query, exchange)` | GET | Searches assets | `pd.DataFrame` |
| `get_data(source, asset, timeframe, save_path, save_format)` | GET | Downloads data | `pd.DataFrame` or `str` |

**`get_data()`** is the most important method for programmatic use:
- No `save_path`: loads Parquet into memory and returns `pd.DataFrame`.
- With `save_path` and `save_format="parquet"`: saves `.parquet` file directly to disk.
- With `save_path` and `save_format="csv"`: converts to CSV and saves to disk.

---

## 4. Data Flow

### 4.1 Full Download Flow

```
User: download DUKASCOPY EURUSD 2020-01-01 2024-01-01
  │
  ▼
CLI.do_download()
  │ → Parses source, asset, dates
  │ → Calls DataManager.download_data()
  │
  ▼
DataManager.download_data()
  │ → Checks: storage.get_database_info() → "Not Found" (ok, continue)
  │ → _get_fetcher("DUKASCOPY") → DukascopyFetcher()
  │ → fetcher.fetch_data(asset, start, end)
  │
  ▼
DukascopyFetcher.fetch_data()
  │ → Validates ticker in dukas_assets.csv
  │ → Chunk loop (7 days) with progress bar
  │ → pd.concat(dfs)
  │ → Removes duplicates, removes timezone, standardizes columns
  │ → Returns M1 DataFrame
  │
  ▼
DataManager.download_data() (continued)
  │ → storage.save_data(df_m1, "DUKASCOPY", "EURUSD", "M1")
  │
  ▼
StorageManager.save_data()
  │ → _get_path() → "database/dukascopy/EURUSD/M1/data.parquet"
  │ → Ensures DatetimeIndex, removes tz, sorts
  │ → df.to_parquet(file_path, engine='fastparquet')
  │ → _update_catalog_entry() → updates catalog.json
  │
  ▼
Output: "✓ Database EURUSD (M1) saved successfully! (X rows)"
```

### 4.2 Resample Flow

```
User: resample DUKASCOPY EURUSD H4
  │
  ▼
DataManager.resample_database("DUKASCOPY", "EURUSD", "H4")
  │ → storage.load_data("DUKASCOPY", "EURUSD", "M1")  ← loads base M1
  │ → processor.resample_ohlc(df_m1, "H4")
  │      → rule = "4h"
  │      → df.resample("4h").agg({Open: first, High: max, Low: min, Close: last, Volume: sum})
  │      → .dropna()
  │ → storage.save_data(df_h4, "DUKASCOPY", "EURUSD", "H4")
  │
  ▼
Output: "✓ Conversion finished and saved!"
  File: database/dukascopy/EURUSD/H4/data.parquet
```

---

## 5. Storage System

### Directory Hierarchy:
```
database/
  {source_lowercase}/        # e.g., dukascopy, openbb
    {ASSET_UPPERCASE}/       # e.g., EURUSD, AAPL
      {TIMEFRAME_UPPERCASE}/ # e.g., M1, H1, D1
        data.parquet         # single data file per combination
```

### Parquet Format:
- Engine: `fastparquet`
- Index: `DatetimeIndex` with `name="datetime"`, no timezone
- Columns: `Open`, `High`, `Low`, `Close`, `Volume`

### Why Parquet?
- Efficient compression for time series data
- Fast columnar reading
- Preserves native data types (float64, datetime64)

---

## 6. Metadata Catalog

**File:** `metadata/catalog.json`

The catalog is a JSON list of objects, one per stored database:

```json
[
  {
    "source": "dukascopy",
    "asset": "EURUSD",
    "timeframe": "M1",
    "rows": 2764800,
    "start_date": "2020-01-02 00:00:00",
    "end_date": "2024-12-31 23:59:00",
    "file_size_kb": 45230.5
  }
]
```

**Automatic Update:** Catalog is updated upon every `save_data()`, `append_data()`, and `delete_database()`.

**`rebuild`:** `rebuild` (CLI) command or `storage.rebuild_catalog()` method scans entire `database/` directory and rebuilds JSON from scratch, useful after manual filesystem operations.

**Fast Read:** `list_databases()` only reads JSON (without opening any Parquet), making the `list` command very fast regardless of data volume.

---

## 7. Supported Data Sources

| Key | Fetcher | Backend | Available Data |
|-----|---------|---------|----------------|
| `DUKASCOPY` | `DukascopyFetcher` | `dukascopy-python` | Forex, indices, commodities, cryptos (~3,000 assets). Full history since ~2000. |
| `OPENBB` | `OpenBBFetcher` | `openbb` + `yfinance` | Stocks, ETFs, indices. M1 data limited to ~30 days. |

### Dukascopy Assets File:
`metadata/dukas_assets.csv` — CSV with ~3,000 rows and columns:
- `ticker` — Official identifier (e.g., `EURUSD`)
- `alias` — Alternative name accepted in CLI
- `nome_do_ativo` — Readable name (e.g., "Euro vs US Dollar")
- `categoria` — Asset group (Forex, Crypto, etc.)

---

## 8. Supported Timeframes

| Abbreviation | Pandas Equivalent | Name |
|--------------|-------------------|------|
| `M1` | `1min` | 1 Minute (base) |
| `M2` | `2min` | 2 Minutes |
| `M5` | `5min` | 5 Minutes |
| `M10` | `10min` | 10 Minutes |
| `M15` | `15min` | 15 Minutes |
| `M30` | `30min` | 30 Minutes |
| `H1` | `1h` | 1 Hour |
| `H2` | `2h` | 2 Hours |
| `H3` | `3h` | 3 Hours |
| `H4` | `4h` | 4 Hours |
| `H6` | `6h` | 6 Hours |
| `D1` | `D` | Daily |
| `W1` | `W` | Weekly |

**Important:** Only `M1` is downloaded directly from fetchers. All others are generated via resampling.

---

## 9. API Security

### Authentication
- Mandatory Header: `X-API-Key: <key>`
- Configured via `DATAMANAGER_API_KEY` environment variable (read by `core/config.py` via Pydantic Settings)
- HTTP 403 if key is invalid or missing

### Injection Protection
- All input fields are validated with Pydantic regex in `schemas/` (e.g., `^[a-zA-Z0-9_]+$`)
- URL parameters in `GET /info` and `GET /data` are validated with `re.match()` before use

### Async Operations
- Downloads and updates run in FastAPI `BackgroundTasks`
- Server is never blocked during long operations
- Prevents duplicates in `/download` by checking M1 existence before scheduling background task (returns HTTP 409 Conflict if already exists)

---

## 10. Docker Deployment

### API Mode (recommended for server):
```bash
docker-compose up -d
```

`docker-compose.yml` configures:
- Image: `ghcr.io/guilsmatos1/datamanager:latest`
- Port: `8686:8686`
- Persistent Volumes: `./database` and `./metadata` (data never lost when recreating container)
- Auto Restart: `restart: always`
- Environment Variable: `DATAMANAGER_API_KEY`
- Default Command: `uv run uvicorn datamanager.api.router:app --host 0.0.0.0 --port 8686`

### Dockerfile:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN apt-get install -y gcc g++   # needed for compiling native dependencies
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen
COPY src/ ./src/
COPY metadata/ ./metadata/
CMD ["uv", "run", "datamanager", "-i"]
```

---

## 11. Main Dependencies

| Package | Version | Function |
|---------|---------|----------|
| `pandas` | 3.0.1 | DataFrame manipulation, resampling, I/O |
| `fastparquet` | 2025.12.0 | Parquet file read/write |
| `fastapi` | 0.128.8 | REST API Framework |
| `uvicorn` | 0.40.0 | ASGI server for FastAPI |
| `pydantic` | 2.12.5 | API payload validation |
| `pydantic-settings` | 2.9.0 | Settings management from env vars / .env |
| `dukascopy-python` | 4.0.1 | Dukascopy data download |
| `openbb` | 4.7.0 | Financial data platform |
| `yfinance` | 1.2.0 | Data backend for OpenBB |
| `colorama` | 0.4.6 | Colored terminal output |
| `requests` | 2.32.5 | HTTP client (used by `client.py`) |
| `python-dateutil` | 2.9.0 | Flexible date parsing in CLI |

Dependencies are managed via `pyproject.toml` and locked in `uv.lock`. Install with:
```bash
uv sync --dev   # includes dev tools (pytest, ruff)
uv sync --no-dev  # production only
```

---

## 12. CLI Command Reference

### Full Usage Examples:

```bash
# Interactive mode
uv run datamanager -i

# Direct mode (without interactive shell)
uv run datamanager download DUKASCOPY EURUSD 2020-01-01 2024-01-01
uv run datamanager list
uv run datamanager quality DUKASCOPY EURUSD M1
```

### Inside Interactive Shell:

```bash
# Download with full history (since 2000-01-01)
download DUKASCOPY EURUSD

# Download multiple assets with automatic resampling
download DUKASCOPY EURUSD,GBPUSD,USDJPY 2023-01-01 2024-01-01 -timeframe H1,H4,D1

# Update an asset
update DUKASCOPY EURUSD

# Update all databases at once
update all

# List all databases
list

# Rebuild catalog (after manual changes)
rebuild

# Search assets
search                                    # shows source summary
search --query "bitcoin"                  # search in OpenBB
search --source dukascopy --query "EUR"   # offline search in CSV

# Create derived timeframe from M1
resample DUKASCOPY EURUSD H1
resample DUKASCOPY EURUSD,GBPUSD H1,H4,D1

# View database metadata
info DUKASCOPY EURUSD M1

# Check data quality
quality DUKASCOPY EURUSD M1
quality OPENBB AAPL,MSFT M1

# Delete a specific timeframe
delete DUKASCOPY EURUSD H1

# Delete all timeframes of an asset
delete DUKASCOPY EURUSD

# Delete EVERYTHING (asks for confirmation)
delete all

# Exit
exit
```

---

## 13. REST API Reference

**Base URL:** `http://<host>:8686`
**Authentication:** Header `X-API-Key: <your_key>`

### POST /download
```json
// Request body:
{
  "source": "DUKASCOPY",
  "asset": "EURUSD",
  "start_date": "2020-01-01",   // optional
  "end_date": "2024-01-01"      // optional
}

// Response 200:
{"status": "success", "message": "Download of EURUSD via DUKASCOPY started in background"}

// Response 409 (already exists):
{"detail": "The database for EURUSD via DUKASCOPY already exists..."}
```

### POST /update
```json
// Request body:
{"source": "DUKASCOPY", "asset": "EURUSD", "timeframe": "M1"}

// Response 200:
{"status": "success", "message": "Update of EURUSD via DUKASCOPY (M1) started in background"}
```

### POST /delete
```json
// Delete a timeframe:
{"source": "DUKASCOPY", "asset": "EURUSD", "timeframe": "H1"}

// Delete all timeframes of the asset:
{"source": "DUKASCOPY", "asset": "EURUSD"}

// Delete everything:
{"source": "all", "asset": "all"}
```

### POST /resample
```json
{"source": "DUKASCOPY", "asset": "EURUSD", "target_timeframe": "H4"}
```

### GET /list
```json
// Response 200:
{
  "databases": [
    {
      "source": "dukascopy",
      "asset": "EURUSD",
      "timeframe": "M1",
      "rows": 2764800,
      "start_date": "2020-01-02 00:00:00",
      "end_date": "2024-12-31 23:59:00",
      "file_size_kb": 45230.5
    }
  ]
}
```

### GET /info/{source}/{asset}/{timeframe}
```
GET /info/dukascopy/EURUSD/M1
// Response: same object from get_database_info()
```

### GET /search
```
GET /search?source=dukascopy&query=bitcoin
GET /search?source=openbb&query=Apple&exchange=NASDAQ

// Response 200:
{"assets": [...list of objects...]}
```

### GET /data/{source}/{asset}/{timeframe}
```
GET /data/dukascopy/EURUSD/M1

// Response: binary .parquet file
// Content-Type: application/octet-stream
// Content-Disposition: attachment; filename="dukascopy_EURUSD_M1.parquet"
```

---

## Notes for Contribution / Extension

### Adding a new data source:
1. Create `src/datamanager/fetchers/my_source.py` inheriting from `BaseFetcher`
2. Implement `source_name` (property) and `fetch_data()` (returning standardized DataFrame)
3. No other changes needed — the fetcher is **auto-discovered** via `pkgutil`/`importlib` in `fetchers/__init__.py`. CLI and API work automatically.

### Adding a new timeframe:
1. Add entry to `TF_MAPPING` dictionary in `src/datamanager/db/processor.py`:
   ```python
   'M45': '45min',
   ```
2. The entire system supports the new TF automatically.

### Important Invariants (system contracts):
- All persisted data has a sorted, timezone-naive `DatetimeIndex`.
- All fetchers return columns with first letter capitalized: `Open`, `High`, `Low`, `Close`, `Volume`.
- `M1` timeframe is always the base data; never resample from a derived TF to generate another.
- `catalog.json` must always reflect real disk state. Use `rebuild` in case of doubt.
