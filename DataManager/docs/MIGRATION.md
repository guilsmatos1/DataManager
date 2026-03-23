# Migration Guide: Version 1.2.0

This document outlines the major technical changes introduced in DataManager v1.2.0, including the project restructuring, dependency management shift, and API modernization.

---

## 1. Project Restructuring (src/ layout)

The codebase has transitioned from a flat structure to a **standard Python `src/` layout**. This change enforces better package isolation and prevents accidental imports from the project root.

### Key Path Changes:
| Old Path | New Path |
|----------|----------|
| `main.py` | `src/datamanager/main.py` |
| `cli.py` | `src/datamanager/cli.py` |
| `client.py` | `src/datamanager/client.py` |
| `network_server.py` | `src/datamanager/api/router.py` |
| `core/server.py` | `src/datamanager/services/manager.py` |
| `data_management/storage.py` | `src/datamanager/db/storage.py` |
| `data_management/processor.py` | `src/datamanager/db/processor.py` |
| `fetchers/dukascopy_fetcher.py` | `src/datamanager/fetchers/dukascopy.py` |
| `fetchers/openbb_fetcher.py` | `src/datamanager/fetchers/openbb.py` |
| `logger.py` | `src/datamanager/utils/logger.py` |

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

## 3. Storage Evolution: SQLite Catalog

The legacy `catalog.json` has been replaced by a high-performance **SQLite database** (`metadata/catalog.db`).

- **WAL Mode**: Enabled by default to support concurrent read/write operations without locking issues.
- **Improved Performance**: Database listings and metadata lookups no longer require full file scans.
- **Automatic Migration**: The system will automatically populate `catalog.db` upon first run or when the `rebuild` command is executed.

---

## 4. New Data Sources & Features

### CCXT Fetcher
Support for over 100 crypto exchanges via the CCXT library.
- Usage: `download CCXT binance:BTC/USDT`
- Default exchange is `binance` if not specified.

### Data Versioning
Automatic backup system for your databases.
- Every `save` operation creates a timestamped version in `database/.versions/`.
- Up to 5 historical versions are kept per asset/timeframe.

### Gap Interpolation
New utility to handle missing data in OHLCV series.
- Supports forward-filling prices and zero-filling volume to maintain continuous time-series.

---

## 5. API Modernization (FastAPI)

The network server has been moved to `src/datamanager/api/` and standardized as a FastAPI application with better security and performance.

- **Authentication**: API Key managed via `pydantic-settings` (env vars).
- **Background Tasks**: Long-running operations (download, update, resample) now utilize FastAPI's `BackgroundTasks` to prevent blocking.
- **Improved Validation**: Pydantic schemas for all request payloads.

---

## 4. Docker Updates

The `Dockerfile` and `docker-compose.yml` have been updated to utilize `uv` for faster builds and smaller images.

- The production image now uses `uv sync --no-dev` for a leaner runtime environment.
- Native dependencies (gcc, g++) are included for compiling high-performance data processing libraries.

---

## 5. Test Reorganization

Tests have been moved and reorganized to support better scaling and shared fixtures.

- **Old Structure**: `tests/test_processor.py`, `tests/test_storage.py` (root-level)
- **New Structure**: 
  - `tests/unit/`: Contains isolated unit tests.
  - `tests/conftest.py`: Shared pytest fixtures (e.g., temporary storage, sample dataframes).

### Running Tests:
```bash
uv run pytest
```

---

## 7. New Performance & Reliability Features

Version 1.2.0 introduces several internal improvements to make DataManager more robust for production-like environments.

### Scheduled Updates
- **SchedulerService**: Integrated background task manager (APScheduler).
- **CLI Commands**: `schedule add`, `schedule list`, `schedule remove`.
- **API Endpoints**: `/schedule` (POST, GET, DELETE).

### Network Resiliency
- **Exponential Backoff**: Fetchers now automatically retry failed network requests (3 attempts with 1s, 2s, 4s delays).
- **Chunked Progress**: Dukascopy downloads are split into 7-day chunks with individual retry protection.

### Concurrency Safety
- **File Locking**: Cross-platform sidecar locking (`.lock`) prevents data corruption when multiple processes/threads access the same database or catalog.
- **Atomic Renames**: Data is saved to a temporary file before being moved to the final destination.

---

## 8. Migration Checklist
- [ ] Install [uv](https://docs.astral.sh/uv/) (if not present).
- [ ] Run `uv sync --dev` to synchronize dependencies and dev tools.
- [ ] Rename your `.env` variables if necessary (refer to `.env.example`).
- [ ] Update your scripts to use `uv run datamanager` instead of `python main.py`.
- [ ] If using the REST API, ensure you provide the `X-API-Key` header.
- [ ] Check if you need to run `uv run datamanager rebuild` to resync your local databases with the new catalog format.
