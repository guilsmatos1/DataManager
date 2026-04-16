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

COPY bases/ ./bases/
COPY components/ ./components/
COPY projects/ ./projects/
COPY pyproject.toml ./pyproject.toml
COPY uv.lock ./uv.lock

RUN uv sync --no-dev --frozen

# --- Stage 2: Final ---
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/bases/trading_monitor_dashboard/src:/app/bases/trading_monitor_cli/src:/app/components/tradingmonitor_storage/src:/app/components/tradingmonitor_ingestion/src:/app/components/tradingmonitor_analytics/src:/app/components/core/src:/app/components/mt5/src \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv

COPY bases/ ./bases/
COPY components/ ./components/
COPY projects/tradingmonitor/pyproject.toml ./pyproject.toml
COPY projects/tradingmonitor/alembic/ ./alembic/

CMD ["trading-monitor", "start-dashboard", "--host", "0.0.0.0", "--port", "8000"]
