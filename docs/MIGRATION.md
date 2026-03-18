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
| `network_server.py` | `src/datamanager/api/router.py` |
| `core/server.py` | `src/datamanager/services/manager.py` |
| `data_management/storage.py` | `src/datamanager/db/storage.py` |
| `data_management/processor.py` | `src/datamanager/db/processor.py` |
| `fetchers/` | `src/datamanager/fetchers/` |
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

# Synchronize dependencies
uv sync --dev
```

---

## 3. API Modernization (FastAPI)

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

## 5. Coding Standards: Ruff

The project now adopts **Ruff** for linting and formatting, replacing previous heterogeneous tools. Configuration is centralized in `pyproject.toml`.

- **Check**: `uv run ruff check .`
- **Format**: `uv run ruff format .`
