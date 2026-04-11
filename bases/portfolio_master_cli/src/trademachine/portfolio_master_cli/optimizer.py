"""
Optimizer Module
================
Portfolio optimization orchestration for PortfolioCLI.
"""

import json
import logging
import os
from typing import TYPE_CHECKING, Any, cast

import polars as pl
from trademachine.core.logger import LOGGER_NAME
from trademachine.portfoliomaster.public import (
    BenchmarkResult,
    BruteForceEngine,
    GeneticEngine,
    ValidationError,
)

logger = logging.getLogger(LOGGER_NAME)


class OptimizerMixin:
    """Portfolio optimization functionality for PortfolioCLI."""

    if TYPE_CHECKING:
        portfolio_manager: Any
        loaded_expert_names: list[str]
        default_config: dict[str, Any]
        _correlation_cache: dict[Any, Any]
        _save_output_dir: Any

    def _build_genetic_engine(
        self, all_trades_long: pl.DataFrame, kwargs: dict
    ) -> GeneticEngine:
        """Constructs the GeneticEngine, reusing cached correlation when possible."""
        corr_period = kwargs.get("corr_period", "D")
        corr_cache_key = self._build_correlation_cache_key(all_trades_long, corr_period)
        correlation_matrix = self._correlation_cache.get(corr_cache_key)
        if correlation_matrix is not None:
            logger.info(f"Using cached correlation matrix (Period: {corr_period})")

        engine = GeneticEngine(
            all_trades_long,
            correlation_period=corr_period,
            correlation_matrix=correlation_matrix,
        )
        if correlation_matrix is None:
            self._correlation_cache[corr_cache_key] = engine.correlation_matrix
        return engine

    def _build_correlation_cache_key(
        self, all_trades_long: pl.DataFrame, corr_period: str
    ) -> tuple:
        """Builds a stable in-process cache key for the current optimization dataset."""
        if all_trades_long.is_empty():
            return (corr_period.upper(), 0)

        summary = (
            all_trades_long.group_by("Strategy")
            .agg(
                pl.len().alias("trade_count"),
                pl.col("Net_Profit").sum().alias("net_profit"),
                pl.col("Net_Profit").abs().sum().alias("gross_abs_profit"),
                pl.col("Horário").min().alias("start"),
                pl.col("Horário").max().alias("end"),
            )
            .sort("Strategy")
        )

        summary_rows = tuple(
            (
                str(name),
                int(trade_count),
                round(float(net_profit), 8),
                round(float(gross_abs_profit), 8),
                str(start),
                str(end),
            )
            for name, trade_count, net_profit, gross_abs_profit, start, end in summary.iter_rows()
        )

        return (
            corr_period.upper(),
            len(all_trades_long),
            str(all_trades_long["Horário"].min()),
            str(all_trades_long["Horário"].max()),
            summary_rows,
        )

    def _build_optimization_engine(
        self, all_trades_long: pl.DataFrame, kwargs: dict
    ) -> BruteForceEngine:
        """Constructs the brute-force engine.

        BruteForceEngine computes its own correlation matrix internally.
        """
        from trademachine.portfolio_master_cli import cli as cli_module

        engine_cls = cast(type[BruteForceEngine], cli_module.BruteForceEngine)
        return engine_cls(
            all_trades_long,
            correlation_period=kwargs.get("corr_period", "D"),
            num_workers=kwargs.get("num_workers", 0),
            corr_filter_batch_size=kwargs.get(
                "corr_filter_batch_size",
                self.default_config.get("corr_filter_batch_size", 10000),
            ),
            matrix_algebra_batch_size=kwargs.get(
                "matrix_algebra_batch_size",
                self.default_config.get("matrix_algebra_batch_size", 1000),
            ),
        )

    def _prepare_optimization_trades(self, kwargs: dict) -> pl.DataFrame:
        """Builds the optimization dataset from current memory and active filters."""
        all_trades_long = self.portfolio_manager.get_all_trades_long()

        if kwargs.get("include_strats") and kwargs.get("exclude_strats"):
            raise ValidationError(
                "--strats and --exclude-strats cannot be used together."
            )

        if kwargs.get("date_initial") or kwargs.get("date_final"):
            all_trades_long = self._apply_date_filter(
                all_trades_long,
                kwargs.get("date_initial"),
                kwargs.get("date_final"),
            )

        if kwargs.get("include_strats"):
            all_trades_long = self._apply_strategy_filter(
                all_trades_long, kwargs["include_strats"], kwargs["min_assets"]
            )

        if kwargs.get("exclude_strats"):
            all_trades_long = self._apply_strategy_exclusion(
                all_trades_long, kwargs["exclude_strats"], kwargs["min_assets"]
            )

        return all_trades_long  # type: ignore[no-any-return]

    def _execute_optimization_engine(
        self, all_trades_long: pl.DataFrame, kwargs: dict
    ) -> BruteForceEngine | GeneticEngine:
        """Runs one optimization cycle and returns the populated engine."""
        if kwargs.get("genetic"):
            engine = self._build_genetic_engine(all_trades_long, kwargs)
            engine.run(
                min_assets=kwargs["min_assets"],
                max_assets=kwargs["max_assets"],
                top_n=kwargs["top_n"],
                rank_by=kwargs["rank_by"],
                max_corr=kwargs["max_correlation"],
                population_size=kwargs.get(
                    "ga_population",
                    self.default_config.get("ga_population", 300),
                ),
                generations=kwargs.get(
                    "ga_generations",
                    self.default_config.get("ga_generations", 100),
                ),
                crossover_prob=kwargs.get(
                    "ga_crossover",
                    self.default_config.get("ga_crossover", 0.7),
                ),
                mutation_prob=kwargs.get(
                    "ga_mutation",
                    self.default_config.get("ga_mutation", 0.2),
                ),
                enrich_details=False,
            )
            return engine

        greedy = kwargs.get("greedy", False)
        engine = self._build_optimization_engine(all_trades_long, kwargs)

        seed_size = kwargs["min_assets"]
        if greedy and kwargs["min_assets"] != kwargs["max_assets"]:
            logger.warning(
                f"--greedy is active: --max ({kwargs['max_assets']}) is ignored. "
                f"Using --min ({seed_size}) as seed size."
            )

        engine.run(
            min_assets=seed_size,
            max_assets=seed_size if greedy else kwargs["max_assets"],
            top_n=kwargs["top_n"],
            rank_by=kwargs["rank_by"],
            max_corr=kwargs["max_correlation"],
            min_metric=kwargs.get("min_metric", 0.0),
        )

        if greedy and engine.best_portfolios:
            seed_combo = engine.best_portfolios[0]["Combo"]
            engine.run_greedy(
                seed_combo=seed_combo,
                rank_by=kwargs["rank_by"],
                max_corr=kwargs["max_correlation"],
            )

        return engine

    def _handle_optimization_results(
        self, engine: BruteForceEngine, kwargs: dict
    ) -> None:
        if not engine.best_portfolios:
            return

        if self._needs_detailed_metrics(kwargs) and hasattr(
            engine, "ensure_detailed_metrics"
        ):
            engine.ensure_detailed_metrics()

        self.last_optimization_results = engine.best_portfolios

        if kwargs.get("show_terminal"):
            engine.print_results(columns=kwargs.get("csv_columns") or None)

        if kwargs.get("save_trades_prefix"):
            self._save_best_portfolio_trades(  # type: ignore[attr-defined]
                engine.best_portfolios, kwargs["save_trades_prefix"]
            )

        if kwargs.get("export_best_json"):
            self._export_to_json(engine.best_portfolios[0], kwargs["export_best_json"])  # type: ignore[attr-defined]

        if kwargs.get("plot_chart"):
            report_path = self._optimization_output_service().generate_report(  # type: ignore[attr-defined]
                engine.best_portfolios,
                open_browser=True,
                strategy_names=engine.strategy_names,
                correlation_matrix=engine.correlation_matrix,
                correlation_period=kwargs.get("corr_period", "D"),
            )
            logger.info(f"Portfolio report saved to: {report_path}")

        if kwargs.get("montecarlo"):
            if kwargs.get("output_dir") is not None:
                from datetime import datetime as _dt

                raw_dir = kwargs["output_dir"]
                _ts = _dt.now().strftime("%Y-%m-%d_%H-%M")
                _out_dir = raw_dir if raw_dir else f"run_{_ts}"
                mc_path = os.path.join(_out_dir, "montecarlo_report.html")
                self._run_montecarlo(  # type: ignore[attr-defined]
                    engine.best_portfolios[0],
                    kwargs["montecarlo"],
                    mc_path,
                    open_browser=False,
                )
            else:
                self._run_montecarlo(  # type: ignore[attr-defined]
                    engine.best_portfolios[0],
                    kwargs["montecarlo"],
                    "montecarlo_report.html",
                    open_browser=True,
                )

        if kwargs.get("output_dir") is not None:
            self._save_output_dir(engine, kwargs)

    @staticmethod
    def _needs_detailed_metrics(kwargs: dict) -> bool:
        """Returns True when the selected outputs need full MT5-style metrics."""
        return bool(
            kwargs.get("show_terminal")
            or kwargs.get("plot_chart")
            or kwargs.get("output_dir") is not None
        )

    @staticmethod
    def _format_duration(seconds: float | None) -> str:
        """Formats a duration in seconds to a short human-readable label."""
        if seconds is None:
            return "N/A"
        total_seconds = max(int(round(seconds)), 0)
        hours, remainder = divmod(total_seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}h {minutes:02d}m {secs:02d}s"
        if minutes > 0:
            return f"{minutes}m {secs:02d}s"
        return f"{secs}s"

    def _print_benchmark_result(self, result: BenchmarkResult) -> None:
        """Prints a concise terminal summary for throughput benchmark runs."""
        from colorama import Fore, Style

        width = getattr(self, "terminal_width", 80)
        sep = f"{Fore.GREEN}{'=' * width}"

        print(f"\n{Fore.CYAN}{Style.BRIGHT}Benchmark Summary{Style.RESET_ALL}")
        print(sep)
        print(
            f"{Fore.CYAN}{'Search space:':<24}{Fore.GREEN}{result.total_combinations:,} combinations"
        )
        print(
            f"{Fore.CYAN}{'Measured window:':<24}{Fore.YELLOW}{result.elapsed_seconds:.2f}s "
            f"{Fore.GREEN}with {result.num_workers} worker(s)"
        )
        print(
            f"{Fore.CYAN}{'Processed in sample:':<24}{Fore.GREEN}{result.processed_combinations:,} combinations"
        )
        print(
            f"{Fore.CYAN}{'  Valid after corr:':<24}{Fore.GREEN}{result.valid_combinations:,} "
            f"{Fore.GREEN}| {Fore.RED}Discarded: {result.discarded_combinations:,}"
        )
        print(
            f"{Fore.CYAN}{'Throughput:':<24}{Fore.YELLOW}{result.combinations_per_second:,.0f} combinations/s"
        )
        print(
            f"{Fore.CYAN}{'Estimated in target:':<24}{Fore.MAGENTA}{result.estimated_combinations_in_target:,} "
            f"{Fore.GREEN}in {self._format_duration(result.target_seconds)}"
        )
        if result.completed_search:
            print(
                f"{Fore.CYAN}{'Estimated completion:':<24}{Fore.GREEN}completed during benchmark "
                f"{Fore.GREEN}({self._format_duration(result.elapsed_seconds)})"
            )
        else:
            print(
                f"{Fore.CYAN}{'Estimated completion:':<24}"
                f"{Fore.YELLOW}{self._format_duration(result.estimated_completion_seconds)}"
            )
        print(f"{sep}\n")

    def run_benchmark(self, **kwargs) -> bool:
        """Measures optimization throughput and extrapolates it to a target time."""
        if not self.loaded_expert_names:
            logger.warning("No strategies loaded for benchmark.")
            return False

        try:
            all_trades_long = self._prepare_optimization_trades(kwargs)
            engine = self._build_optimization_engine(all_trades_long, kwargs)
            result = engine.benchmark(
                min_assets=kwargs["min_assets"],
                max_assets=kwargs["max_assets"],
                max_corr=kwargs["max_correlation"],
                sample_seconds=kwargs.get("sample_seconds", 5.0),
                target_seconds=kwargs.get("target_seconds", 600.0),
            )
            self._print_benchmark_result(result)
            return True
        except ValidationError as e:
            logger.error(f"Validation error: {e}")
            return False
        except Exception as e:
            logger.exception(f"Unexpected crash: {e}")
            return False

    def _run_greedy_loops(self, **kwargs) -> bool:
        """Runs greedy optimization in sequential loops, removing winners from cache."""
        from datetime import datetime as dt

        requested_loops = kwargs.get("greedy_loops") or 1
        root_output_dir = kwargs.get("output_dir")
        if not root_output_dir:
            timestamp = dt.now().strftime("%Y-%m-%d_%H-%M")
            root_output_dir = f"run_{timestamp}"
        os.makedirs(root_output_dir, exist_ok=True)

        loop_winners: list[dict] = []
        loop_summary: list[dict] = []

        for loop_idx in range(1, requested_loops + 1):
            if len(self.loaded_expert_names) < kwargs["min_assets"]:
                logger.info(
                    f"Stopping greedy loops at {loop_idx - 1}/{requested_loops}: "
                    f"only {len(self.loaded_expert_names)} strategies remain."
                )
                break

            logger.info(
                f"Greedy loop {loop_idx}/{requested_loops} | "
                f"{len(self.loaded_expert_names)} strategies available"
            )

            try:
                all_trades_long = self._prepare_optimization_trades(kwargs)
            except ValidationError as e:
                logger.info(
                    f"Stopping greedy loops at {loop_idx - 1}/{requested_loops}: {e}"
                )
                break

            if all_trades_long.is_empty():
                logger.info(
                    f"Stopping greedy loops at {loop_idx - 1}/{requested_loops}: no trades remain."
                )
                break

            loop_kwargs = dict(kwargs)
            loop_label = f"loop_{loop_idx:02d}"
            loop_kwargs["output_dir"] = os.path.join(root_output_dir, loop_label)
            if kwargs.get("save_trades_prefix"):
                loop_kwargs["save_trades_prefix"] = self._suffix_output_path(  # type: ignore[attr-defined]
                    kwargs["save_trades_prefix"], loop_label
                )

            engine = self._execute_optimization_engine(all_trades_long, loop_kwargs)
            if not engine.best_portfolios:
                logger.info(
                    f"Stopping greedy loops at {loop_idx - 1}/{requested_loops}: "
                    "no valid portfolio found."
                )
                break

            self._handle_optimization_results(engine, loop_kwargs)

            winner = engine.best_portfolios[0]
            combo = list(winner["Combo"])
            removed = self._remove_selected_strategies(combo)  # type: ignore[attr-defined]
            loop_winners.append(winner)
            loop_summary.append(
                {
                    "loop": loop_idx,
                    "output_dir": os.path.abspath(loop_kwargs["output_dir"]),
                    "selected_strategies": combo,
                    "removed_from_cache": removed,
                    "metrics": {
                        k: (round(v, 4) if isinstance(v, float) else v)
                        for k, v in winner.items()
                        if k != "Combo"
                    },
                    "remaining_strategies": len(self.loaded_expert_names),
                }
            )

        summary_payload = {
            "generated_at": dt.now().isoformat(timespec="seconds"),
            "requested_loops": requested_loops,
            "completed_loops": len(loop_summary),
            "loops": loop_summary,
        }
        summary_path = os.path.join(root_output_dir, "multi_greedy_summary.json")
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary_payload, f, indent=2, ensure_ascii=False)
        logger.info(
            f"[output] multi_greedy_summary.json → {os.path.abspath(summary_path)}"
        )
        logger.info(f"Output directory: {os.path.abspath(root_output_dir)}")

        self.last_optimization_results = loop_winners
        return bool(loop_winners)

    def run_optimization(self, **kwargs) -> bool:
        """Orchestrates the portfolio optimization process.

        Returns:
            True if at least one portfolio was found, False otherwise.
        """
        if not self.loaded_expert_names:
            logger.warning("No strategies loaded for optimization.")
            return False

        try:
            greedy_loops = kwargs.get("greedy_loops") or 1
            if kwargs.get("greedy") and greedy_loops > 1:
                return self._run_greedy_loops(**kwargs)

            all_trades_long = self._prepare_optimization_trades(kwargs)
            engine = self._execute_optimization_engine(all_trades_long, kwargs)

            self._handle_optimization_results(engine, kwargs)
            if kwargs.get("remove_top1_from_cache") and engine.best_portfolios:
                self._remove_selected_strategies(  # type: ignore[attr-defined]
                    list(engine.best_portfolios[0]["Combo"])
                )
            return bool(engine.best_portfolios)

        except ValidationError as e:
            logger.error(str(e))
            return False
        except Exception as e:
            logger.error(f"Unexpected optimization failure: {e}", exc_info=True)
            return False

    def _apply_strategy_filter(
        self, all_trades_long: pl.DataFrame, requested_names: list, min_assets: int
    ) -> pl.DataFrame:
        """Delegates to the portfoliomaster component filter."""
        from trademachine.portfoliomaster.public import (
            filter_trades_by_strategy,
        )

        return filter_trades_by_strategy(  # type: ignore[no-any-return]
            all_trades_long,
            requested_names,
            self.loaded_expert_names,
            min_assets,
        )

    def _apply_strategy_exclusion(
        self, all_trades_long: pl.DataFrame, excluded_names: list, min_assets: int
    ) -> pl.DataFrame:
        """Delegates to the portfoliomaster component exclusion filter."""
        from trademachine.portfoliomaster.public import (
            exclude_strategies_from_trades,
        )

        return exclude_strategies_from_trades(  # type: ignore[no-any-return]
            all_trades_long,
            excluded_names,
            self.loaded_expert_names,
            min_assets,
        )

    def _apply_date_filter(
        self,
        all_trades_long: pl.DataFrame,
        date_initial: str | None,
        date_final: str | None,
    ) -> pl.DataFrame:
        """Delegates to the portfoliomaster component date filter."""
        from trademachine.portfoliomaster.public import (
            filter_trades_by_date,
        )

        return filter_trades_by_date(all_trades_long, date_initial, date_final)  # type: ignore[no-any-return]
