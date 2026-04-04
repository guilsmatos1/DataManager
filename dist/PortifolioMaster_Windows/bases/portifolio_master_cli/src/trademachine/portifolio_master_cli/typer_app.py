"""
Typer CLI Application Definition
"""

import typer
from trademachine.core.logger import (
    configure_console_streams,
    setup_logger,
)
from trademachine.portifoliomaster.core.config import AppConfig
from trademachine.portifoliomaster.core.exceptions import ValidationError

app = typer.Typer(
    help="PortifolioMaster CLI - MT5 Portfolio Optimization Tool",
    add_completion=False,
    no_args_is_help=True,
)

# Sub-apps
cache_app = typer.Typer(help="Cache management commands")
config_app = typer.Typer(help="Configuration management commands")
inspect_app = typer.Typer(help="Inspection and analysis commands")

DEFAULT_MT5_ADHERENCE_DIR = (
    "components/portifoliomaster/test/trademachine/portifoliomaster/reports"
)
DEFAULT_SQX_ADHERENCE_DIR = (
    "components/portifoliomaster/test/trademachine/portifoliomaster/reports-sqx"
)

app.add_typer(cache_app, name="cache")
app.add_typer(config_app, name="config")
app.add_typer(inspect_app, name="inspect")


# Global state
class State:
    def __init__(self):
        self.config = AppConfig.from_json()
        self.cli_app = None


state = State()


def validate_cli_args(args):
    """Logic constraints validation (compatible with Namespace or Typer options)."""

    # Helper to access both Namespace and dict-like objects
    def get_val(name):
        if isinstance(args, dict):
            return args.get(name)
        return getattr(args, name, None)

    min_assets = get_val("min") if get_val("min") is not None else get_val("min_assets")
    max_assets = get_val("max") if get_val("max") is not None else get_val("max_assets")
    corr = get_val("corr")
    greedy = get_val("greedy")
    greedy_loops = get_val("greedy_loops")
    montecarlo = get_val("montecarlo")
    strats = get_val("strats")
    exclude_strats = get_val("exclude_strats")
    # For compatibility with argparse test cases where optimize might be False
    optimize = get_val("optimize") if get_val("optimize") is not None else True

    if min_assets is not None and min_assets < 1:
        raise ValidationError(f"Minimum assets must be at least 1. Got: {min_assets}")
    if min_assets is not None and max_assets is not None and min_assets > max_assets:
        raise ValidationError(
            f"Minimum assets ({min_assets}) cannot be greater than Maximum assets ({max_assets})."
        )
    if corr is not None and (corr < -1 or corr > 1):
        raise ValidationError(
            f"Correlation threshold must be between -1.0 and 1.0. Got: {corr}"
        )
    if (
        strats is not None
        and exclude_strats is not None
        and str(strats).lower() != "all"
        and str(exclude_strats).lower() != "all"
    ):
        raise ValidationError("--strats and --exclude-strats cannot be used together.")
    if greedy and not optimize:
        raise ValidationError("--greedy requires --optimize.")
    if greedy_loops is not None:
        if greedy_loops < 1:
            raise ValidationError(
                f"--greedy-loops requires at least 1 loop. Got: {greedy_loops}"
            )
        if not greedy:
            raise ValidationError("--greedy-loops requires --greedy.")
    if montecarlo is not None:
        if montecarlo < 10:
            raise ValidationError(
                f"--montecarlo requires at least 10 iterations. Got: {montecarlo}"
            )
        if not optimize:
            raise ValidationError("--montecarlo requires --optimize.")


@app.callback()
def global_callback(
    quiet: bool = typer.Option(False, help="Suppress INFO output on the console"),
):
    """Global options and setup."""
    from trademachine.portifolio_master_cli.cli import PortifolioCLI

    configure_console_streams()
    setup_logger(log_path=state.config.log_path, quiet=quiet)
    if state.cli_app is None:
        state.cli_app = PortifolioCLI(default_config=state.config.model_dump())


# --- Cache Commands ---


@cache_app.command("info")
def cache_info(
    cache_path: str | None = typer.Option(None, help="Custom cache path"),
):
    """Show cache information."""
    path = cache_path or state.config.cache_path
    state.cli_app.cache_info(cache_path=path)


@cache_app.command("rebuild")
def cache_rebuild(
    directory: str = typer.Argument(..., help="Directory to scan for reports"),
    cache_path: str | None = typer.Option(None, help="Custom cache path"),
):
    """Rebuild the cache from a directory of reports."""
    path = cache_path or state.config.cache_path
    state.cli_app.cache_rebuild(directory, cache_path=path)


@cache_app.command("clear")
def cache_clear(
    cache_path: str | None = typer.Option(None, help="Custom cache path"),
):
    """Clear the cache."""
    path = cache_path or state.config.cache_path
    state.cli_app.cache_clear(cache_path=path)


