from unittest.mock import MagicMock, patch

from trademachine.portifolio_master_cli.typer_app import app, state
from typer.testing import CliRunner

runner = CliRunner()


def test_load_command_uses_directory_and_can_list():
    mock_cli = MagicMock()
    previous_cli = state.cli_app
    previous_load_workers = state.config.load_workers
    try:
        state.cli_app = mock_cli
        state.config.load_workers = 0
        with (
            patch(
                "trademachine.portifolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portifolio_master_cli.typer_app.setup_logger"),
        ):
            result = runner.invoke(app, ["load", "./reports", "--list"])
    finally:
        state.cli_app = previous_cli
        state.config.load_workers = previous_load_workers

    assert result.exit_code == 0
    mock_cli.load_reports.assert_called_once_with(
        directory_path="./reports", use_cache=False, parse_workers=0
    )
    mock_cli.list_loaded_strategies.assert_called_once_with()


def test_cache_save_uses_destination_and_custom_path():
    mock_cli = MagicMock()
    previous_cli = state.cli_app
    previous_cache_path = state.config.cache_path
    try:
        state.cli_app = mock_cli
        state.config.cache_path = "cache.parquet"
        with (
            patch(
                "trademachine.portifolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portifolio_master_cli.typer_app.setup_logger"),
        ):
            result = runner.invoke(app, ["cache", "save", "./backup/cache.parquet"])
    finally:
        state.cli_app = previous_cli
        state.config.cache_path = previous_cache_path

    assert result.exit_code == 0
    mock_cli.cache_save.assert_called_once_with(
        destination="./backup/cache.parquet", cache_path="cache.parquet"
    )


def test_cache_load_uses_source_and_custom_path():
    mock_cli = MagicMock()
    previous_cli = state.cli_app
    previous_cache_path = state.config.cache_path
    try:
        state.cli_app = mock_cli
        state.config.cache_path = "cache.parquet"
        with (
            patch(
                "trademachine.portifolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portifolio_master_cli.typer_app.setup_logger"),
        ):
            result = runner.invoke(app, ["cache", "load", "./backup/cache.parquet"])
    finally:
        state.cli_app = previous_cli
        state.config.cache_path = previous_cache_path

    assert result.exit_code == 0
    mock_cli.cache_load.assert_called_once_with(
        source="./backup/cache.parquet", cache_path="cache.parquet"
    )


def test_cache_merge_uses_three_paths():
    mock_cli = MagicMock()
    previous_cli = state.cli_app
    try:
        state.cli_app = mock_cli
        with (
            patch(
                "trademachine.portifolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portifolio_master_cli.typer_app.setup_logger"),
        ):
            result = runner.invoke(
                app,
                [
                    "cache",
                    "merge",
                    "./left.parquet",
                    "./right.parquet",
                    "./merged.parquet",
                ],
            )
    finally:
        state.cli_app = previous_cli

    assert result.exit_code == 0
    mock_cli.cache_merge.assert_called_once_with(
        left="./left.parquet",
        right="./right.parquet",
        destination="./merged.parquet",
    )


def test_cache_merge_rejects_duplicate_paths():
    mock_cli = MagicMock()
    previous_cli = state.cli_app
    try:
        state.cli_app = mock_cli
        with (
            patch(
                "trademachine.portifolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portifolio_master_cli.typer_app.setup_logger"),
        ):
            result = runner.invoke(
                app,
                [
                    "cache",
                    "merge",
                    "./same.parquet",
                    "./same.parquet",
                    "./merged.parquet",
                ],
            )
    finally:
        state.cli_app = previous_cli

    assert result.exit_code != 0
    assert "distinct left, right and destination" in result.output
    mock_cli.cache_merge.assert_not_called()


