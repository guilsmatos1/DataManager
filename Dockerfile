FROM python:3.12-slim
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
RUN uv sync --no-dev --frozen

# Copy source code and metadata
COPY src/ ./src/
COPY metadata/ ./metadata/

# Default command: interactive CLI
CMD ["uv", "run", "datamanager", "-i"]
