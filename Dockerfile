# syntax=docker/dockerfile:1

# --- Stage 1: Builder ---
FROM python:3.12-slim AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY pyproject.toml uv.lock* ./
COPY src/ ./src/

RUN uv sync --no-dev --frozen --no-install-project 2>/dev/null || uv sync --no-dev --no-install-project

# --- Stage 2: Final ---
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv

COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY metadata/ ./metadata/

CMD ["uvicorn", "trademachine.datamanager_api.router:app", "--host", "0.0.0.0", "--port", "8686"]