@cache_app.command("save")
def cache_save(
    destination: str = typer.Argument(..., help="Destination cache file path"),
    cache_path: str | None = typer.Option(None, help="Custom cache path"),
):
    """Save the current cache file to another path."""
    path = cache_path or state.config.cache_path
    state.cli_app.cache_save(destination=destination, cache_path=path)


@cache_app.command("load")
def cache_load(
    source: str = typer.Argument(..., help="Source cache file path"),
    cache_path: str | None = typer.Option(None, help="Custom cache path"),
):
    """Load a saved cache file into the active cache location."""
    path = cache_path or state.config.cache_path
    state.cli_app.cache_load(source=source, cache_path=path)


@cache_app.command("merge")
def cache_merge(
    left: str = typer.Argument(..., help="Left cache file path"),
    right: str = typer.Argument(..., help="Right cache file path"),
    destination: str = typer.Argument(..., help="Destination merged cache path"),
):
    """Merge two saved cache files into a destination file."""
    try:
        if len({left, right, destination}) < 3:
            raise ValidationError(
                "cache merge requires distinct left, right and destination paths."
            )
    except ValidationError as e:
        raise typer.BadParameter(str(e)) from e
    state.cli_app.cache_merge(left=left, right=right, destination=destination)


# --- Config Commands ---


@config_app.command("show")
def config_show(
    path: str = typer.Option("config.json", "--config", help="Config file path"),
):
    """Show current configuration."""
    state.cli_app.config_show(path)


@config_app.command("validate")
def config_validate(
    path: str = typer.Option("config.json", "--config", help="Config file path"),
):
    """Validate configuration file."""
    state.cli_app.config_validate(path)


# --- Inspect Commands ---


@inspect_app.command("correlations")
def inspect_correlations(
    period: str = typer.Option(
        None, "--corr-period", help="Correlation period (H, D, W, M)"
    ),
    top_n: int = typer.Option(10, "--top", help="Show top N pairs"),
    threshold: float | None = typer.Option(None, help="Correlation threshold"),
):
    """Show strategy correlations."""
    period = period or state.config.corr_period
    state.cli_app.load_reports()
    state.cli_app.inspect_correlations(period=period, top_n=top_n, threshold=threshold)


@inspect_app.command("strategy")
def inspect_strategy(
    name: str = typer.Argument(..., help="Strategy name"),
    chart: bool = typer.Option(False, "--chart", help="Show equity chart"),
):
    """Show detailed strategy metrics."""
    state.cli_app.load_reports()
    state.cli_app.inspect_strategy(name, show_chart=chart)


# --- Drawdown Commands ---


def _run_drawdown_pairing(
    load: str | None = None,
    workers: int | None = None,
    target: float = typer.Option(4000.0, help="Target drawdown"),
    tick: float = typer.Option(0.1, help="Lot tick step"),
    apply: bool = typer.Option(False, "--apply", help="Apply scaling to cache"),
    report: str | None = typer.Option(
        None, "--report", help="Write pairing results to CSV"
    ),
) -> None:
    try:
        if report and not report.lower().endswith(".csv"):
            raise ValidationError("--report must point to a .csv file.")
    except ValidationError as e:
        raise typer.BadParameter(str(e)) from e
    parse_workers = workers if workers is not None else state.config.load_workers
    if load:
        state.cli_app.load_reports(
            directory_path=load,
            use_cache=False,
            parse_workers=parse_workers,
        )
    else:
        state.cli_app.load_reports()
    state.cli_app.drawdown_pairing(
        target_dd=target, lot_tick=tick, apply=apply, report_path=report
    )


@app.command("load")
def load(
    directory: str = typer.Argument(..., help="MT5 HTML reports folder path"),
    workers: int | None = typer.Option(
        None,
        "--workers",
        help="Parsing workers for report loading (0 = auto)",
    ),
    list_strats: bool = typer.Option(False, "--list", help="List strategies in memory"),
):
    """Load MT5 reports into memory and cache."""
    parse_workers = workers if workers is not None else state.config.load_workers
    state.cli_app.load_reports(
        directory_path=directory,
        use_cache=False,
        parse_workers=parse_workers,
    )
    if list_strats:
        state.cli_app.list_loaded_strategies()


@app.command("pairing")
def pairing(
    load: str | None = typer.Option(None, help="HTML reports folder path"),
    workers: int | None = typer.Option(
        None,
        "--workers",
        help="Parsing workers used when --load is provided (0 = auto)",
    ),
    target: float = typer.Option(4000.0, help="Target drawdown"),
    tick: float = typer.Option(0.1, help="Lot tick step"),
    apply: bool = typer.Option(False, "--apply", help="Apply scaling to cache"),
    report: str | None = typer.Option(
        None, "--report", help="Write pairing results to CSV"
    ),
):
    """Calculate and apply drawdown pairing/scaling."""
    _run_drawdown_pairing(
        load=load,
        workers=workers,
        target=target,
        tick=tick,
        apply=apply,
        report=report,
    )


