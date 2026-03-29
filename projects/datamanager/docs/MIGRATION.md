# Migration Guide: Version 1.2.0

This document outlines the major technical changes introduced in DataManager v0.1.0, including the Polylith restructuring, TimescaleDB migration, and API modernization.

---

## 1. Project Restructuring (Polylith)

The codebase has transitioned from a flat `src/` layout to **Polylith Architecture**. This change enforces better layer isolation: components (business logic) cannot depend on bases (entry points).

### Key Path Changes:
| Old Path | New Path |
|----------|----------|
| `src/datamanager/main.py` | `bases/datamanager_cli/src/trademachine/datamanager_cli/cli.py` |
| `src/datamanager/cli.py` | `bases/datamanager_cli/src/trademachine/datamanager_cli/cli.py` |
| `src/datamanager/client.py` | `components/datamanager/src/trademachine/datamanager/client.py` |
| `src/datamanager/api/router.py` | `bases/datamanager_api/src/trademachine/datamanager_api/router.py` |
| `src/datamanager/services/manager.py` | `components/datamanager/src/trademachine/datamanager/services/manager.py` |
| `src/datamanager/db/storage.py` | `components/datamanager/src/trademachine/datamanager/db/storage.py` |
| `src/datamanager/db/processor.py` | `components/datamanager/src/trademachine/datamanager/db/processor.py` |
| `src/datamanager/fetchers/dukascopy.py` | `components/datamanager/src/trademachine/datamanager/fetchers/dukascopy.py` |
| `src/datamanager/fetchers/openbb.py` | `components/datamanager/src/trademachine/datamanager/fetchers/openbb.py` |
| `src/datamanager/utils/logger.py` | Removed (use stdlib `logging`) |

---

## 2. Dependency Management: `uv`

DataManager now uses [uv](https://docs.astral.sh/uv/) for lightning-fast dependency management and execution.

- **`pyproject.toml`**: Replaces `requirements.txt` as the single source of truth for project metadata and dependencies.
- **`uv.lock`**: Ensures reproducible builds across environments.
- **`uv run datamanager`**: Use the registered entry point instead of `python main.py`.

### Migration Steps:
```bash
# Install uv (if not already present)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Synchronize dependencies (including new ccxt support)
uv sync --dev
```

---

## 3. Storage Evolution: TimescaleDB

The legacy Parquet file storage has been replaced by **TimescaleDB** (PostgreSQL with time-series extensions).

- **Hypertable**: `ohlcv_m1` is a TimescaleDB hypertable partitioned by `timestamp`, replacing `database/{source}/{ASSET}/{TIMEFRAME}/data.parquet` files.
- **Continuous Aggregates**: M5, M15, H1, H4, D1 timeframes are materialized views automatically refreshed by TimescaleDB — no runtime resampling cost.
- **Upsert Logic**: Data is inserted with `ON CONFLICT DO UPDATE` to prevent duplicates.
- **Asset Catalog**: Metadata (sources, tickers, date ranges) stored in SQL tables (`sources`, `assets`), replacing `catalog.json`.

### Database Migrations
Run Alembic migrations to set up the TimescaleDB schema:
```bash
uv run alembic upgrade head
```

---

## 4. New Data Sources & Features

### CCXT Fetcher
Support for over 100 crypto exchanges via the CCXT library.
- Usage: `download CCXT binance:BTC/USDT`
- Default exchange is `binance` if not specified.

### Gap Interpolation
New utility to handle missing data in OHLCV series via `DataProcessor.fill_gaps()`.
- Supports forward-filling prices and zero-filling volume to maintain continuous time-series.

---

## 5. API Modernization (FastAPI)

The network server has been moved to the Polylith base `datamanager_api` and standardized as a FastAPI application with better security and performance.

- **Authentication**: API Key managed via `pydantic-settings` (env vars).
- **Background Tasks**: Long-running operations (download, update) now utilize FastAPI's `BackgroundTasks` to prevent blocking.
- **Improved Validation**: Pydantic schemas for all request payloads.

---

## 6. Docker Updates

The `Dockerfile` and `docker-compose.yml` have been updated to utilize `uv` for faster builds and smaller images.

- The production image uses `uv sync --no-dev` for a leaner runtime environment.
- Native dependencies (gcc, g++) are included for compiling high-performance data processing libraries.
- **TimescaleDB** is required — use the `docker-compose.yml` which starts both the API and the database, or connect to an existing TimescaleDB instance via `DATABASE_URL`.

---

## 7. Test Reorganization

Tests have been moved to the Polylith component structure.

- **Old Structure**: `tests/test_processor.py`, `tests/test_storage.py` (root-level)
- **New Structure**:
  - `components/datamanager/test/`: Contains isolated unit tests.
  - `components/datamanager/test/conftest.py`: Shared pytest fixtures.

### Running Tests:
```bash
uv run pytest components/datamanager/test/
```

---

## 8. New Performance & Reliability Features

Version 1.2.0 introduces several internal improvements.

### Scheduled Updates
- **SchedulerService**: Integrated background task manager (APScheduler).
- **CLI Commands**: `schedule add`, `schedule list`, `schedule remove`.
- **API Endpoints**: `/schedule` (POST, GET, DELETE).
- **Persistence**: Jobs are stored in TimescaleDB via SQLAlchemyJobStore, surviving service restarts.

### Network Resiliency
- **Exponential Backoff**: Fetchers now automatically retry failed network requests (3 attempts with 1s, 2s, 4s delays).
- **Chunked Progress**: Dukascopy downloads are split into 7-day chunks with individual retry protection.

---

## 9. Migration Checklist
- [ ] Install [uv](https://docs.astral.sh/uv/) (if not present).
- [ ] Run `uv sync --dev` to synchronize dependencies and dev tools.
- [ ] Configure `DATABASE_URL` in `.env` pointing to your TimescaleDB instance.
- [ ] Run `uv run alembic upgrade head` to create the database schema.
- [ ] Update your scripts to use `uv run datamanager` instead of `python main.py`.
- [ ] If using the REST API, ensure you provide the `X-API-Key` header.
- [ ] If you have legacy Parquet data, it is no longer used — download fresh data via the CLI or API.
