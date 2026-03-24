# Repository Guidelines

## Project Structure & Module Organization
Code lives under `src/datamanager/` using a standard `src` layout. `main.py` wires the CLI entry point, `cli.py` implements the interactive shell, `api/router.py` exposes the FastAPI app, and `services/manager.py` coordinates fetchers, storage, and processing. Data access code is in `db/`, source integrations are in `fetchers/`, and runtime settings live in `core/config.py`. Tests are in `tests/unit/`. Persistent local data is written to `database/`, while metadata such as `catalog.db` (SQLite) and Dukascopy assets live in `metadata/`.

## Build, Test, and Development Commands
Use `uv` for local development.

- `uv sync --dev`: install runtime and development dependencies into the project environment.
- `uv run pytest`: run the test suite under `tests/`.
- `uv run ruff check .`: run linting and import-order checks.
- `uv run datamanager -i`: start the interactive CLI.
- `uv run uvicorn datamanager.api.router:app --host 0.0.0.0 --port 8686 --reload`: run the REST API locally.
- `docker compose run --rm datamanager`: run the app in the project container with local volumes mounted.

## Coding Style & Naming Conventions
Target Python 3.12 and follow Ruff defaults configured in `pyproject.toml`: 4-space indentation and a 120-character line limit. Keep modules and functions in `snake_case`, classes in `PascalCase`, and constants in `UPPER_SNAKE_CASE`. Preserve the existing package split by responsibility (`fetchers`, `db`, `services`, `api`) instead of adding cross-cutting utility files.

## Testing Guidelines
Pytest is the test runner. Place new tests in `tests/unit/` as `test_<feature>.py`, and name test functions `test_<behavior>()`. Prefer isolated fixtures with `tmp_path` and small in-memory pandas frames, following `test_storage.py` and `test_processor.py`. No formal coverage gate is configured; add tests for any change that affects resampling, persistence, CLI parsing, or API behavior.

## Commit & Pull Request Guidelines
Recent history uses Conventional Commit prefixes such as `feat:`, `fix:`, `docs:`, `chore:`, and `security:`. Keep messages imperative and scoped to one change. Pull requests should include a short summary, the commands used for validation, and sample CLI/API output when behavior changes. Link related issues when applicable.

## Security & Configuration Tips
Do not commit `.env` files, API keys, logs, or generated database contents. Start from `.env.example` for local API configuration, and verify that `DATAMANAGER_API_KEY` is set before exposing the FastAPI service outside localhost.
