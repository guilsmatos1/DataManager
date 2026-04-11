import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

LOGGER_NAME = "TradeMachine"
CONSOLE_HANDLER_NAME = "trademachine-console"
FILE_HANDLER_NAME = "trademachine-file"


UNICODE_FALLBACKS = str.maketrans(
    {
        "→": "->",
        "═": "=",
        "─": "-",
        "×": "x",
        "—": "-",
        "≈": "~=",
        "🏆": "TOP",
    }
)


class _JSONFormatter(logging.Formatter):
    """JSON formatter for file-based structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def _to_console_safe_text(text: str, encoding: str | None) -> str:
    """Translates common symbols to ASCII before applying replacement fallback."""
    stream_encoding = encoding or "utf-8"
    translated = text.translate(UNICODE_FALLBACKS)
    return translated.encode(stream_encoding, errors="replace").decode(stream_encoding)


class SafeTextStream:
    """Wraps a text stream and degrades unsupported characters instead of failing."""

    def __init__(self, stream):
        self._stream = stream

    def write(self, text):
        try:
            return self._stream.write(text)
        except UnicodeEncodeError:
            encoding = getattr(self._stream, "encoding", None) or "utf-8"
            safe_text = _to_console_safe_text(text, encoding)
            return self._stream.write(safe_text)

    def flush(self):
        return self._stream.flush()

    def isatty(self):
        return self._stream.isatty()

    def fileno(self):
        return self._stream.fileno()

    @property
    def encoding(self):
        return getattr(self._stream, "encoding", None)

    @property
    def errors(self):
        return getattr(self._stream, "errors", None)

    def __getattr__(self, name):
        return getattr(self._stream, name)


def _as_safe_text(stream):
    """Returns the stream wrapped once with SafeTextStream."""
    if isinstance(stream, SafeTextStream):
        return stream
    return SafeTextStream(stream)


def configure_console_streams():
    """Redirects sys.stdout and sys.stderr to SafeTextStream to avoid encoding crashes."""
    sys.stdout = _as_safe_text(sys.stdout)
    sys.stderr = _as_safe_text(sys.stderr)


def setup_logger(
    name: str = LOGGER_NAME,
    log_path: str = "log.log",
    quiet: bool = False,
    level: int = logging.INFO,
) -> logging.Logger:
    """Configures the global system logger.

    Console handler: human-readable format (HH:MM:SS [LEVEL] message).
    File handler: structured JSON, one entry per line.

    Args:
        name: Logger name.
        log_path: Path to the log file.
        quiet: When True, suppresses INFO messages on the console (WARNING+ only).
        level: Base logging level.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False

    # Message format for console
    console_formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
    )
    console_level = logging.WARNING if quiet else level
    console_stream = _as_safe_text(sys.stdout)

    # Console Handler
    console_handler = next(
        (h for h in logger.handlers if h.get_name() == CONSOLE_HANDLER_NAME),
        None,
    )
    if console_handler is None:
        console_handler = logging.StreamHandler(console_stream)
        console_handler.set_name(CONSOLE_HANDLER_NAME)
        logger.addHandler(console_handler)
    else:
        # Update existing handler
        if hasattr(console_handler, "setStream"):
            console_handler.setStream(console_stream)

    console_handler.setLevel(console_level)
    console_handler.setFormatter(console_formatter)

    # File Handler
    file_handler = next(
        (h for h in logger.handlers if h.get_name() == FILE_HANDLER_NAME),
        None,
    )
    if file_handler is None:
        log_file = Path(log_path)
        if log_file.parent != Path("."):
            log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.set_name(FILE_HANDLER_NAME)
        logger.addHandler(file_handler)

    file_handler.setLevel(level)
    file_handler.setFormatter(_JSONFormatter())

    return logger
