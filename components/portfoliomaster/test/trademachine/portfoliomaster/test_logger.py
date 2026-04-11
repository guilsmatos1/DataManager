import io
import logging
import sys

from trademachine.core.logger import (
    CONSOLE_HANDLER_NAME,
    FILE_HANDLER_NAME,
    LOGGER_NAME,
    SafeTextStream,
    configure_console_streams,
    setup_logger,
)


def test_safe_text_stream_uses_ascii_fallbacks_for_known_symbols():
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252")
    safe_stream = SafeTextStream(stream)

    safe_stream.write("RetDD: 41.9250 → 42.4913 | ═ ═ | ─ | × | — | ≈ | 🏆")
    safe_stream.flush()

    raw.seek(0)
    written = raw.read().decode("cp1252")
    assert "RetDD: 41.9250 -> 42.4913" in written
    assert "= =" in written
    assert " | - | x | - | ~= | TOP" in written


def test_configure_console_streams_is_idempotent(monkeypatch):
    stdout = io.StringIO()
    stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    configure_console_streams()
    wrapped_stdout = sys.stdout
    wrapped_stderr = sys.stderr

    configure_console_streams()

    assert sys.stdout is wrapped_stdout
    assert sys.stderr is wrapped_stderr


def test_setup_logger_installs_own_handlers_even_with_root_handler(tmp_path):
    logger = logging.getLogger(LOGGER_NAME)
    root = logging.getLogger()
    original_root_handlers = list(root.handlers)
    original_logger_handlers = list(logger.handlers)
    original_propagate = logger.propagate
    logger.handlers.clear()

    root_handler = logging.StreamHandler(io.StringIO())
    root.addHandler(root_handler)

    try:
        configured = setup_logger(log_path=str(tmp_path / "test.log"))
        handler_names = {handler.get_name() for handler in configured.handlers}

        assert CONSOLE_HANDLER_NAME in handler_names
        assert FILE_HANDLER_NAME in handler_names
        assert configured.propagate is False
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers = original_logger_handlers
        logger.propagate = original_propagate
        root.removeHandler(root_handler)
        root_handler.close()
        root.handlers = original_root_handlers


def test_setup_logger_updates_existing_console_handler_level(tmp_path):
    logger = logging.getLogger(LOGGER_NAME)
    original_handlers = list(logger.handlers)
    original_propagate = logger.propagate
    logger.handlers.clear()

    try:
        setup_logger(log_path=str(tmp_path / "first.log"), quiet=False)
        configured = setup_logger(log_path=str(tmp_path / "first.log"), quiet=True)
        console_handler = next(
            handler
            for handler in configured.handlers
            if handler.get_name() == CONSOLE_HANDLER_NAME
        )

        assert console_handler.level == logging.WARNING
        assert (
            len(
                [h for h in configured.handlers if h.get_name() == CONSOLE_HANDLER_NAME]
            )
            == 1
        )
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers = original_handlers
        logger.propagate = original_propagate
