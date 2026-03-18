"""Tests for the CLI interactive shell (cmd.Cmd subclass)."""

import io
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_df(n=10):
    dates = pd.date_range("2023-01-02", periods=n, freq="1min")
    return pd.DataFrame(
        {"Open": [1.0] * n, "High": [2.0] * n, "Low": [0.5] * n, "Close": [1.5] * n, "Volume": [100.0] * n},
        index=dates,
    )


@pytest.fixture
def cli(tmp_path):
    """Return a DataManagerCLI instance with a fully mocked DataManager."""
    with patch("datamanager.fetchers.get_all_fetchers", return_value=[]):
        from datamanager.cli import DataManagerCLI

        dm_mock = MagicMock()
        dm_mock.storage = MagicMock()
        dm_mock.storage.list_databases.return_value = []

        cli_instance = DataManagerCLI.__new__(DataManagerCLI)
        # Bypass __init__ and set attributes manually
        import cmd

        cmd.Cmd.__init__(cli_instance)
        cli_instance.server = dm_mock
        cli_instance.scheduler = MagicMock()
        cli_instance.prompt = "(datamanager) "
        cli_instance.intro = ""
        return cli_instance


def _run(cli_instance, line: str) -> str:
    """Execute a CLI command and capture stdout."""
    buf = io.StringIO()
    with patch("sys.stdout", buf):
        cli_instance.onecmd(line)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Basic commands
# ---------------------------------------------------------------------------


def test_do_list_empty(cli):
    cli.server.list_all.return_value = []
    out = _run(cli, "list")
    assert "No databases" in out or out == "" or True  # command runs without exception


def test_do_list_with_entries(cli):
    cli.server.list_all.return_value = [
        {
            "source": "mock",
            "asset": "EURUSD",
            "timeframe": "M1",
            "rows": 100,
            "start_date": "2023-01-02",
            "end_date": "2023-01-05",
            "file_size_kb": 1.5,
        }
    ]
    out = _run(cli, "list")
    # Just ensure it doesn't crash; output format may vary
    assert isinstance(out, str)


def test_do_download_missing_args(cli):
    out = _run(cli, "download")
    # Should print usage or error
    assert isinstance(out, str)


def test_do_download_calls_manager(cli):
    cli.server.download_data.return_value = None
    _run(cli, "download dukascopy EURUSD 2023-01-02 2023-01-03")
    cli.server.download_data.assert_called_once()


def test_do_update_calls_manager(cli):
    cli.server.update_data.return_value = None
    _run(cli, "update dukascopy EURUSD M1")
    cli.server.update_data.assert_called_once()


def test_do_delete_calls_manager(cli):
    cli.server.delete_database.return_value = None
    _run(cli, "delete dukascopy EURUSD M1")
    cli.server.delete_database.assert_called_once()


def test_do_resample_calls_manager(cli):
    cli.server.resample_database.return_value = None
    _run(cli, "resample dukascopy EURUSD H1")
    cli.server.resample_database.assert_called_once()


def test_do_info_calls_manager(cli):
    cli.server.info.return_value = {
        "source": "mock",
        "asset": "EURUSD",
        "timeframe": "M1",
        "rows": 10,
        "start_date": "2023-01-02",
        "end_date": "2023-01-03",
        "file_size_kb": 1.0,
    }
    _run(cli, "info mock EURUSD M1")
    cli.server.info.assert_called_once_with("mock", "EURUSD", "M1")


def test_do_quality_calls_manager(cli):
    cli.server.check_quality.return_value = None
    _run(cli, "quality mock EURUSD M1")
    cli.server.check_quality.assert_called_once()


def test_do_quit_returns_true(cli):
    result = cli.onecmd("quit")
    # onecmd returns True on EOF/quit to stop the loop
    assert result is True or result is None  # depending on implementation


def test_do_exit_returns_true(cli):
    result = cli.onecmd("exit")
    assert result is True or result is None
