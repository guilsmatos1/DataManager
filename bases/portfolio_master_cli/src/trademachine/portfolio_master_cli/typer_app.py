"""
Typer CLI Application Definition
"""

import typer
from trademachine.core.logger import (
    configure_console_streams,
    setup_logger,
)
from trademachine.portfoliomaster.public import AppConfig, ValidationError

app = typer.Typer(
    help="PortfolioMaster CLI - MT5 Portfolio Optimization Tool",
    add_completion=False,
    no_args_is_help=True,
)

# Sub-apps
cache_app = typer.Typer(help="Cache management commands")
config_app = typer.Typer(help="Configuration management commands")
inspect_app = typer.Typer(help="Inspection and analysis commands")
drawdown_app = typer.Typer(help="Drawdown and scaling commands")

app.add_typer(cache_app, name="cache")
app.add_typer(config_app, name="config")
app.add_typer(inspect_app, name="inspect")
app.add_typer(drawdown_app, name="drawdown")


# Global state
class State:
    def __init__(self):
        from typing import Any

        self.config = AppConfig.from_json()
        self.cli_app: Any = None


state = State()


def _exit_with_error(message: str) -> None:
    """Prints a user-facing error and exits with a non-zero code."""
    typer.echo(message, err=True)
    raise typer.Exit(1)


def _split_csv_values(raw: str | None) -> list[str] | None:
    """Parses comma-separated strategy names into a clean list."""
    if raw is None:
        return None
    values = [value.strip() for value in raw.split(",") if value.strip()]
    return values or None


def _load_reports_from_directory(
    directory: str,
    *,
    workers: int | None = None,
    use_cache: bool | None = None,
) -> None:
    """Loads reports with explicit kwargs to keep CLI tests stable."""
    from typing import Any

    kwargs: dict[str, Any] = {"directory_path": directory}
    if use_cache is not None:
        kwargs["use_cache"] = use_cache
    if workers is not None:
        kwargs["parse_workers"] = workers
    state.cli_app.load_reports(**kwargs)


def _run_optimization_command(
    *,
    load: str | None,
    load_workers: int | None,
    list_strats: bool,
    strats: str | None,
    exclude_strats: str | None,
    min_assets: int | None,
    max_assets: int | None,
    top: int | None,
    corr: float | None,
    corr_period: str | None,
    rank: str | None,
    workers: int | None,
    save_trades: str | None,
    print_results: bool | None,
    output: str | None,
    import_p: str | None,
    greedy: bool,
    date_initial: str | None,
    date_final: str | None,
    min_metric: float,
    montecarlo: int | None,
    prune_cache: bool,
    genetic: bool,
    ga_population: int | None = None,
    ga_generations: int | None = None,
    ga_crossover: float | None = None,
    ga_mutation: float | None = None,
    ga_loop: int = 1,
) -> None:
    """Shared CLI implementation for optimization commands."""
    config = state.config
    cli_app = state.cli_app

    resolved_min_assets = min_assets if min_assets is not None else config.min_assets
    resolved_max_assets = max_assets if max_assets is not None else config.max_assets
    resolved_top = top if top is not None else config.top_n
    resolved_corr = corr if corr is not None else config.max_corr
    resolved_corr_period = (
        corr_period if corr_period is not None else config.corr_period
    )
    resolved_rank = rank if rank is not None else config.rank_by
    resolved_workers = workers if workers is not None else config.num_workers
    resolved_print_results = (
        print_results if print_results is not None else config.print_results
    )

    validate_cli_args(
        {
            "min": resolved_min_assets,
            "max": resolved_max_assets,
            "corr": resolved_corr,
            "greedy": greedy,
            "montecarlo": montecarlo,
            "optimize": True,
        }
    )

    if strats and exclude_strats:
        _exit_with_error("--strats and --exclude-strats cannot be used together.")

    if load:
        _load_reports_from_directory(load, workers=load_workers)
    elif not cli_app.loaded_expert_names:
        cli_app.load_reports()

    if import_p:
        cli_app.import_saved_portfolio(import_p, plot_after_load=True)
        return

    if list_strats:
        cli_app.list_loaded_strategies()

    strategy_filter = (
        _split_csv_values(strats) if strats and strats.lower() != "all" else None
    )
    strategy_exclusions = _split_csv_values(exclude_strats)

    found = cli_app.run_optimization(
        min_assets=resolved_min_assets,
        max_assets=resolved_max_assets,
        top_n=resolved_top,
        include_strats=strategy_filter,
        exclude_strats=strategy_exclusions,
        save_trades_prefix=save_trades,
        show_terminal=resolved_print_results,
        rank_by=resolved_rank,
        max_correlation=resolved_corr,
        corr_period=resolved_corr_period,
        output_dir=output,
        csv_columns=config.csv_columns,
        num_workers=resolved_workers,
        greedy=greedy,
        date_initial=date_initial,
        date_final=date_final,
        min_metric=min_metric,
        corr_filter_batch_size=config.corr_filter_batch_size,
        matrix_algebra_batch_size=config.matrix_algebra_batch_size,
        montecarlo=montecarlo,
        remove_top1_from_cache=prune_cache,
        genetic=genetic,
        ga_population=ga_population
        if ga_population is not None
        else config.ga_population,
        ga_generations=ga_generations
        if ga_generations is not None
        else config.ga_generations,
        ga_crossover=ga_crossover if ga_crossover is not None else config.ga_crossover,
        ga_mutation=ga_mutation if ga_mutation is not None else config.ga_mutation,
        ga_loop=ga_loop,
    )
    if not found:
        raise typer.Exit(1)


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
    montecarlo = get_val("montecarlo")
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
    if greedy and not optimize:
        raise ValidationError("--greedy requires --optimize.")
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
    configure_console_streams()
    setup_logger(log_path=state.config.log_path, quiet=quiet)
    if state.cli_app is None:
        from trademachine.portfolio_master_cli.cli import PortfolioCLI

        state.cli_app = PortfolioCLI(default_config=state.config.model_dump())


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


