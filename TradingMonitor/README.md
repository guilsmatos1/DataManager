# TradingMonitor CLI

A Python-based CLI framework for monitoring and analyzing MetaTrader 5 (MT5) trading strategies.

## Overview
This tool operates as a data ingestion pipeline and a real-time monitoring interface. It expects an MQL5 Expert Advisor running on your MT5 terminal to push trade deals, account updates, and equity curve events via **TCP sockets**. These events are saved into TimescaleDB (PostgreSQL) and can be visualized in real-time through a FastAPI-based dashboard.

## Requirements
*   Python 3.11+
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
    *   Compile `src/mql5/MetricsPublisher.mq5` inside your MT5 terminal.
    *   Attach the EA to a chart. It will begin pushing deals and equity curve updates to the TCP server.

## Configuration
You can customize the settings using environment variables or a `.env` file:
- `DATABASE_URL`: Connection string for PostgreSQL (e.g., `postgresql://postgres:password@localhost:5432/tradingmonitor`).
- `SERVER_HOST`: Host for the TCP server (default: 127.0.0.1).
- `SERVER_PORT`: Port for the TCP server (default: 5555).
- `DASHBOARD_HOST`: Host for the web dashboard (default: 127.0.0.1).
- `DASHBOARD_PORT`: Port for the web dashboard (default: 8000).
- `DEBUG`: Set to True for verbose output.
