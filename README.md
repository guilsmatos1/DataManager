# DataManager

## Overview
**DataManager** is a centralized tool designed to fetch, manage, store, update, and resample financial OHLCV (Open, High, Low, Close, Volume) data. By providing an interactive Command-Line Interface (CLI) as well as a single-command mode, it offers a streamlined way to maintain local databases of financial assets.

Currently, it supports the following data sources:
- **OpenBB**
- **Dukascopy**

## Purpose and Objectives
The main objective of DataManager is to simplify the management of financial data. Instead of repeatedly fetching data from APIs when running tests or analyses, DataManager downloads the data locally (by default at a 1-Minute `M1` timeframe) and provides tools to reliably update it or resample it into larger timeframes (e.g., `H1`, `D1`). 

### Key Features
- **Data Fetching:** Download historical OHLCV data from OpenBB and Dukascopy.
- **Local Storage:** Store asset data efficiently on disk.
- **Resampling:** Convert `M1` base data into any higher timeframe dynamically. Supported: `M2`, `M5`, `M10`, `M15`, `M30`, `H1`, `H2`, `H3`, `H4`, `H6`, `D1`, `W1`.
- **Smart Updating:** Update existing databases by fetching only the newly available data (since the last saved date) and appending it.
- **Asset Search:** Built-in search functionality to explore available tickers and assets from the supported sources.

## Architecture
The project follows a modular architecture:

- `main.py` & `cli.py`: The entry points of the application. They provide both an interactive shell and a direct terminal command interface.
- `core/server.py` (`DataManager`): The central controller that orchestrates data flow, integrating the fetchers, storage, and processors.
- `fetchers/`: Contains the integration logic for various data sources (`openbb_fetcher.py`, `dukascopy_fetcher.py`). All fetchers standardize the fetched data into `M1` (1-minute) resolution dataframes.
- `data_management/`: 
  - `storage.py`: Handles saving, loading, updating, and deleting the local databases using optimized formats (e.g., Parquet). Data is saved under the `database/` directory, while metadata catalog (e.g., `dukas_assets.csv`) is kept in the `metadata/` directory.
  - `processor.py`: Contains data processing logic, primarily focusing on resampling OHLCV data from lower to higher timeframes.

## Instructions & Usage

### 1. Installation
Ensure you have Python installed, then install the necessary dependencies from the `requirements.txt`:
```bash
pip install -r requirements.txt
```

### 2. Running DataManager

You can run DataManager out-of-the-box using **Docker**, or natively via your Python environment.

#### Option A: Using Docker (Recommended)
Running via Docker ensures you don't have to install local dependencies or worry about OS compatibility.

1. Build and start the interactive container using `docker compose`:
```bash
docker compose run --rm datamanager
```
*Note: Any data downloaded using the docker container will be automatically persisted to the `./database` and `./metadata` folders on your host machine.*

#### Option B: Running Natively
You can run DataManager in **Interactive Mode** or **Direct Command Mode**.

**Interactive Mode:**
Start the continuous interactive shell:
```bash
python main.py -i
```
Inside the interactive prompt, you can use commands like `help`, `list`, or `search`. To exit, type `exit`.

**Direct Command Mode:**
Execute a specific command directly from your terminal without opening the interactive shell:
```bash
python main.py search --query Apple
python main.py download OPENBB AAPL 2023-01-01 2023-12-31
```

### 3. Available Commands

- `download <fonte> <ativos> [start_date] [end_date]`: Downloads data.
  *Example:* `download OPENBB AAPL,MSFT 2023-01-01 2024-01-01`
- `update <fonte> <ativos> [timeframe]`: Updates an existing database with new data.
  *Example:* `update OPENBB AAPL M1`
  *(Note: `update all` automatically updates all `M1` bases and reconstructs higher timeframes).*
- `resample <fonte> <ativos> <novo_timeframe>`: Converts an existing `M1` base to a different timeframe.
  *Example:* `resample OPENBB AAPL H1`
- `list`: Lists all locally saved databases along with technical details (rows, dimensions, size).
- `search [--source] [--query] [--exchange]`: Searches for supported assets.
  *Example:* `search --source dukascopy --query bitcoin`
- `info <fonte> <ativo> <timeframe>`: Shows metadata info for a specific database.
- `delete <fonte> <ativos> [timeframe]`: Deletes databases. (Use `delete all` for full cleanup).
