import subprocess
from unittest.mock import patch

import pytest
import trademachine.tradingmonitor_storage.db.database as database_module
import typer
from sqlalchemy.exc import OperationalError
from trademachine.trading_monitor_cli.main import setup_db, start_ingestion
from trademachine.tradingmonitor_storage.db.database import (
    DatabaseInitializationError,
    DatabaseUnavailableError,
)


def test_ensure_database_connection_raises_actionable_error():
    error = OperationalError("SELECT 1", {}, OSError("connection refused"))

    with (
        patch.object(database_module.engine, "connect", side_effect=error),
        patch.object(
            database_module,
            "_docker_database_diagnosis",
            return_value="The database container is not running in Docker.",
        ),
    ):
        with pytest.raises(DatabaseUnavailableError) as exc_info:
            database_module.ensure_database_connection("TradingMonitor ingestion")

    message = str(exc_info.value)
    assert "Cannot start TradingMonitor ingestion" in message
    assert "Configured `DATABASE_URL`:" in message
    assert (
        "Docker diagnosis: The database container is not running in Docker." in message
    )
    assert "127.0.0.1:5433" in message
    assert "tradingmonitor" in message
    assert "***" in message


def test_docker_database_diagnosis_reports_stopped_container():
    result = subprocess.CompletedProcess(
        args=["docker", "compose", "ps"],
        returncode=0,
        stdout="redis\n",
        stderr="",
    )

    with (
        patch.object(
            database_module,
            "_get_docker_compose_command",
            return_value=["docker", "compose"],
        ),
        patch.object(database_module.subprocess, "run", return_value=result),
    ):
        message = database_module._docker_database_diagnosis()

    assert "not running in Docker" in message
    assert "docker compose up -d timescaledb" in message


def test_start_ingestion_exits_cleanly_when_database_is_unavailable(capsys):
    with patch(
        "trademachine.tradingmonitor_ingestion.public.start_server",
        side_effect=DatabaseUnavailableError("database offline"),
    ):
        with pytest.raises(typer.Exit) as exc_info:
            start_ingestion("127.0.0.1", 5555)

    captured = capsys.readouterr()
    assert exc_info.value.exit_code == 1
    assert "database offline" in captured.err


def test_setup_db_exits_cleanly_when_hypertable_creation_fails(capsys):
    with patch(
        "trademachine.trading_monitor_cli.main.init_db",
        side_effect=DatabaseInitializationError("hypertable setup failed"),
    ):
        with pytest.raises(typer.Exit) as exc_info:
            setup_db()

    captured = capsys.readouterr()
    assert exc_info.value.exit_code == 1
    assert "hypertable setup failed" in captured.err
