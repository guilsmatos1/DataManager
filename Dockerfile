FROM python:3.12-slim
WORKDIR /app

# Install system dependencies commonly required for openbb / pandas
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default command
CMD ["python", "main.py", "-i"]
