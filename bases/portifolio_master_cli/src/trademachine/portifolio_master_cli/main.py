"""
Main Entry Point
===============
Orchestrates the PortifolioMaster application, handling configuration loading
and CLI argument parsing.
"""

import argparse
import logging
import sys

from trademachine.portifolio_master_cli.cli import PortifolioCLI, _flag_value
from trademachine.portifoliomaster.core.config import AppConfig
from trademachine.portifoliomaster.core.exceptions import ValidationError
from trademachine.portifoliomaster.utils.logger import (
    LOGGER_NAME,
    configure_console_streams,
    setup_logger,
)

_SUBCOMMANDS = {"inspect", "cache", "config", "adherence", "drawdown"}


def _handle_subcommand(
    cmd: str, rest: list[str], config: AppConfig, cli_app: PortifolioCLI
) -> bool | None:
    """Dispatches top-level subcommands that don't need optimization state.

    Returns:
        False if the subcommand completed with a logical failure (e.g. adherence
        failures). None / True for success. Used by main() to set the exit code.
    """

    if cmd == "cache":
        sub = rest[0] if rest else ""
        args = rest[1:]
        cache_path = _flag_value(args, "--cache-path") or config.cache_path

        if sub == "info":
            cli_app.cache_info(cache_path=cache_path)
        elif sub == "rebuild":
            directory = next((a for a in args if not a.startswith("--")), None)
            if not directory:
                print(
                    "Usage: portifoliomaster cache rebuild <directory> [--cache-path PATH]"
                )
                sys.exit(1)
            cli_app.cache_rebuild(directory, cache_path=cache_path)
        elif sub == "clear":
            cli_app.cache_clear(cache_path=cache_path)
        else:
            print("cache subcommands:  info | rebuild <dir> | clear")
            sys.exit(1)

    elif cmd == "config":
        sub = rest[0] if rest else ""
        config_path = _flag_value(rest[1:], "--config") or "config.json"

        if sub == "show":
            cli_app.config_show(config_path)
        elif sub == "validate":
            cli_app.config_validate(config_path)
        else:
            print("config subcommands:  show | validate")
            sys.exit(1)

    elif cmd == "inspect":
        sub = rest[0] if rest else ""
        rest2 = rest[1:]

        if sub == "correlations":
            period = _flag_value(rest2, "--corr-period") or config.corr_period
            top_n = int(_flag_value(rest2, "--top") or 10)
            threshold_raw = _flag_value(rest2, "--threshold")
            threshold: float | None = float(threshold_raw) if threshold_raw else None
            cli_app.load_reports()
            cli_app.inspect_correlations(
                period=period, top_n=top_n, threshold=threshold
            )
        elif sub == "strategy":
            name = next((a for a in rest2 if not a.startswith("--")), None)
            if not name:
                print("Usage: portifoliomaster inspect strategy <name> [--chart]")
                sys.exit(1)
            show_chart = "--chart" in rest2
            cli_app.load_reports()
            cli_app.inspect_strategy(name, show_chart=show_chart)
        else:
            print("inspect subcommands:  correlations | strategy <name>")
            sys.exit(1)

    elif cmd == "drawdown":
        sub = rest[0] if rest else ""
        args = rest[1:]
        if sub == "pairing":
            target_raw = _flag_value(args, "--target")
            tick_raw = _flag_value(args, "--tick")
            target_dd = float(target_raw) if target_raw else 4000.0
            lot_tick = float(tick_raw) if tick_raw else 0.1
            apply = "--apply" in args
            cli_app.load_reports()
            cli_app.drawdown_pairing(
                target_dd=target_dd, lot_tick=lot_tick, apply=apply
            )
        else:
            print("drawdown subcommands: pairing [--target N] [--tick X] [--apply]")
            sys.exit(1)

    elif cmd == "adherence":
        mt5_dir = _flag_value(rest, "--mt5-dir") or "tests/reports"
        sqx_dir = _flag_value(rest, "--sqx-dir") or "tests/reports-sqx"
        output_dir = _flag_value(rest, "--output")
        threshold_raw = _flag_value(rest, "--threshold")
        pearson_raw = _flag_value(rest, "--pearson")
        threshold = (
            float(threshold_raw) if threshold_raw else config.adherence_threshold
        )
        pearson_threshold = (
            float(pearson_raw) if pearson_raw else config.adherence_pearson
        )
        open_browser = "--no-browser" not in rest
        quiet = "--quiet" in rest
        all_passed = cli_app.adherence_run(
            mt5_dir=mt5_dir,
            sqx_dir=sqx_dir,
            output_dir=output_dir,
            threshold=threshold,
            pearson_threshold=pearson_threshold,
            open_browser=open_browser,
            quiet=quiet,
        )
        return all_passed

    return None


