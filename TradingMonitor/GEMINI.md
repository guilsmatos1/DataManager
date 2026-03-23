# TradingMonitor Project Context

## Project Overview
TradingMonitor is a comprehensive Python-based framework designed for real-time monitoring, data ingestion, and performance analysis of MetaTrader 5 (MT5) trading strategies. It bridges the gap between MT5's MQL5 environment and modern data analysis tools.

> **Note:** This is a personal project developed for private use. It is designed to be used by a single individual and does not include multi-user management or multi-tenant features.

### Core Architecture
- **Data Source**: MQL5 Expert Advisor (`src/mql5/MetricsPublisher.mq5`) running in MT5, pushing trade deals, equity updates, and account info via **TCP**.
- **Ingestion Layer**: A Python TCP server (`src/ingestion/tcp_server.py`) that validates incoming JSON payloads using Pydantic schemas (`src/ingestion/schemas.py`) and persists them to the database.
- **Storage**: TimescaleDB (PostgreSQL) for efficient time-series storage. It uses **hypertables** for `deals` and `equity_curve` tables to handle high-frequency updates.
- **Analysis Engine**: Uses `Pandas` and `QuantStats` (`src/metrics/calculator.py`) to compute financial metrics like Sharpe Ratio, Max Drawdown, Win Rate, and portfolio correlations.
- **Interface**:
    - **CLI**: A `Typer`-based command-line tool (`src/cli/main.py`) for management, database initialization, and terminal reporting.
    - **Dashboard**: A `FastAPI` web application (`src/dashboard/app.py`) providing real-time visualization via WebSockets.

### Main Technologies
- **Python 3.11+**
- **uv** (Package Manager)
- **TimescaleDB** (PostgreSQL extension)
- **SQLAlchemy** (ORM) & **Alembic** (Migrations)
- **FastAPI** (Web Framework) & **Uvicorn** (ASGI Server)
- **Pandas** & **QuantStats** (Data Analysis)
- **Pydantic** (Validation & Settings)
- **Typer** (CLI)
- **TCP/JSON** (Messaging)

---

## Building and Running

### Prerequisites
- Docker & Docker Compose (for TimescaleDB)
- Python 3.11+
- [uv](https://docs.astral.sh/uv/) installed
- MetaTrader 5 Terminal (for data source)

### Initial Setup
1.  **Install Dependencies**:
    ```bash
    uv sync
    ```
2.  **Start Database**:
    ```bash
    docker-compose up -d
    ```
3.  **Initialize Database Schema**:
    ```bash
    uv run trading-monitor setup-db
    ```

### Running the System
- **Start Ingestion Only**:
  ```bash
  uv run trading-monitor start-ingestion
  ```
- **Start Web Dashboard (with Ingestion)**:
  ```bash
  uv run trading-monitor start-dashboard
  ```
- **Check Ingestion Health**:
  ```bash
  uv run trading-monitor status
  ```

### Development Commands
- **Migrations**:
  ```bash
  alembic revision --autogenerate -m "description"
  alembic upgrade head
  ```
- **Tests**:
  ```bash
  pytest tests/
  ```

---

## Development Conventions

### Data Identification
- **Strategy ID**: Primarily identified by the **MT5 Magic Number** (stored as a string).
- **Account ID**: Primarily identified by the **MT5 Login Number**.

### Code Style & Structure
- **Imports**: All internal imports should use the `src.` prefix.
- **Runtime Environment**: Commands run via `python -m` usually require `PYTHONPATH=.`.
- **Database Access**: Use `SessionLocal` from `src.db.database` for manual DB sessions; use the `get_db` dependency in FastAPI routes.
- **Migrations**: High-frequency tables (`deals`, `equity_curve`) are initialized as hypertables in `src/db/database.py`. Standard relational tables are managed via Alembic.

### Testing
- Existing tests are located in the `tests/` directory.
- `test_metrics.py` and `test_ingestion.py` are the primary test suites.
- Use `pytest` for execution.

### Environment Configuration
Managed via `src/config.py` using `pydantic-settings`.
- `DATABASE_URL`: Connection string.
- `SERVER_HOST` / `SERVER_PORT`: Ingestion server settings.
- `DASHBOARD_HOST` / `DASHBOARD_PORT`: Web server settings.
- `DEBUG`: Boolean for verbose output.