def test_pairing_accepts_load_option():
    mock_cli = MagicMock()
    previous_cli = state.cli_app
    previous_load_workers = state.config.load_workers
    try:
        state.cli_app = mock_cli
        state.config.load_workers = 0
        with (
            patch(
                "trademachine.portifolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portifolio_master_cli.typer_app.setup_logger"),
        ):
            result = runner.invoke(
                app,
                [
                    "pairing",
                    "--load",
                    "./reports",
                    "--target",
                    "4000",
                    "--tick",
                    "0.1",
                ],
            )
    finally:
        state.cli_app = previous_cli
        state.config.load_workers = previous_load_workers

    assert result.exit_code == 0
    mock_cli.load_reports.assert_called_once_with(
        directory_path="./reports", use_cache=False, parse_workers=0
    )
    mock_cli.drawdown_pairing.assert_called_once_with(
        target_dd=4000.0, lot_tick=0.1, apply=False, report_path=None
    )


def test_pairing_accepts_report_option():
    mock_cli = MagicMock()
    previous_cli = state.cli_app
    previous_load_workers = state.config.load_workers
    try:
        state.cli_app = mock_cli
        state.config.load_workers = 0
        with (
            patch(
                "trademachine.portifolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portifolio_master_cli.typer_app.setup_logger"),
        ):
            result = runner.invoke(
                app,
                [
                    "pairing",
                    "--load",
                    "./reports",
                    "--target",
                    "4000",
                    "--tick",
                    "0.1",
                    "--report",
                    "./pairing.csv",
                ],
            )
    finally:
        state.cli_app = previous_cli
        state.config.load_workers = previous_load_workers

    assert result.exit_code == 0
    mock_cli.drawdown_pairing.assert_called_once_with(
        target_dd=4000.0,
        lot_tick=0.1,
        apply=False,
        report_path="./pairing.csv",
    )


def test_pairing_rejects_non_csv_report():
    mock_cli = MagicMock()
    previous_cli = state.cli_app
    previous_load_workers = state.config.load_workers
    try:
        state.cli_app = mock_cli
        state.config.load_workers = 0
        with (
            patch(
                "trademachine.portifolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portifolio_master_cli.typer_app.setup_logger"),
        ):
            result = runner.invoke(
                app,
                [
                    "pairing",
                    "--load",
                    "./reports",
                    "--report",
                    "./pairing.txt",
                ],
            )
    finally:
        state.cli_app = previous_cli
        state.config.load_workers = previous_load_workers

    assert result.exit_code != 0
    assert ".csv file" in result.output
    mock_cli.drawdown_pairing.assert_not_called()


def test_load_command_accepts_workers_option():
    mock_cli = MagicMock()
    previous_cli = state.cli_app
    try:
        state.cli_app = mock_cli
        with (
            patch(
                "trademachine.portifolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portifolio_master_cli.typer_app.setup_logger"),
        ):
            result = runner.invoke(app, ["load", "./reports", "--workers", "3"])
    finally:
        state.cli_app = previous_cli

    assert result.exit_code == 0
    mock_cli.load_reports.assert_called_once_with(
        directory_path="./reports", use_cache=False, parse_workers=3
    )


def test_optimize_accepts_load_workers_option():
    mock_cli = MagicMock()
    previous_cli = state.cli_app
    try:
        state.cli_app = mock_cli
        mock_cli.run_optimization.return_value = True
        with (
            patch(
                "trademachine.portifolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portifolio_master_cli.typer_app.setup_logger"),
        ):
            result = runner.invoke(
                app,
                [
                    "optimize",
                    "--load",
                    "./reports",
                    "--load-workers",
                    "4",
                    "--min",
                    "5",
                    "--max",
                    "5",
                ],
            )
    finally:
        state.cli_app = previous_cli

    assert result.exit_code == 0
    mock_cli.load_reports.assert_called_once_with(
        directory_path="./reports", parse_workers=4
    )


def test_optimize_accepts_prune_cache_option():
    mock_cli = MagicMock()
    previous_cli = state.cli_app
    try:
        state.cli_app = mock_cli
        mock_cli.run_optimization.return_value = True
        with (
            patch(
                "trademachine.portifolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portifolio_master_cli.typer_app.setup_logger"),
        ):
            result = runner.invoke(
                app,
                [
                    "optimize",
                    "--load",
                    "./reports",
                    "--min",
                    "5",
                    "--max",
                    "5",
                    "--prune-cache",
                ],
            )
    finally:
        state.cli_app = previous_cli

    assert result.exit_code == 0
    assert mock_cli.run_optimization.call_args.kwargs["remove_top1_from_cache"] is True


