# Repository Guidelines

## Project Structure & Module Organization
Code lives under `components/datamanager/src/trademachine/datamanager/` using **Polylith architecture**. Entry points are in `bases/`: `datamanager_cli` (interactive shell) and `datamanager_api` (FastAPI REST API, port 8686). Core business logic (fetchers, storage, processing, scheduling) lives in the `datamanager` component. Tests are in `tests/unit/`. Persistent data is stored in TimescaleDB (`ohlcv_m1` hypertable + continuous aggregates for M5/M15/H1/H4/D1), with asset metadata in `sources`/`assets` tables.

## Build, Test, and Development Commands
Use `uv` for local development.

- `uv sync --dev`: install runtime and development dependencies into the project environment.
- `uv run pytest components/datamanager/test/`: run the test suite.
- `uv run ruff check .`: run linting and import-order checks.
- `uv run datamanager -i`: start the interactive CLI.
- `uv run uvicorn trademachine.datamanager_api.router:app --host 0.0.0.0 --port 8686 --reload`: run the REST API locally.
- `docker compose run --rm datamanager`: run the app in the project container with local volumes mounted.

## Coding Style & Naming Conventions
Target Python 3.12 and follow Ruff defaults configured in `pyproject.toml`: 4-space indentation and a 120-character line limit. Keep modules and functions in `snake_case`, classes in `PascalCase`, and constants in `UPPER_SNAKE_CASE`. Preserve the existing package split by responsibility (`fetchers`, `db`, `services`, `api`) instead of adding cross-cutting utility files.

## Testing Guidelines
Pytest is the test runner. Place new tests in `tests/unit/` as `test_<feature>.py`, and name test functions `test_<behavior>()`. Prefer isolated fixtures with `tmp_path` and small in-memory pandas frames, following patterns in `components/datamanager/test/`. No formal coverage gate is configured; add tests for any change that affects resampling, persistence, CLI parsing, or API behavior.

## Commit & Pull Request Guidelines
Recent history uses Conventional Commit prefixes such as `feat:`, `fix:`, `docs:`, `chore:`, and `security:`. Keep messages imperative and scoped to one change. Pull requests should include a short summary, the commands used for validation, and sample CLI/API output when behavior changes. Link related issues when applicable.

## Security & Configuration Tips
Do not commit `.env` files, API keys, logs, or generated database contents. Start from `.env.example` for local API configuration, and verify that `DATAMANAGER_API_KEY` is set before exposing the FastAPI service outside localhost.