@cache_app.command("list")
def cache_list(
    cache_path: str | None = typer.Option(None, help="Custom cache path"),
):
    """List all strategies stored in the cache."""
    path = cache_path or state.config.cache_path
    state.cli_app.cache_list(cache_path=path)


@cache_app.command("delete")
def cache_delete(
    names: list[str] = typer.Argument(
        ..., help="Strategy names to delete (space or comma-separated)"
    ),
    cache_path: str | None = typer.Option(None, help="Custom cache path"),
):
    """Delete specific strategies from the cache by name."""
    name_list = [n.strip() for raw in names for n in raw.split(",") if n.strip()]
    path = cache_path or state.config.cache_path
    state.cli_app.cache_delete(names=name_list, cache_path=path)


@cache_app.command("add")
def cache_add(
    names: list[str] = typer.Argument(
        ..., help="Strategy names to add (space or comma-separated)"
    ),
    directory: str = typer.Option(..., "--dir", help="Directory to search for reports"),
    cache_path: str | None = typer.Option(None, help="Custom cache path"),
):
    """Add specific strategies from a directory to the cache."""
    name_list = [n.strip() for raw in names for n in raw.split(",") if n.strip()]
    path = cache_path or state.config.cache_path
    state.cli_app.cache_add(names=name_list, directory=directory, cache_path=path)


@cache_app.command("save")
def cache_save(
    destination: str = typer.Argument(
        ..., help="Destination path for the cache snapshot"
    ),
    cache_path: str | None = typer.Option(None, help="Custom cache path"),
):
    """Save a snapshot of the cache to a file."""
    path = cache_path or state.config.cache_path
    state.cli_app.cache_save(destination=destination, cache_path=path)


@cache_app.command("load")
def cache_load(
    source: str = typer.Argument(..., help="Source cache snapshot file to load"),
    cache_path: str | None = typer.Option(None, help="Custom cache path"),
):
    """Load a saved cache snapshot into the active cache."""
    path = cache_path or state.config.cache_path
    state.cli_app.cache_load(source=source, cache_path=path)


