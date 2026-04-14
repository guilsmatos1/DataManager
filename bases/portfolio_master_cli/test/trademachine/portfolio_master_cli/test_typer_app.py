from unittest.mock import MagicMock, patch

from trademachine.portfolio_master_cli.typer_app import app, state
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
                "trademachine.portfolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portfolio_master_cli.typer_app.setup_logger"),
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
                "trademachine.portfolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portfolio_master_cli.typer_app.setup_logger"),
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
                "trademachine.portfolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portfolio_master_cli.typer_app.setup_logger"),
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
                "trademachine.portfolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portfolio_master_cli.typer_app.setup_logger"),
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
                "trademachine.portfolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portfolio_master_cli.typer_app.setup_logger"),
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
                "trademachine.portfolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portfolio_master_cli.typer_app.setup_logger"),
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
                "trademachine.portfolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portfolio_master_cli.typer_app.setup_logger"),
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


def test_optimize_command_runs_brute_force_engine():
    mock_cli = MagicMock()
    previous_cli = state.cli_app
    previous_min_assets = state.config.min_assets
    previous_max_assets = state.config.max_assets
    previous_top_n = state.config.top_n
    previous_max_corr = state.config.max_corr
    previous_corr_period = state.config.corr_period
    previous_rank_by = state.config.rank_by
    previous_num_workers = state.config.num_workers
    previous_print_results = state.config.print_results
    previous_csv_columns = state.config.csv_columns
    previous_corr_filter_batch_size = state.config.corr_filter_batch_size
    previous_matrix_algebra_batch_size = state.config.matrix_algebra_batch_size
    previous_ga_population = state.config.ga_population
    previous_ga_generations = state.config.ga_generations
    previous_ga_crossover = state.config.ga_crossover
    previous_ga_mutation = state.config.ga_mutation
    try:
        state.cli_app = mock_cli
        state.config.min_assets = 1
        state.config.max_assets = 2
        state.config.top_n = 3
        state.config.max_corr = 0.5
        state.config.corr_period = "D"
        state.config.rank_by = "RetDD"
        state.config.num_workers = 0
        state.config.print_results = False
        state.config.csv_columns = []
        state.config.corr_filter_batch_size = 100
        state.config.matrix_algebra_batch_size = 10
        state.config.ga_population = 300
        state.config.ga_generations = 100
        state.config.ga_crossover = 0.7
        state.config.ga_mutation = 0.2
        mock_cli.loaded_expert_names = ["A"]
        mock_cli.run_optimization.return_value = True
        with (
            patch(
                "trademachine.portfolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portfolio_master_cli.typer_app.setup_logger"),
        ):
            result = runner.invoke(app, ["optimize", "--min", "1", "--max", "2"])
    finally:
        state.cli_app = previous_cli
        state.config.min_assets = previous_min_assets
        state.config.max_assets = previous_max_assets
        state.config.top_n = previous_top_n
        state.config.max_corr = previous_max_corr
        state.config.corr_period = previous_corr_period
        state.config.rank_by = previous_rank_by
        state.config.num_workers = previous_num_workers
        state.config.print_results = previous_print_results
        state.config.csv_columns = previous_csv_columns
        state.config.corr_filter_batch_size = previous_corr_filter_batch_size
        state.config.matrix_algebra_batch_size = previous_matrix_algebra_batch_size
        state.config.ga_population = previous_ga_population
        state.config.ga_generations = previous_ga_generations
        state.config.ga_crossover = previous_ga_crossover
        state.config.ga_mutation = previous_ga_mutation

    assert result.exit_code == 0
    assert mock_cli.run_optimization.call_args.kwargs["genetic"] is False
    assert mock_cli.run_optimization.call_args.kwargs["greedy"] is False


