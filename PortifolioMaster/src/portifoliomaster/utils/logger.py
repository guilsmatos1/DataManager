import logging
import sys

LOGGER_NAME = "PMaster"
CONSOLE_HANDLER_NAME = "pmaster-console"
FILE_HANDLER_NAME = "pmaster-file"
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


def _as_safe_text(stream):
    """Returns the stream wrapped once with SafeTextStream."""
    if isinstance(stream, SafeTextStream):
        return stream
    return SafeTextStream(stream)


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


def configure_console_streams() -> None:
    """Makes stdout/stderr resilient to legacy terminal encodings."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        setattr(sys, name, _as_safe_text(stream))


def setup_logger(name=LOGGER_NAME, log_path: str = "log.log", quiet: bool = False):
    """Configures the global system logger.

    Args:
        quiet: When True, suppresses INFO messages on the console (WARNING+ only).
               File handler is unaffected and always logs at INFO level.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    # Message format
    formatter = logging.Formatter(fmt="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    console_level = logging.WARNING if quiet else logging.INFO
    console_stream = _as_safe_text(sys.stdout)

    console_handler = next(
        (handler for handler in logger.handlers if handler.get_name() == CONSOLE_HANDLER_NAME),
        None,
    )
    if console_handler is None:
        console_handler = logging.StreamHandler(console_stream)
        console_handler.set_name(CONSOLE_HANDLER_NAME)
        logger.addHandler(console_handler)
    else:
        console_handler.setStream(console_stream)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)

    file_handler = next(
        (handler for handler in logger.handlers if handler.get_name() == FILE_HANDLER_NAME),
        None,
    )
    if file_handler is None:
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.set_name(FILE_HANDLER_NAME)
        logger.addHandler(file_handler)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    return logger
