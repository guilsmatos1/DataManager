# TradingMonitor CLI

A Python-based CLI framework for monitoring and analyzing MetaTrader 5 (MT5) trading strategies, built with the **Polylith Architecture**.

## Overview
This tool operates as a data ingestion pipeline and a real-time monitoring interface. It expects an MQL5 Expert Advisor running on your MT5 terminal to push trade deals, account updates, equity curve events, and runtime snapshots via **TCP sockets**. These events are saved into TimescaleDB (PostgreSQL) and can be visualized in real-time through a FastAPI-based dashboard.

## Requirements
*   Python 3.12+
*   Docker & Docker Compose (for TimescaleDB)
*   MetaTrader 5 terminal.
*   `uv` installed locally (`uv --version`)

## Setup Instructions

1.  **Install dependencies with `uv`:**
    ```bash
    uv sync
    ```

2.  **Start the Database:**
    ```bash
    docker-compose up -d
    ```

3.  **Initialize the Database Schema:**
    ```bash
    uv run trading-monitor setup-db
    ```

4.  **Start the Ingestion & Dashboard:**
    ```bash
    uv run trading-monitor start-dashboard
    ```
    *This starts the TCP server (port 5555) and the web interface (port 8000).*

5.  **Run the MQL5 EA:**
    *   Use the EA source at `projects/tradingmonitor/mt5/MetricsPublisher.mq5` and compile it inside your MT5 terminal (typically under `MQL5/Experts`).
    *   Attach the EA to a chart. It will begin pushing deals and equity curve updates to the TCP server.

## Runtime Snapshot Payload
To populate the `/real` dashboard with open-trade and pending-order counts, the EA should publish a `STRATEGY_RUNTIME` topic with this JSON payload:

```text
STRATEGY_RUNTIME {"time":1711737600,"magic":123456,"open_profit":48.35,"open_trades_count":2,"pending_orders_count":1}
```

The backend stores the latest snapshot per strategy and aggregates these counts on the real-accounts page.

## Configuration
You can customize the settings using environment variables or a `.env` file:
- `DATABASE_URL`: Connection string for PostgreSQL (e.g., `postgresql://postgres:password@localhost:5432/tradingmonitor`).
- `SERVER_HOST`: Host for the TCP server (default: 127.0.0.1).
- `SERVER_PORT`: Port for the TCP server (default: 5555).
- `DASHBOARD_HOST`: Host for the web dashboard (default: 127.0.0.1).
- `DASHBOARD_PORT`: Port for the web dashboard (default: 8000).
- `DEBUG`: Set to True for verbose output.