@app.command("benchmark")
def benchmark(
    load: str | None = typer.Option(None, help="HTML reports folder path"),
    load_workers: int | None = typer.Option(
        None,
        "--load-workers",
        help="Parsing workers used when --load is provided (0 = auto)",
    ),
    strats: str | None = typer.Option(None, help="Filter strategies (comma-separated)"),
    min_assets: int = typer.Option(None, "--min", help="Min assets in portfolio"),
    max_assets: int = typer.Option(None, "--max", help="Max assets in portfolio"),
    corr: float = typer.Option(None, help="Max pairwise correlation"),
    corr_period: str = typer.Option(None, help="Correlation period (H, D, W, M)"),
    workers: int = typer.Option(None, help="Number of parallel workers"),
    date_initial: str | None = typer.Option(None, help="Start date (YYYY-MM-DD)"),
    date_final: str | None = typer.Option(None, help="End date (YYYY-MM-DD)"),
    sample_seconds: float = typer.Option(
        5.0, "--sample-seconds", help="How long to measure throughput"
    ),
    target_time: float = typer.Option(
        600.0, "--target-time", help="Extrapolation target in seconds"
    ),
):
    """Estimate how many portfolio combinations can be processed in a target time."""
    config = state.config
    cli_app = state.cli_app

    min_assets = min_assets if min_assets is not None else config.min_assets
    max_assets = max_assets if max_assets is not None else config.max_assets
    corr = corr if corr is not None else config.max_corr
    corr_period = corr_period if corr_period is not None else config.corr_period
    workers = workers if workers is not None else config.num_workers

    validate_cli_args(
        {
            "min": min_assets,
            "max": max_assets,
            "corr": corr,
            "optimize": False,
        }
    )

    if load:
        cli_app.load_reports(
            directory_path=load,
            parse_workers=(
                load_workers
                if load_workers is not None
                else state.config.load_workers
            ),
        )
    elif not cli_app.loaded_expert_names:
        cli_app.load_reports()

    strategy_filter = (
        [s.strip() for s in strats.split(",")]
        if strats and strats.lower() != "all"
        else None
    )

    found = cli_app.run_benchmark(
        min_assets=min_assets,
        max_assets=max_assets,
        include_strats=strategy_filter,
        max_correlation=corr,
        corr_period=corr_period,
        num_workers=workers,
        date_initial=date_initial,
        date_final=date_final,
        sample_seconds=sample_seconds,
        target_seconds=target_time,
        corr_filter_batch_size=config.corr_filter_batch_size,
        matrix_algebra_batch_size=config.matrix_algebra_batch_size,
    )
    if not found:
        raise typer.Exit(1)


# --- Adherence Command ---


@app.command("adherence")
def adherence(
    mt5_dir: str = typer.Option(
        DEFAULT_MT5_ADHERENCE_DIR, help="MT5 reports directory"
    ),
    sqx_dir: str = typer.Option(
        DEFAULT_SQX_ADHERENCE_DIR, help="SQX reports directory"
    ),
    output: str | None = typer.Option(None, help="Output directory"),
    threshold: float | None = typer.Option(None, help="Trade count threshold"),
    pearson: float | None = typer.Option(None, help="Pearson correlation threshold"),
    export_passed_reports: bool = typer.Option(
        False,
        "--export-passed-reports",
        help="Copy passed MT5 reports into a subfolder inside the output directory",
    ),
    no_browser: bool = typer.Option(False, help="Do not open browser"),
    quiet: bool = typer.Option(False, help="Suppress output"),
):
    """Run MT5 vs SQX adherence check."""
    threshold = threshold if threshold is not None else state.config.adherence_threshold
    pearson_threshold = (
        pearson if pearson is not None else state.config.adherence_pearson
    )
    success = state.cli_app.adherence_run(
        mt5_dir=mt5_dir,
        sqx_dir=sqx_dir,
        output_dir=output,
        threshold=threshold,
        pearson_threshold=pearson_threshold,
        export_passed_reports=export_passed_reports,
        open_browser=not no_browser,
        quiet=quiet,
    )
    if not success:
        raise typer.Exit(1)


# --- Interactive Mode ---


@app.command("interactive", help="Launch interactive shell")
def interactive():
    """Enter interactive mode."""
    state.cli_app.start_interactive_shell(default_csv_cols=state.config.csv_columns)


# --- Main Optimization Command ---


