# Use a multi-stage build for a smaller final image
FROM python:3.12-slim

# The following environment variables are recommended for uv in Docker:
# - UV_LINK_MODE=copy: Avoids issues with filesystems that don't support hardlinks.
# - UV_COMPILE_BYTECODE=1: Speeds up container startup.
# - PYTHONUNBUFFERED=1: Ensures logs are sent straight to terminal.
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

# Install system dependencies required for openbb / pandas native extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy dependency files first to leverage Docker layer caching
COPY pyproject.toml uv.lock ./

# Install production dependencies only (no dev tools)
# We use --no-install-project because the source code isn't copied yet.
RUN uv sync --no-dev --frozen --no-install-project

# Copy source code and metadata
COPY src/ ./src/
COPY metadata/ ./metadata/

# Now install the project itself
RUN uv sync --no-dev --frozen

# Default command: interactive CLI
CMD ["uv", "run", "datamanager", "-i"]