@cache_app.command("merge")
def cache_merge(
    left: str = typer.Argument(..., help="Left cache file"),
    right: str = typer.Argument(..., help="Right cache file"),
    destination: str = typer.Argument(..., help="Output merged cache file"),
):
    """Merge two cache snapshots into a destination file."""
    if len({left, right, destination}) != 3:
        _exit_with_error("Please provide distinct left, right and destination paths.")
    state.cli_app.cache_merge(
        left=left,
        right=right,
        destination=destination,
    )


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
    period: str | None = typer.Option(
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


def _run_pairing(
    load: str | None,
    target: float,
    tick: float,
    apply: bool,
    report: str | None,
) -> None:
    """Shared implementation for pairing command aliases."""
    if report and not report.lower().endswith(".csv"):
        _exit_with_error("--report must point to a .csv file.")

    if load:
        _load_reports_from_directory(
            load,
            workers=state.config.load_workers,
            use_cache=False,
        )
    else:
        state.cli_app.load_reports()

    state.cli_app.drawdown_pairing(
        target_dd=target,
        lot_tick=tick,
        apply=apply,
        report_path=report,
    )


@drawdown_app.command("pairing")
def drawdown_pairing_command(
    load: str | None = typer.Option(None, "--load", help="HTML reports folder path"),
    target: float = typer.Option(4000.0, help="Target drawdown"),
    tick: float = typer.Option(0.1, help="Lot tick step"),
    apply: bool = typer.Option(False, "--apply", help="Apply scaling to cache"),
    report: str | None = typer.Option(None, "--report", help="CSV report path"),
):
    """Calculate and apply drawdown pairing/scaling."""
    _run_pairing(load=load, target=target, tick=tick, apply=apply, report=report)


@app.command("pairing")
def pairing(
    load: str | None = typer.Option(None, "--load", help="HTML reports folder path"),
    target: float = typer.Option(4000.0, help="Target drawdown"),
    tick: float = typer.Option(0.1, help="Lot tick step"),
    apply: bool = typer.Option(False, "--apply", help="Apply scaling to cache"),
    report: str | None = typer.Option(None, "--report", help="CSV report path"),
):
    """Calculate and apply drawdown pairing/scaling."""
    _run_pairing(load=load, target=target, tick=tick, apply=apply, report=report)


# --- Adherence Command ---


@app.command("adherence")
def adherence(
    mt5_dir: str = typer.Option("tests/reports", help="MT5 reports directory"),
    sqx_dir: str = typer.Option("tests/reports-sqx", help="SQX reports directory"),
    output: str | None = typer.Option(None, help="Output directory"),
    threshold: float | None = typer.Option(None, help="Trade count threshold"),
    pearson: float | None = typer.Option(None, help="Pearson correlation threshold"),
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


@app.command("load")
def load(
    directory: str = typer.Argument(..., help="HTML reports folder path"),
    list_strats: bool = typer.Option(False, "--list", help="List strategies in memory"),
    workers: int | None = typer.Option(
        None, "--workers", help="Number of parsing workers"
    ),
):
    """Load reports into memory without running optimization."""
    parse_workers = workers if workers is not None else state.config.load_workers
    _load_reports_from_directory(
        directory,
        workers=parse_workers,
        use_cache=False,
    )
    if list_strats:
        state.cli_app.list_loaded_strategies()


@app.command("benchmark")
def benchmark(
    load: str | None = typer.Option(None, "--load", help="HTML reports folder path"),
    load_workers: int | None = typer.Option(
        None, "--load-workers", help="Number of parsing workers"
    ),
    strats: str | None = typer.Option(None, help="Filter strategies (comma-separated)"),
    exclude_strats: str | None = typer.Option(
        None, "--exclude-strats", help="Exclude strategies (comma-separated)"
    ),
    min_assets: int = typer.Option(None, "--min", help="Min assets in portfolio"),
    max_assets: int = typer.Option(None, "--max", help="Max assets in portfolio"),
    corr: float = typer.Option(None, help="Max pairwise correlation"),
    corr_period: str | None = typer.Option(
        None, help="Correlation period (H, D, W, M)"
    ),
    workers: int = typer.Option(None, help="Number of parallel workers"),
    sample_seconds: float = typer.Option(5.0, help="Benchmark sampling duration"),
    target_seconds: float = typer.Option(
        600.0, help="Target duration for completion estimate"
    ),
):
    """Measure optimization throughput for the current search space."""
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
            "optimize": True,
        }
    )

    if strats and exclude_strats:
        _exit_with_error("--strats and --exclude-strats cannot be used together.")

    if load:
        _load_reports_from_directory(load, workers=load_workers)
    elif not cli_app.loaded_expert_names:
        cli_app.load_reports()

    found = cli_app.run_benchmark(
        min_assets=min_assets,
        max_assets=max_assets,
        max_correlation=corr,
        corr_period=corr_period,
        num_workers=workers,
        include_strats=_split_csv_values(strats),
        exclude_strats=_split_csv_values(exclude_strats),
        sample_seconds=sample_seconds,
        target_seconds=target_seconds,
    )
    if not found:
        raise typer.Exit(1)


