# DataManager

## Overview
**DataManager** is a centralized tool designed to fetch, manage, store, update, and resample financial OHLCV (Open, High, Low, Close, Volume) data. By providing an interactive Command-Line Interface (CLI) as well as a single-command mode, it offers a streamlined way to maintain local databases of financial assets.

Currently, it supports the following data sources:
- **OpenBB**: Stocks, ETFs, indices (via yfinance).
- **Dukascopy**: Forex, commodities, indices, cryptos.
- **CCXT**: Extensive crypto support across multiple exchanges (e.g., `binance:BTC/USDT`).

## Purpose and Objectives
The main objective of DataManager is to simplify the management of financial data. Instead of repeatedly fetching data from APIs when running tests or analyses, DataManager downloads the data locally (by default at a 1-Minute `M1` timeframe) and provides tools to reliably update it or resample it into larger timeframes (e.g., `H1`, `D1`).

### Key Features
- **Data Fetching:** Download historical OHLCV data from OpenBB, Dukascopy, and CCXT.
- **Local Storage:** Store asset data efficiently in Parquet format with atomic writes and cross-platform file locking.
- **Resampling:** Convert `M1` base data into any higher timeframe dynamically. Supported: `M2`, `M5`, `M10`, `M15`, `M30`, `H1`, `H2`, `H3`, `H4`, `H6`, `D1`, `W1`.
- **Smart Updating:** Update existing databases by fetching only the newly available data and appending it.
- **Data Versioning:** Automatic timestamped backups (up to 5 versions) for every saved asset/timeframe.
- **Gap Interpolation:** Built-in logic to fill missing candles via forward-filling prices and zero-filling volume.
- **Asset Search:** Built-in search functionality to explore available tickers and assets from the supported sources.
- **Scheduled Updates:** Automate recurring data updates using Cron expressions or time intervals (API & CLI).
- **REST API Modernization:** 
  - **Dashboard & Stats:** Overview of total rows, sources, and storage usage.
  - **Data Streaming:** High-performance CSV streaming for large datasets.
  - **Rate Limiting:** Sliding window protection (60 req/min).
  - **Pagination:** Support for `skip` and `limit` in asset listings.
- **Network Resiliency:** Automatic retry with exponential backoff for network-related fetch errors.
- **Concurrency Safety:** Robust SQLite-backed catalog with WAL mode for safe multi-process access.

## Architecture
DataManager follows a modular src layout (`src/datamanager/`). For a complete technical breakdown, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

For version-specific changes (v1.2.0), refer to the [Migration Guide](docs/MIGRATION.md).

- `src/datamanager/main.py` & `src/datamanager/cli.py`: Entry points providing both an interactive shell and a direct terminal command interface.
- `src/datamanager/services/manager.py` (`DataManager`): The central controller that orchestrates data flow.
- `src/datamanager/services/scheduler.py` (`SchedulerService`): Manages background automated update tasks using APScheduler.
- `src/datamanager/fetchers/`: Contains the integration logic for various data sources. All fetchers standardize the data into `M1` resolution dataframes.
- `src/datamanager/db/`:
  - `storage.py`: Handles persistence using Parquet with atomic writes, versioning, and a **SQLite catalog** (`metadata/catalog.db`).
  - `processor.py`: Contains data processing logic for OHLCV resampling and gap filling.
- `src/datamanager/api/router.py`: FastAPI REST API (port 8686) with API key authentication, rate limiting, and dashboard stats.
- `src/datamanager/core/config.py`: Application settings and environment variable management via Pydantic.
- `src/datamanager/utils/`:
  - `retry.py`: Utility for exponential backoff retries on network operations.
  - `logger.py`: Structured logging with human-readable console output and JSON file logging.

## Instructions & Usage

