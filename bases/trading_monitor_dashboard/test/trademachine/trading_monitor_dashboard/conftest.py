import os

# Set required env vars before any app module is imported (Settings is module-level).
os.environ["API_KEY"] = "test-api-key-pytest"
os.environ["DATABASE_URL"] = (
    "postgresql://postgres:password@localhost:5433/trademachine.tradingmonitor_test"
)