def test_optimize_genetic_command_runs_genetic_engine():
    mock_cli = MagicMock()
    previous_cli = state.cli_app
    previous_min_assets = state.config.min_assets
    previous_max_assets = state.config.max_assets
    previous_top_n = state.config.top_n
    previous_max_corr = state.config.max_corr
    previous_corr_period = state.config.corr_period
    previous_rank_by = state.config.rank_by
    previous_num_workers = state.config.num_workers
    previous_print_results = state.config.print_results
    previous_csv_columns = state.config.csv_columns
    previous_corr_filter_batch_size = state.config.corr_filter_batch_size
    previous_matrix_algebra_batch_size = state.config.matrix_algebra_batch_size
    previous_ga_population = state.config.ga_population
    previous_ga_generations = state.config.ga_generations
    previous_ga_crossover = state.config.ga_crossover
    previous_ga_mutation = state.config.ga_mutation
    try:
        state.cli_app = mock_cli
        state.config.min_assets = 1
        state.config.max_assets = 2
        state.config.top_n = 3
        state.config.max_corr = 0.5
        state.config.corr_period = "D"
        state.config.rank_by = "RetDD"
        state.config.num_workers = 0
        state.config.print_results = False
        state.config.csv_columns = []
        state.config.corr_filter_batch_size = 100
        state.config.matrix_algebra_batch_size = 10
        state.config.ga_population = 300
        state.config.ga_generations = 100
        state.config.ga_crossover = 0.7
        state.config.ga_mutation = 0.2
        mock_cli.loaded_expert_names = ["A"]
        mock_cli.run_optimization.return_value = True
        with (
            patch(
                "trademachine.portfolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portfolio_master_cli.typer_app.setup_logger"),
        ):
            result = runner.invoke(
                app,
                [
                    "optimize-genetic",
                    "--min",
                    "1",
                    "--max",
                    "2",
                    "--ga-population",
                    "123",
                ],
            )
    finally:
        state.cli_app = previous_cli
        state.config.min_assets = previous_min_assets
        state.config.max_assets = previous_max_assets
        state.config.top_n = previous_top_n
        state.config.max_corr = previous_max_corr
        state.config.corr_period = previous_corr_period
        state.config.rank_by = previous_rank_by
        state.config.num_workers = previous_num_workers
        state.config.print_results = previous_print_results
        state.config.csv_columns = previous_csv_columns
        state.config.corr_filter_batch_size = previous_corr_filter_batch_size
        state.config.matrix_algebra_batch_size = previous_matrix_algebra_batch_size
        state.config.ga_population = previous_ga_population
        state.config.ga_generations = previous_ga_generations
        state.config.ga_crossover = previous_ga_crossover
        state.config.ga_mutation = previous_ga_mutation

    assert result.exit_code == 0
    assert mock_cli.run_optimization.call_args.kwargs["genetic"] is True
    assert mock_cli.run_optimization.call_args.kwargs["ga_population"] == 123


