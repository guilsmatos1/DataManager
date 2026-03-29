# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Install system dependencies required for openbb / pandas native extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy entire Polylith workspace (bases + components resolve via relative paths in pyproject.toml)
COPY bases/ ./bases/
COPY components/ ./components/
COPY projects/datamanager/pyproject.toml ./pyproject.toml
COPY projects/datamanager/alembic/ ./alembic/
COPY metadata/ ./metadata/

# Copy uv.lock if present at workspace root
COPY uv.lock ./uv.lock 2>/dev/null || true

# Install dependencies — uv resolves bases/components via pyproject.toml relative paths
RUN uv sync --no-dev --frozen --no-install-project
RUN uv sync --no-dev --frozen

# Default command: start the REST API
CMD ["uv", "run", "uvicorn", "trademachine.datamanager_api.router:app", "--host", "0.0.0.0", "--port", "8686"]