def test_optimize_accepts_exclude_strats_option():
    mock_cli = MagicMock()
    previous_cli = state.cli_app
    try:
        state.cli_app = mock_cli
        mock_cli.run_optimization.return_value = True
        with (
            patch(
                "trademachine.portifolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portifolio_master_cli.typer_app.setup_logger"),
        ):
            result = runner.invoke(
                app,
                [
                    "optimize",
                    "--load",
                    "./reports",
                    "--min",
                    "5",
                    "--max",
                    "5",
                    "--exclude-strats",
                    "A,B",
                ],
            )
    finally:
        state.cli_app = previous_cli

    assert result.exit_code == 0
    assert mock_cli.run_optimization.call_args.kwargs["exclude_strats"] == ["A", "B"]


def test_optimize_rejects_strats_and_exclude_strats_together():
    mock_cli = MagicMock()
    previous_cli = state.cli_app
    try:
        state.cli_app = mock_cli
        with (
            patch(
                "trademachine.portifolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portifolio_master_cli.typer_app.setup_logger"),
        ):
            result = runner.invoke(
                app,
                [
                    "optimize",
                    "--load",
                    "./reports",
                    "--min",
                    "5",
                    "--max",
                    "5",
                    "--strats",
                    "A,B",
                    "--exclude-strats",
                    "C,D",
                ],
            )
    finally:
        state.cli_app = previous_cli

    assert result.exit_code != 0
    assert "cannot be used together" in result.output
    mock_cli.run_optimization.assert_not_called()


def test_benchmark_accepts_load_workers_option():
    mock_cli = MagicMock()
    previous_cli = state.cli_app
    try:
        state.cli_app = mock_cli
        mock_cli.run_benchmark.return_value = True
        with (
            patch(
                "trademachine.portifolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portifolio_master_cli.typer_app.setup_logger"),
        ):
            result = runner.invoke(
                app,
                [
                    "benchmark",
                    "--load",
                    "./reports",
                    "--load-workers",
                    "4",
                    "--min",
                    "5",
                    "--max",
                    "5",
                ],
            )
    finally:
        state.cli_app = previous_cli

    assert result.exit_code == 0
    mock_cli.load_reports.assert_called_once_with(
        directory_path="./reports", parse_workers=4
    )
    mock_cli.run_benchmark.assert_called_once()


def test_cache_delete_uses_names_and_custom_path():
    mock_cli = MagicMock()
    previous_cli = state.cli_app
    previous_cache_path = state.config.cache_path
    try:
        state.cli_app = mock_cli
        state.config.cache_path = "cache.parquet"
        with (
            patch(
                "trademachine.portifolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portifolio_master_cli.typer_app.setup_logger"),
        ):
            result = runner.invoke(app, ["cache", "delete", "StratA", "StratB"])
    finally:
        state.cli_app = previous_cli
        state.config.cache_path = previous_cache_path

    assert result.exit_code == 0
    mock_cli.cache_delete.assert_called_once_with(
        names=["StratA", "StratB"], cache_path="cache.parquet"
    )


def test_cache_add_uses_names_dir_and_custom_path():
    mock_cli = MagicMock()
    previous_cli = state.cli_app
    previous_cache_path = state.config.cache_path
    try:
        state.cli_app = mock_cli
        state.config.cache_path = "cache.parquet"
        with (
            patch(
                "trademachine.portifolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portifolio_master_cli.typer_app.setup_logger"),
        ):
            result = runner.invoke(
                app, ["cache", "add", "StratA", "StratB", "--dir", "./reports"]
            )
    finally:
        state.cli_app = previous_cli
        state.config.cache_path = previous_cache_path

    assert result.exit_code == 0
    mock_cli.cache_add.assert_called_once_with(
        names=["StratA", "StratB"], directory="./reports", cache_path="cache.parquet"
    )
