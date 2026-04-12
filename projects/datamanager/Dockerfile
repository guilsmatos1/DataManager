# syntax=docker/dockerfile:1

# --- Stage 1: Builder ---
FROM python:3.12-slim AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy workspace structure needed for Polylith resolution
COPY bases/ ./bases/
COPY components/ ./components/
COPY projects/datamanager/pyproject.toml ./pyproject.toml
COPY uv.lock ./uv.lock

# Install dependencies into /app/.venv
RUN uv sync --no-dev --frozen

# --- Stage 2: Final ---
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/bases/datamanager_api/src:/app/bases/datamanager_cli/src:/app/components/datamanager/src:/app/components/core/src:/app/components/metrics/src:/app/components/mt5/src \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Copy the virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy only necessary application code and metadata
COPY bases/ ./bases/
COPY components/ ./components/
COPY projects/datamanager/pyproject.toml ./pyproject.toml
COPY projects/datamanager/alembic/ ./alembic/
COPY projects/datamanager/metadata/ ./projects/datamanager/metadata/

# Default command: start the REST API using the venv's uvicorn
CMD ["uvicorn", "trademachine.datamanager_api.router:app", "--host", "0.0.0.0", "--port", "8686"]