def validate_cli_args(args):
    """Early validation of logic constraints."""
    if args.min < 1:
        raise ValidationError(
            f"Minimum assets (--min) must be at least 1. Got: {args.min}"
        )
    if args.min > args.max:
        raise ValidationError(
            f"Minimum assets ({args.min}) cannot be greater than Maximum assets ({args.max})."
        )
    if args.corr < -1 or args.corr > 1:
        raise ValidationError(
            f"Correlation threshold (--corr) must be between -1.0 and 1.0. Got: {args.corr}"
        )
    if hasattr(args, "greedy") and args.greedy and not args.optimize:
        raise ValidationError("--greedy requires --optimize.")
    if hasattr(args, "montecarlo") and args.montecarlo is not None:
        if args.montecarlo < 10:
            raise ValidationError(
                f"--montecarlo requires at least 10 iterations. Got: {args.montecarlo}"
            )
        if not args.optimize:
            raise ValidationError("--montecarlo requires --optimize.")


def main():
    """Main execution flow."""
    configure_console_streams()
    config = AppConfig.from_json()
    # Detect --quiet early so the logger is configured correctly before any output
    quiet = "--quiet" in sys.argv
    setup_logger(log_path=config.log_path, quiet=quiet)
    cli_app = PortifolioCLI(default_config=config.model_dump())

    # Intercept help flags and empty arguments to show the professional documentation
    help_triggers = {"-h", "--help", "help"}
    if len(sys.argv) == 1 or any(arg in help_triggers for arg in sys.argv):
        from trademachine.portifoliomaster.utils.help import get_detailed_help

        print(get_detailed_help())
        sys.exit(0)

    # Route subcommands before the main parser to avoid flag conflicts
    if len(sys.argv) > 1 and sys.argv[1] in _SUBCOMMANDS:
        try:
            success = _handle_subcommand(sys.argv[1], sys.argv[2:], config, cli_app)
            if success is False:
                sys.exit(1)
        except Exception as e:
            logging.getLogger(LOGGER_NAME).error(f"Error: {e}", exc_info=True)
            sys.exit(2)
        return

    parser = argparse.ArgumentParser(
        description="PortifolioMaster CLI - MT5 Portfolio Optimization Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Arg definitions
    parser.add_argument("--load", type=str, help="HTML reports folder path")
    parser.add_argument("--list", action="store_true", help="List strategies in memory")
    parser.add_argument(
        "-i", "--interactive", action="store_true", help="Launch interactive shell"
    )
    parser.add_argument(
        "--optimize", action="store_true", help="Run optimization process"
    )
    parser.add_argument(
        "--strats", type=str, help="Filter strategies (comma-separated names)"
    )
    parser.add_argument("--min", type=int, default=config.min_assets)
    parser.add_argument("--max", type=int, default=config.max_assets)
    parser.add_argument("--top", type=int, default=config.top_n)
    parser.add_argument("--corr", type=float, default=config.max_corr)
    parser.add_argument(
        "--corr-period",
        type=str,
        choices=["H", "D", "W", "M"],
        default=config.corr_period,
    )
    parser.add_argument(
        "--rank", type=str, choices=["RetDD", "NetProfit"], default=config.rank_by
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=config.num_workers,
        help="Number of parallel workers (0 = auto-detect all CPUs, 1 = single process)",
    )
    parser.add_argument(
        "--save-trades",
        type=str,
        help="Export best portfolio trades to a file (extension .csv or .parquet determines format)",
    )
    parser.add_argument(
        "--print",
        action="store_true",
        default=config.print_results,
        help="Print results table",
    )
    parser.add_argument(
        "--output",
        nargs="?",
        const="",
        default=config.output_dir,
        metavar="DIR",
        help=(
            "Save all outputs to a directory (default: auto-generates a timestamped folder). "
            "Without a value, auto-generates a timestamped folder in the current directory "
            "(e.g. run_2026-03-19_17-08). "
            "With a value, uses the specified path."
        ),
    )
    parser.add_argument(
        "--import-p", type=str, help="Import and analyze saved portfolio JSON"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress INFO output on the console (errors and warnings still shown)",
    )
    parser.add_argument(
        "--greedy",
        action="store_true",
        help="Greedy forward-selection: expand best seed portfolio one strategy at a time",
    )
    parser.add_argument(
        "--date-initial",
        type=str,
        default=None,
        help="Start date for trade history filter (format: YYYY-MM-DD)",
    )
    parser.add_argument(
        "--date-final",
        type=str,
        default=None,
        help="End date for trade history filter (format: YYYY-MM-DD)",
    )
    parser.add_argument(
        "--filter",
        type=float,
        default=0.0,
        help="Minimum value for the ranking metric (RetDD or NetProfit). Portfolios below this threshold are skipped.",
    )
    parser.add_argument(
        "--montecarlo",
        nargs="?",
        const=1000,
        default=None,
        type=int,
        metavar="N",
        help=(
            "Run Monte Carlo simulation on the best portfolio after optimization. "
            "Shuffles trade order N times (default: 1000) to estimate drawdown distribution. "
            "Requires --optimize."
        ),
    )

    args = parser.parse_args()

    try:
        validate_cli_args(args)

        if args.interactive:
            cli_app.start_interactive_shell(default_csv_cols=config.csv_columns)
            return

        # Load strategies
        if args.load:
            cli_app.load_reports(args.load)
        elif not cli_app.loaded_expert_names:
            cli_app.load_reports()

        if args.import_p:
            cli_app.import_saved_portfolio(args.import_p, plot_after_load=True)
            return

        if args.list:
            cli_app.list_loaded_strategies()

        if args.optimize:
            strategy_filter = (
                [s.strip() for s in args.strats.split(",")]
                if args.strats and args.strats.lower() != "all"
                else None
            )
            found = cli_app.run_optimization(
                min_assets=args.min,
                max_assets=args.max,
                top_n=args.top,
                include_strats=strategy_filter,
                save_trades_prefix=args.save_trades,
                show_terminal=args.print and not args.quiet,
                rank_by=args.rank,
                max_correlation=args.corr,
                corr_period=args.corr_period,
                output_dir=args.output,
                csv_columns=config.csv_columns,
                num_workers=args.workers,
                greedy=args.greedy,
                date_initial=args.date_initial,
                date_final=args.date_final,
                min_metric=args.filter,
                corr_filter_batch_size=config.corr_filter_batch_size,
                matrix_algebra_batch_size=config.matrix_algebra_batch_size,
                montecarlo=args.montecarlo,
            )
            if not found:
                sys.exit(1)

    except ValidationError as e:
        logging.getLogger(LOGGER_NAME).error(f"Argument Error: {e}")
        sys.exit(2)
    except Exception as e:
        logging.getLogger(LOGGER_NAME).error(f"Unexpected crash: {e}", exc_info=True)
        sys.exit(2)


if __name__ == "__main__":
    main()
