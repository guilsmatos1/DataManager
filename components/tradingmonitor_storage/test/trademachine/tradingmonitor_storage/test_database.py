from contextlib import nullcontext
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError
from trademachine.tradingmonitor_storage.db import database as database_module


def test_ensure_hypertables_raises_initialization_error_and_rolls_back():
    conn = MagicMock()
    conn.execute.side_effect = SQLAlchemyError("hypertable failed")

    with (
        patch.object(database_module.engine, "connect", return_value=nullcontext(conn)),
        patch.object(database_module.logger, "exception") as mock_log,
    ):
        with pytest.raises(database_module.DatabaseInitializationError) as exc_info:
            database_module._ensure_hypertables()

    assert "creating hypertables" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, SQLAlchemyError)
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()
    mock_log.assert_called_once_with("Failed to create TradingMonitor hypertables")
