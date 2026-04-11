# TradingMonitor Project Context

## Project Overview
TradingMonitor is a comprehensive Python-based framework designed for real-time monitoring, data ingestion, and performance analysis of MetaTrader 5 (MT5) trading strategies. It bridges the gap between MT5's MQL5 environment and modern data analysis tools.

This project is built using the **Polylith Architecture**, organized into reusable components and entry-point bases.

> **Note:** This is a personal project developed for private use. It is designed to be used by a single individual and does not include multi-user management or multi-tenant features.

### Core Architecture
- **Data Source**: MQL5 Expert Advisor running in MT5, pushing trade deals, equity updates, and account info via **TCP**.
- **Ingestion Layer**: A TCP server located in `components/tradingmonitor_ingestion/src/trademachine/tradingmonitor_ingestion/ingestion/tcp_server.py` that validates incoming JSON payloads using Pydantic schemas and persists them through the storage component.
- **Storage**: TimescaleDB (PostgreSQL) for efficient time-series storage. It uses **hypertables** for `deals` and `equity_curve` tables to handle high-frequency updates.
- **Analysis Engine**: Uses `Pandas` and `QuantStats` (`components/tradingmonitor_analytics/src/trademachine/tradingmonitor_analytics/metrics/calculator.py`) to compute financial metrics like Sharpe Ratio, Drawdown, Win Rate, and portfolio correlations.
- **Interfaces (Bases)**:
    - **CLI**: A `Typer`-based command-line tool (`bases/trading_monitor_cli/`) for management, database initialization, and terminal reporting.
    - **Dashboard**: A `FastAPI` web application (`bases/trading_monitor_dashboard/`) providing real-time visualization via WebSockets.

### Main Technologies
- **Python 3.12+**
- **uv** (Package Manager & Workspace)
- **Polylith** (Architecture)
- **TimescaleDB** (PostgreSQL extension)
- **SQLAlchemy 2.0+** (ORM) & **Alembic** (Migrations)
- **FastAPI** (Web Framework) & **Uvicorn** (ASGI Server)
- **Pandas** & **QuantStats** (Data Analysis)
- **Pydantic 2.0+** (Validation & Settings)
- **Typer** (CLI)
- **TCP/JSON** (Messaging)

---

## Building and Running

### Prerequisites
- Docker & Docker Compose (for TimescaleDB)
- Python 3.12+
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
  uv run pytest components/tradingmonitor_storage/test components/tradingmonitor_ingestion/test components/tradingmonitor_analytics/test bases/trading_monitor_cli/test bases/trading_monitor_dashboard/test
  ```

---

## Development Conventions

### Data Identification
- **Strategy ID**: Primarily identified by the **MT5 Magic Number** (stored as a string).
- **Account ID**: Primarily identified by the **MT5 Login Number**.

### Code Style & Structure (Polylith)
- **Namespace**: All internal imports MUST use the `trademachine` namespace (e.g., `from trademachine.tradingmonitor_storage import ...`).
- **Components**: Lógica pura e reutilizável em `components/`.
- **Bases**: Pontos de entrada (CLI, Web) em `bases/`.
- **Database Access**: Use `SessionLocal` from `trademachine.tradingmonitor_storage.db.database`.
- **Migrations**: High-frequency tables (`deals`, `equity_curve`) are initialized as hypertables in `trademachine.tradingmonitor_storage.db.database.py`. Standard relational tables are managed via Alembic in `projects/tradingmonitor/alembic/`.

### Testing
- TradingMonitor tests are split across `components/tradingmonitor_storage/test/`, `components/tradingmonitor_ingestion/test/`, `components/tradingmonitor_analytics/test/`, `bases/trading_monitor_cli/test/`, and `bases/trading_monitor_dashboard/test/`.
- Use `uv run pytest` for execution.

### Environment Configuration
Managed via `trademachine.tradingmonitor_storage.config` using `pydantic-settings`.
- `DATABASE_URL`: Connection string.
- `SERVER_HOST` / `SERVER_PORT`: Ingestion server settings.
- `DASHBOARD_HOST` / `DASHBOARD_PORT`: Web server settings.
- `DEBUG`: Boolean for verbose output.