def test_optimize_genetic_command_accepts_ga_loop():
    mock_cli = MagicMock()
    previous_cli = state.cli_app
    previous_min_assets = state.config.min_assets
    previous_max_assets = state.config.max_assets
    previous_top_n = state.config.top_n
    previous_max_corr = state.config.max_corr
    previous_corr_period = state.config.corr_period
    previous_rank_by = state.config.rank_by
    previous_num_workers = state.config.num_workers
    previous_print_results = state.config.print_results
    previous_csv_columns = state.config.csv_columns
    previous_corr_filter_batch_size = state.config.corr_filter_batch_size
    previous_matrix_algebra_batch_size = state.config.matrix_algebra_batch_size
    previous_ga_population = state.config.ga_population
    previous_ga_generations = state.config.ga_generations
    previous_ga_crossover = state.config.ga_crossover
    previous_ga_mutation = state.config.ga_mutation
    try:
        state.cli_app = mock_cli
        state.config.min_assets = 1
        state.config.max_assets = 2
        state.config.top_n = 3
        state.config.max_corr = 0.5
        state.config.corr_period = "D"
        state.config.rank_by = "RetDD"
        state.config.num_workers = 0
        state.config.print_results = False
        state.config.csv_columns = []
        state.config.corr_filter_batch_size = 100
        state.config.matrix_algebra_batch_size = 10
        state.config.ga_population = 300
        state.config.ga_generations = 100
        state.config.ga_crossover = 0.7
        state.config.ga_mutation = 0.2
        mock_cli.loaded_expert_names = ["A"]
        mock_cli.run_optimization.return_value = True
        with (
            patch(
                "trademachine.portfolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portfolio_master_cli.typer_app.setup_logger"),
        ):
            result = runner.invoke(
                app,
                [
                    "optimize-genetic",
                    "--min",
                    "1",
                    "--max",
                    "2",
                    "--ga-loop",
                    "3",
                ],
            )
    finally:
        state.cli_app = previous_cli
        state.config.min_assets = previous_min_assets
        state.config.max_assets = previous_max_assets
        state.config.top_n = previous_top_n
        state.config.max_corr = previous_max_corr
        state.config.corr_period = previous_corr_period
        state.config.rank_by = previous_rank_by
        state.config.num_workers = previous_num_workers
        state.config.print_results = previous_print_results
        state.config.csv_columns = previous_csv_columns
        state.config.corr_filter_batch_size = previous_corr_filter_batch_size
        state.config.matrix_algebra_batch_size = previous_matrix_algebra_batch_size
        state.config.ga_population = previous_ga_population
        state.config.ga_generations = previous_ga_generations
        state.config.ga_crossover = previous_ga_crossover
        state.config.ga_mutation = previous_ga_mutation

    assert result.exit_code == 0
    assert mock_cli.run_optimization.call_args.kwargs["ga_loop"] == 3


def test_optimize_command_rejects_ga_loop():
    mock_cli = MagicMock()
    previous_cli = state.cli_app
    try:
        state.cli_app = mock_cli
        with (
            patch(
                "trademachine.portfolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portfolio_master_cli.typer_app.setup_logger"),
        ):
            result = runner.invoke(app, ["optimize", "--ga-loop", "3"])
    finally:
        state.cli_app = previous_cli

    assert result.exit_code != 0
    assert "--ga-loop" in result.output


def test_optimize_command_rejects_removed_genetic_flag():
    mock_cli = MagicMock()
    previous_cli = state.cli_app
    try:
        state.cli_app = mock_cli
        with (
            patch(
                "trademachine.portfolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portfolio_master_cli.typer_app.setup_logger"),
        ):
            result = runner.invoke(app, ["optimize", "--genetic"])
    finally:
        state.cli_app = previous_cli

    assert result.exit_code != 0
    assert "--genetic" in result.output


def test_pairing_rejects_non_csv_report():
    mock_cli = MagicMock()
    previous_cli = state.cli_app
    previous_load_workers = state.config.load_workers
    try:
        state.cli_app = mock_cli
        state.config.load_workers = 0
        with (
            patch(
                "trademachine.portfolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portfolio_master_cli.typer_app.setup_logger"),
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
                "trademachine.portfolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portfolio_master_cli.typer_app.setup_logger"),
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
                "trademachine.portfolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portfolio_master_cli.typer_app.setup_logger"),
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
                "trademachine.portfolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portfolio_master_cli.typer_app.setup_logger"),
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
                "trademachine.portfolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portfolio_master_cli.typer_app.setup_logger"),
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
                "trademachine.portfolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portfolio_master_cli.typer_app.setup_logger"),
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
                "trademachine.portfolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portfolio_master_cli.typer_app.setup_logger"),
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
                "trademachine.portfolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portfolio_master_cli.typer_app.setup_logger"),
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
                "trademachine.portfolio_master_cli.typer_app.configure_console_streams"
            ),
            patch("trademachine.portfolio_master_cli.typer_app.setup_logger"),
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