@app.command("optimize")
def optimize(
    load: str | None = typer.Option(None, help="HTML reports folder path"),
    load_workers: int | None = typer.Option(
        None,
        "--load-workers",
        help="Parsing workers used when --load is provided (0 = auto)",
    ),
    list_strats: bool = typer.Option(False, "--list", help="List strategies in memory"),
    strats: str | None = typer.Option(None, help="Filter strategies (comma-separated)"),
    exclude_strats: str | None = typer.Option(
        None, "--exclude-strats", help="Exclude strategies (comma-separated)"
    ),
    min_assets: int = typer.Option(None, "--min", help="Min assets in portfolio"),
    max_assets: int = typer.Option(None, "--max", help="Max assets in portfolio"),
    top: int = typer.Option(None, help="Number of top portfolios to keep"),
    corr: float = typer.Option(None, help="Max pairwise correlation"),
    corr_period: str = typer.Option(None, help="Correlation period (H, D, W, M)"),
    rank: str = typer.Option(None, help="Metric to rank by (RetDD, NetProfit)"),
    workers: int = typer.Option(None, help="Number of parallel workers"),
    save_trades: str | None = typer.Option(None, help="Export trades file path"),
    print_results: bool = typer.Option(None, "--print", help="Print results table"),
    output: str | None = typer.Option(None, help="Output directory"),
    import_p: str | None = typer.Option(None, help="Import saved portfolio JSON"),
    greedy: bool = typer.Option(False, help="Use greedy forward-selection"),
    greedy_loops: int | None = typer.Option(
        None,
        "--greedy-loops",
        help="Repeat greedy optimization N times, removing selected strategies from cache after each loop",
    ),
    remove_top1_from_cache: bool = typer.Option(
        False,
        "--prune-cache",
        help="Delete top-1 portfolio strategies from cache after optimization",
    ),
    date_initial: str | None = typer.Option(None, help="Start date (YYYY-MM-DD)"),
    date_final: str | None = typer.Option(None, help="End date (YYYY-MM-DD)"),
    min_metric: float = typer.Option(
        0.0, "--filter", help="Min value for ranking metric"
    ),
    montecarlo: int | None = typer.Option(
        None, help="Run Monte Carlo simulation (N iterations)"
    ),
):
    """Run portfolio optimization."""
    config = state.config
    cli_app = state.cli_app

    # Use defaults from config if not provided
    min_assets = min_assets if min_assets is not None else config.min_assets
    max_assets = max_assets if max_assets is not None else config.max_assets
    top = top if top is not None else config.top_n
    corr = corr if corr is not None else config.max_corr
    corr_period = corr_period if corr_period is not None else config.corr_period
    rank = rank if rank is not None else config.rank_by
    workers = workers if workers is not None else config.num_workers
    print_results = print_results if print_results is not None else config.print_results

    # Validation
    try:
        validate_cli_args(
            {
                "min": min_assets,
                "max": max_assets,
                "corr": corr,
                "greedy": greedy,
                "greedy_loops": greedy_loops,
                "montecarlo": montecarlo,
                "strats": strats,
                "exclude_strats": exclude_strats,
                "optimize": True,
            }
        )
    except ValidationError as e:
        raise typer.BadParameter(str(e)) from e

    # Load strategies
    if load:
        cli_app.load_reports(
            directory_path=load,
            parse_workers=(
                load_workers
                if load_workers is not None
                else state.config.load_workers
            ),
        )
    elif not cli_app.loaded_expert_names:
        cli_app.load_reports()

    if import_p:
        cli_app.import_saved_portfolio(import_p, plot_after_load=True)
        return

    if list_strats:
        cli_app.list_loaded_strategies()

    strategy_filter = (
        [s.strip() for s in strats.split(",")]
        if strats and strats.lower() != "all"
        else None
    )
    exclude_filter = (
        [s.strip() for s in exclude_strats.split(",")]
        if exclude_strats and exclude_strats.lower() != "all"
        else None
    )

    found = cli_app.run_optimization(
        min_assets=min_assets,
        max_assets=max_assets,
        top_n=top,
        include_strats=strategy_filter,
        exclude_strats=exclude_filter,
        save_trades_prefix=save_trades,
        show_terminal=print_results,
        rank_by=rank,
        max_correlation=corr,
        corr_period=corr_period,
        output_dir=output,
        csv_columns=config.csv_columns,
        num_workers=workers,
        greedy=greedy,
        greedy_loops=greedy_loops,
        remove_top1_from_cache=remove_top1_from_cache,
        date_initial=date_initial,
        date_final=date_final,
        min_metric=min_metric,
        corr_filter_batch_size=config.corr_filter_batch_size,
        matrix_algebra_batch_size=config.matrix_algebra_batch_size,
        montecarlo=montecarlo,
    )
    if not found:
        raise typer.Exit(1)
