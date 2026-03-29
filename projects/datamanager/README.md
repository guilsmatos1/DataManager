# DataManager

## Overview
**DataManager** is a centralized service for fetching, storing, and managing financial OHLCV (Open, High, Low, Close, Volume) data. Built on top of **TimescaleDB (PostgreSQL)**, it leverages hypertables and continuous aggregates to handle millions of records with high efficiency and real-time resampling.

**Supported Data Sources:**
- **OpenBB** — Stocks, ETFs, and indices (via yfinance).
- **Dukascopy** — Forex, commodities, and indices.
- **CCXT** — Cryptocurrency across 100+ exchanges.

---

## 🚀 Key Features
- **TimescaleDB Infrastructure:** Uses PostgreSQL with the TimescaleDB extension for time-series optimization. 
- **M1-First Storage:** Raw data is stored at 1-minute (M1) resolution in a hypertable.
- **Real-time Resampling:** Higher timeframes (M5, H1, etc.) are automatically derived via **Continuous Aggregates** (Materialized Views), ensuring instant access without manual resampling.
- **Idempotent Downloads:** Supports chunked, resumable downloads with automatic `UPSERT` logic (no data duplication).
- **Persistent Scheduler:** Cron and interval-based recurring updates are stored natively in the database (`apscheduler_jobs`), surviving service restarts and crashes.
- **REST API & Client:** A high-performance FastAPI server with a dedicated Python Client (`DataManagerClient`) for seamless integration.

---

## 🏗 Architecture (Polylith)
The project follows the **Polylith Architecture**, organized into:
- **Components:** Pure business logic (`datamanager`, `core`).
- **Bases:** Entry points (`datamanager_api`, `datamanager_cli`).
- **Projects:** Build configurations (`projects/datamanager`).

---

## 🛠 Installation & Setup

Requires [uv](https://docs.astral.sh/uv/) and **PostgreSQL + TimescaleDB**.

### 1. Synchronize Dependencies
```bash
uv sync --dev
```

### 2. Configure Environment
Copy the example environment file and fill in your database credentials:
```bash
cp .env.example .env
```
Key variables:
- `DATAMANAGER_DATABASE_URL`: Connection string (e.g., `postgresql://user:pass@localhost:5432/db`).
- `DATAMANAGER_API_KEY`: Secret key for API authentication.

### 3. Run Migrations
Ensure your database has the TimescaleDB extension installed, then run:
```bash
uv run alembic upgrade head
```

---

## 🖥 Usage

### Interactive CLI
The CLI provides a powerful shell to manage your data:
```bash
uv run datamanager-cli
```
Inside the CLI:
```bash
# Download data (supports auto-idempotency)
download dukascopy EURUSD 2020-01-01 2025-01-01

# Search for available assets
search --source ccxt --query BTC/USDT

# Schedule recurring updates
schedule add dukascopy EURUSD M1 --interval 60

# Data quality report
quality dukascopy EURUSD M1
```

### Server Mode (REST API)
Start the API to serve data to other services:
```bash
uv run uvicorn trademachine.datamanager_api.router:app --host 0.0.0.0 --port 8686
```

---

## 📦 Python Client
Integrate data directly into your scripts or notebooks:

```python
from trademachine.datamanager.client import DataManagerClient

client = DataManagerClient(base_url="http://localhost:8686", api_key="YOUR_KEY")

# Fetch data directly as a Pandas DataFrame
df = client.get_data(
    source="dukascopy", 
    asset="EURUSD", 
    timeframe="H1", 
    timezone="America/Sao_Paulo"
)

# Save as CSV locally
client.get_data("ccxt", "binance:BTC/USDT", "M1", save_path="btc.csv", save_format="csv")
```

---

## 🧪 Testing & Quality
We maintain high standards of code quality and coverage for the core manager and storage logic.

```bash
# Run the test suite
uv run pytest components/datamanager/test/

# Lint and Format
uv run ruff check .
uv run ruff format .

# Type Checking
uv run mypy components/datamanager/src/
```

---

## 📂 Data Layout (TimescaleDB)
- `ohlcv_m1`: Primary hypertable (Source of Truth).
- `ohlcv_m5`, `ohlcv_h1`, `ohlcv_d1`: Continuous Aggregates (Materialized Views).
- `assets` & `sources`: Metadata catalog and relational mapping.
- `apscheduler_jobs`: Persistent state for the job scheduler.
