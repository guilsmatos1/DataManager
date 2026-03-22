import json
import logging
import sys
from datetime import datetime, timezone


class _JSONFormatter(logging.Formatter):
    """JSON formatter for file-based structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def setup_logger(name: str = "DataManager") -> logging.Logger:
    """Configures the global system logger.

    Console handler: human-readable format (HH:MM:SS [LEVEL] message).
    File handler (log.log): structured JSON, one entry per line.
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    # --- Console: human-readable ---
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter(fmt="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(console_handler)

    # --- File: structured JSON ---
    file_handler = logging.FileHandler("log.log", encoding="utf-8")
    file_handler.setFormatter(_JSONFormatter())
    logger.addHandler(file_handler)

    return logger
