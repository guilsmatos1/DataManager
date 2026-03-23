import os

# Set default environment variables for testing
os.environ.setdefault("API_KEY", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("DATAMANAGER_API_KEY", "test")
