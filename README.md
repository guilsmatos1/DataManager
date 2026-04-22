# DataManager

DataManager is the TradeMachine service for fetching, storing, updating, and serving financial OHLCV data and FRED economic series.

This repository is an exported partial Polylith workspace from the main `TradeMachine` monorepo. The source of truth remains the monorepo; this repo is the external runnable/exported project.

## Layout

```text
.
├── pyproject.toml
├── workspace.toml
├── .env.example
├── .trademachine-export.json
├── bases/
│   ├── datamanager_api/
│   │   ├── pyproject.toml
│   │   ├── src/trademachine/datamanager_api/
│   │   └── test/trademachine/datamanager_api/
│   └── datamanager_cli/
│       ├── pyproject.toml
│       ├── src/trademachine/datamanager_cli/
│       └── test/trademachine/datamanager_cli/
├── components/
│   ├── core/
│   │   └── src/trademachine/core/
│   └── datamanager/
│       ├── pyproject.toml
│       ├── src/trademachine/datamanager/
│       └── test/trademachine/datamanager/
└── projects/
    └── datamanager/
        ├── pyproject.toml
        ├── Dockerfile
        ├── docker-compose.yml
        ├── alembic.ini
        ├── alembic/
        ├── docs/
        └── metadata/
```

Important paths:

- API entry point: `bases/datamanager_api/src/trademachine/datamanager_api/router.py`
- CLI entry point: `bases/datamanager_cli/src/trademachine/datamanager_cli/cli.py`
- Domain logic: `components/datamanager/src/trademachine/datamanager/`
- Shared utilities: `components/core/src/trademachine/core/`
- Migrations: `projects/datamanager/alembic/`
- Project config: `projects/datamanager/pyproject.toml`
- Docker config: `projects/datamanager/docker-compose.yml`

## Requirements

- Python 3.12+
- `uv`
- PostgreSQL/TimescaleDB

The service reads settings through Pydantic using the `DATAMANAGER_` prefix.

Useful environment variables:

```bash
DATAMANAGER_API_KEY=test-dm-key
DATAMANAGER_DATABASE_URL=postgresql://postgres:password@localhost:5433/datamanager
DATAMANAGER_HOST=127.0.0.1
DATAMANAGER_PORT=8686
FRED_API_KEY=your-fred-api-key
```

There is a `.env.example` at the repository root. If using it, make sure the database URL is available as `DATAMANAGER_DATABASE_URL`.

## Install

From the repository root:

```bash
cd ~/Sync/Projects/DataManager
uv sync --dev
```

## Database

For the local setup currently used on this machine, TimescaleDB is exposed on port `5433`:

```text
postgresql://postgres:password@localhost:5433/datamanager
```

Run migrations from the DataManager project directory:

```bash
cd ~/Sync/Projects/DataManager/projects/datamanager
DATAMANAGER_DATABASE_URL=postgresql://postgres:password@localhost:5433/datamanager \
uv run alembic upgrade head
```

Then return to the repo root before starting the API:

```bash
cd ~/Sync/Projects/DataManager
```

## Start The API

From the repository root:

```bash
cd ~/Sync/Projects/DataManager

DATAMANAGER_API_KEY=test-dm-key \
DATAMANAGER_DATABASE_URL=postgresql://postgres:password@localhost:5433/datamanager \
uv run uvicorn trademachine.datamanager_api.router:app \
  --host 127.0.0.1 \
  --port 8686
```

Open:

```text
http://127.0.0.1:8686/docs
```

Authenticated API example:

```bash
curl -H 'X-API-Key: test-dm-key' http://127.0.0.1:8686/list
```

## Start The CLI

From the repository root:

```bash
cd ~/Sync/Projects/DataManager

DATAMANAGER_API_KEY=test-dm-key \
DATAMANAGER_DATABASE_URL=postgresql://postgres:password@localhost:5433/datamanager \
uv run datamanager -i
```

Example CLI commands:

```text
list
search --source dukascopy --query EUR
download dukascopy EURUSD 2024-01-01 2024-12-31
update all
```

## Docker

The Docker files live under `projects/datamanager/`:

```bash
cd ~/Sync/Projects/DataManager/projects/datamanager
docker compose up -d
```

The current compose file builds from the repo root using:

```text
context: ../..
dockerfile: projects/datamanager/Dockerfile
```

It expects the API to connect to an external PostgreSQL/TimescaleDB instance through `DATAMANAGER_DATABASE_URL`.

## Tests

From the repository root:

```bash
uv run pytest components/datamanager/test/
uv run pytest bases/datamanager_api/test/
uv run pytest bases/datamanager_cli/test/
```

## Export Metadata

`.trademachine-export.json` records the files managed by the TradeMachine export process. Do not edit it manually unless you are intentionally repairing an export.

To refresh this repository from the monorepo:

```bash
cd ~/Sync/Projects/TradeMachine
uv run python -m tools.export_projects datamanager --target ../DataManager --dry-run --allow-dirty-target
uv run python -m tools.export_projects datamanager --target ../DataManager --allow-dirty-target
```