@app.command("optimize")
def optimize(
    load: str | None = typer.Option(None, help="HTML reports folder path"),
    load_workers: int | None = typer.Option(
        None, "--load-workers", help="Number of parsing workers"
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
    corr_period: str | None = typer.Option(
        None, help="Correlation period (H, D, W, M)"
    ),
    rank: str | None = typer.Option(None, help="Metric to rank by (RetDD, NetProfit)"),
    workers: int = typer.Option(None, help="Number of parallel workers"),
    save_trades: str | None = typer.Option(None, help="Export trades file path"),
    print_results: bool = typer.Option(None, "--print", help="Print results table"),
    output: str | None = typer.Option(None, help="Output directory"),
    import_p: str | None = typer.Option(None, help="Import saved portfolio JSON"),
    greedy: bool = typer.Option(False, help="Use greedy forward-selection"),
    date_initial: str | None = typer.Option(None, help="Start date (YYYY-MM-DD)"),
    date_final: str | None = typer.Option(None, help="End date (YYYY-MM-DD)"),
    min_metric: float = typer.Option(
        0.0, "--filter", help="Min value for ranking metric"
    ),
    montecarlo: int | None = typer.Option(
        None, help="Run Monte Carlo simulation (N iterations)"
    ),
    prune_cache: bool = typer.Option(
        False, "--prune-cache", help="Remove the top portfolio from cache after success"
    ),
):
    """Run brute-force portfolio optimization."""
    _run_optimization_command(
        load=load,
        load_workers=load_workers,
        list_strats=list_strats,
        strats=strats,
        exclude_strats=exclude_strats,
        min_assets=min_assets,
        max_assets=max_assets,
        top=top,
        corr=corr,
        corr_period=corr_period,
        rank=rank,
        workers=workers,
        save_trades=save_trades,
        print_results=print_results,
        output=output,
        import_p=import_p,
        greedy=greedy,
        date_initial=date_initial,
        date_final=date_final,
        min_metric=min_metric,
        montecarlo=montecarlo,
        prune_cache=prune_cache,
        genetic=False,
    )


@app.command("optimize-genetic")
def optimize_genetic(
    load: str | None = typer.Option(None, help="HTML reports folder path"),
    load_workers: int | None = typer.Option(
        None, "--load-workers", help="Number of parsing workers"
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
    corr_period: str | None = typer.Option(
        None, help="Correlation period (H, D, W, M)"
    ),
    rank: str | None = typer.Option(None, help="Metric to rank by (RetDD, NetProfit)"),
    workers: int = typer.Option(None, help="Number of parallel workers"),
    save_trades: str | None = typer.Option(None, help="Export trades file path"),
    print_results: bool = typer.Option(None, "--print", help="Print results table"),
    output: str | None = typer.Option(None, help="Output directory"),
    import_p: str | None = typer.Option(None, help="Import saved portfolio JSON"),
    date_initial: str | None = typer.Option(None, help="Start date (YYYY-MM-DD)"),
    date_final: str | None = typer.Option(None, help="End date (YYYY-MM-DD)"),
    min_metric: float = typer.Option(
        0.0, "--filter", help="Min value for ranking metric"
    ),
    montecarlo: int | None = typer.Option(
        None, help="Run Monte Carlo simulation (N iterations)"
    ),
    prune_cache: bool = typer.Option(
        False, "--prune-cache", help="Remove the top portfolio from cache after success"
    ),
    ga_population: int | None = typer.Option(
        None, "--ga-population", help="GA population size (default: 300)"
    ),
    ga_generations: int | None = typer.Option(
        None, "--ga-generations", help="GA number of generations (default: 100)"
    ),
    ga_crossover: float | None = typer.Option(
        None, "--ga-crossover", help="GA crossover probability (default: 0.7)"
    ),
    ga_mutation: float | None = typer.Option(
        None, "--ga-mutation", help="GA mutation probability (default: 0.2)"
    ),
    ga_loop: int = typer.Option(
        1, "--ga-loop", min=1, help="Run the genetic algorithm in N loops"
    ),
):
    """Run genetic-algorithm portfolio optimization."""
    _run_optimization_command(
        load=load,
        load_workers=load_workers,
        list_strats=list_strats,
        strats=strats,
        exclude_strats=exclude_strats,
        min_assets=min_assets,
        max_assets=max_assets,
        top=top,
        corr=corr,
        corr_period=corr_period,
        rank=rank,
        workers=workers,
        save_trades=save_trades,
        print_results=print_results,
        output=output,
        import_p=import_p,
        greedy=False,
        date_initial=date_initial,
        date_final=date_final,
        min_metric=min_metric,
        montecarlo=montecarlo,
        prune_cache=prune_cache,
        genetic=True,
        ga_population=ga_population,
        ga_generations=ga_generations,
        ga_crossover=ga_crossover,
        ga_mutation=ga_mutation,
        ga_loop=ga_loop,
    )