### 1. Installation
Ensure you have [uv](https://docs.astral.sh/uv/) installed, then install dependencies:
```bash
# Standard installation
uv sync --dev

# Installation with crypto support (CCXT)
uv sync --dev --extra crypto
```

### 2. Configuration
Copy the `.env.example` to `.env` and set your `DATAMANAGER_API_KEY`:
```bash
cp .env.example .env
```
The REST API requires this key to be present in the `X-API-Key` header. You can also customize `HOST` and `PORT` (default: `8686`).

### 3. Running DataManager

You can run DataManager out-of-the-box using **Docker**, or natively via uv.

#### Option A: Using Docker (Recommended)
Running via Docker ensures you don't have to install local dependencies or worry about OS compatibility.

1. **Interactive CLI Mode:**
```bash
docker compose run --rm datamanager_api uv run datamanager -i
```

2. **REST API Mode:**
```bash
docker compose up -d datamanager_api
```
*Note: Any data downloaded using the docker container will be automatically persisted to the `./database` and `./metadata` folders on your host machine.*

#### Option B: Running Natively
You can run DataManager in **Interactive Mode** or **Direct Command Mode**.

**Interactive Mode:**
Start the continuous interactive shell:
```bash
uv run datamanager -i
```
Inside the interactive prompt, you can use commands like `help`, `list`, or `search`. To exit, type `exit`.

**Direct Command Mode:**
Execute a specific command directly from your terminal without opening the interactive shell:
```bash
uv run datamanager search --query Apple
uv run datamanager download OPENBB AAPL 2023-01-01 2023-12-31
```

**REST API Mode:**
```bash
uv run uvicorn datamanager.api.router:app --host 0.0.0.0 --port 8686 --reload
```

### 4. Available Commands

- `download <source> <assets> [start_date] [end_date] [-timeframe tf1,tf2,...]`: Downloads data.
  *Example:* `download OPENBB AAPL,MSFT 2023-01-01 2024-01-01`
  *Example:* `download DUKASCOPY EURUSD,GBPUSD -timeframe M15,H1`
  *Example:* `download CCXT binance:BTC/USDT,eth:ETH/USDT`
- `update <source> <assets> [timeframe]`: Updates an existing database with new data.
  *Example:* `update OPENBB AAPL M1`
  *(Note: `update all` automatically updates all `M1` bases and reconstructs higher timeframes).*
- `resample <source> <assets> <new_timeframe>`: Converts an existing `M1` base to a different timeframe.
  *Example:* `resample OPENBB AAPL H1`
- `list`: Lists all locally saved databases along with technical details (rows, dimensions, size).
- `search [--source] [--query] [--exchange]`: Searches for supported assets.
  *Example:* `search --source dukascopy --query bitcoin`
- `info <source> <asset> <timeframe>`: Shows metadata info for a specific database.
- `delete <source> <assets> [timeframe]`: Deletes databases. (Use `delete all` for full cleanup).
- `schedule <subcommand> [args]`: Manages automated update tasks.
  *Example:* `schedule add DUKASCOPY EURUSD M1 --interval 60`
  *Example:* `schedule add OPENBB AAPL H1 --cron "0 9 * * 1-5"`
  *Example:* `schedule list`
  *Example:* `schedule remove <job_id>`
- `rebuild`: Rebuilds the `catalog.db` index by scanning the physical files on disk.
- `quality <source> <assets> [timeframe]`: Performs a data integrity report (checks for gaps, duplicates, and OHLC logic).

### 5. Programmatic Usage (Python Client)

You can also use DataManager programmatically in your own Python scripts using the provided client:

```python
from datamanager.client import DataManagerClient

# Connect to the API (requires DATAMANAGER_API_KEY in .env)
client = DataManagerClient(base_url="http://localhost:8686", api_key="YOUR_API_KEY")

# Download data directly into a Pandas DataFrame
# Optional: use 'timezone' parameter for automatic conversion (e.g., "America/New_York", "UTC")
df = client.get_data("DUKASCOPY", "EURUSD", "H1", timezone="America/Sao_Paulo")
print(df.head())

# Or save it directly to a CSV file
client.get_data("DUKASCOPY", "EURUSD", "H1", save_path="eurusd_h1.csv", save_format="csv")
```
