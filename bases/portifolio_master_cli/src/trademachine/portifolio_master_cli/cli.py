"""
CLI Module
==========
Manages the Command Line Interface and user interactions.
"""

import glob
import json
import logging
import os
import shlex

import polars as pl
from colorama import Fore, Style, init
from tqdm import tqdm
from trademachine.core.logger import LOGGER_NAME
from trademachine.mt5.parser import MT5ReportParser
from trademachine.portifoliomaster.core.exceptions import (
    DataError,
    ParserError,
    ValidationError,
)
from trademachine.portifoliomaster.services.adherence import (
    adherence_result_to_dict,
    run_adherence_check,
)
from trademachine.portifoliomaster.services.optimization import BruteForceEngine
from trademachine.portifoliomaster.services.portfolio import PortfolioManager
from trademachine.portifoliomaster.utils.visualizer import (
    generate_adherence_report_html,
    generate_montecarlo_report_html,
    generate_portfolio_report_html,
    plot_portfolio_equity,
)

init(autoreset=True)

logger = logging.getLogger(LOGGER_NAME)


def _flag_value(args: list[str], flag: str) -> str | None:
    """Returns the value after `flag` in args list, or None if not present."""
    for i, arg in enumerate(args):
        if arg == flag and i + 1 < len(args):
            return args[i + 1]
        if arg.startswith(f"{flag}="):
            return arg.split("=", 1)[1]
    return None


class PortifolioCLI:
    """Interface for user interactions via command line or interactive shell."""

    def __init__(self, default_config: dict | None = None):
        self.report_parser = MT5ReportParser()
        self.portfolio_manager = PortfolioManager()
        self.loaded_expert_names: list[str] = []
        self.default_config = default_config or {}
        self.last_optimization_results: list[dict] = []

    def load_reports(self, directory_path: str | None = None, use_cache: bool = True):
        """Loads MT5 reports. Prioritizes root cache."""
        cache_filepath = self.default_config.get("cache_path", "cache.parquet")

        if use_cache and os.path.exists(cache_filepath):
            logger.info(
                f"Loading cached strategies from: {os.path.abspath(cache_filepath)}"
            )
            try:
                cached_df = pl.read_parquet(cache_filepath)
                if "Horário" not in cached_df.columns:
                    raise DataError(
                        "Cache file is incompatible (missing 'Horário' column)."
                    )

                self.loaded_expert_names = [
                    col for col in cached_df.columns if col != "Horário"
                ]
                for name in self.loaded_expert_names:
                    # filter_nulls(0.0): get_returns_matrix() pads every
                    # timestamp across all strategies with 0.0 for periods
                    # where a strategy had no trades. Keeping those zero rows
                    # would inflate Total_Trades with phantom entries.
                    self.portfolio_manager.strategies[name] = (
                        cached_df.select(["Horário", name])
                        .rename({name: "Net_Profit"})
                        .filter(pl.col("Net_Profit") != 0.0)
                    )
                self.portfolio_manager.load_lots_cache(cache_filepath)
                logger.info(
                    f"[OK] {len(self.loaded_expert_names)} strategies loaded from cache."
                )
                return
            except Exception as e:
                logger.warning(f"Cache invalid or incompatible: {e}.")

        if not directory_path:
            logger.error(
                "No cache found and no directory provided to scan for reports."
            )
            return

        if not os.path.exists(directory_path):
            logger.error(f"Directory '{directory_path}' does not exist.")
            return

        report_files = glob.glob(os.path.join(directory_path, "*.html"))
        if not report_files:
            logger.error(f"No MT5 HTML reports found in '{directory_path}'.")
            return

        logger.info(f"Parsing {len(report_files)} reports from {directory_path}...")
        for filepath in tqdm(report_files, desc="Parsing"):
            try:
                expert_name = self.report_parser.parse_report(filepath)
                deals_df = self.report_parser.deals_by_expert[expert_name]
                if self.portfolio_manager.add_strategy(expert_name, deals_df):
                    if expert_name not in self.loaded_expert_names:
                        self.loaded_expert_names.append(expert_name)
            except ParserError as e:
                tqdm.write(f"   - Skipped {os.path.basename(filepath)}: {e}")
            except Exception as e:
                tqdm.write(
                    f"   - Unexpected error parsing {os.path.basename(filepath)}: {e}"
                )

        if self.loaded_expert_names:
            try:
                self.portfolio_manager.get_returns_matrix().write_parquet(
                    cache_filepath
                )
                logger.info(f"Cache saved to {os.path.abspath(cache_filepath)}")
            except Exception as e:
                logger.error(f"Failed to write cache file: {e}")
            self.portfolio_manager.save_lots_cache(cache_filepath)

        logger.info(
            f"Total: {len(self.loaded_expert_names)} strategies successfully loaded."
        )

    def list_loaded_strategies(self):
        """Prints a table of all strategies currently in memory."""
        if not self.loaded_expert_names:
            logger.warning("Memory is empty.")
            return

        header = f"{'Name':<30} | {'Lot':>6} | {'# of Trades':<12} | {'Net Profit':<12} | {'MaxDD':<10} | {'Ret/DD':<8}"
        print(header)
        print("-" * len(header))
        for name in sorted(self.loaded_expert_names):
            metrics = self.portfolio_manager.calculate_strategy_metrics(name)
            lot = self.portfolio_manager.strategy_lots.get(name, 1.0)
            if metrics:
                self._print_strategy_row(name, metrics, lot)

    def _print_strategy_row(self, name: str, metrics: dict, lot: float):
        """Prints a single formatted strategy row."""
        print(
            f"{name[:30]:<30} | "
            f"{lot:>6.2f} | "
            f"{metrics['Trades']:<12} | "
            f"{metrics['Profit']:<12.2f} | "
            f"{metrics['MaxDD']:<10.2f} | "
            f"{metrics['RetDD']:<8.2f}"
        )

    def _handle_optimization_results(
        self, engine: BruteForceEngine, kwargs: dict
    ) -> None:
        if not engine.best_portfolios:
            return

        self.last_optimization_results = engine.best_portfolios

        if kwargs.get("show_terminal"):
            engine.print_results(columns=kwargs.get("csv_columns") or None)

        if kwargs.get("save_trades_prefix"):
            self._save_best_portfolio_trades(
                engine.best_portfolios, kwargs["save_trades_prefix"]
            )

        if kwargs.get("export_best_json"):
            self._export_to_json(engine.best_portfolios[0], kwargs["export_best_json"])

        if kwargs.get("plot_chart"):
            report_path = generate_portfolio_report_html(
                engine.best_portfolios, self.portfolio_manager.strategies
            )
            logger.info(f"Portfolio report saved to: {report_path}")

        if kwargs.get("montecarlo"):
            if kwargs.get("output_dir") is not None:
                from datetime import datetime as _dt

                raw_dir = kwargs["output_dir"]
                _ts = _dt.now().strftime("%Y-%m-%d_%H-%M")
                _out_dir = raw_dir if raw_dir else f"run_{_ts}"
                mc_path = os.path.join(_out_dir, "montecarlo_report.html")
                self._run_montecarlo(
                    engine.best_portfolios[0],
                    kwargs["montecarlo"],
                    mc_path,
                    open_browser=False,
                )
            else:
                self._run_montecarlo(
                    engine.best_portfolios[0],
                    kwargs["montecarlo"],
                    "montecarlo_report.html",
                    open_browser=True,
                )

        if kwargs.get("output_dir") is not None:
            self._save_output_dir(engine, kwargs)

    def run_optimization(self, **kwargs) -> bool:
        """Orchestrates the portfolio optimization process.

        Returns:
            True if at least one portfolio was found, False otherwise.
        """
        if not self.loaded_expert_names:
            logger.warning("No strategies loaded for optimization.")
            return False

        try:
            all_trades_long = self.portfolio_manager.get_all_trades_long()

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

            greedy = kwargs.get("greedy", False)
            engine = BruteForceEngine(
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

            self._handle_optimization_results(engine, kwargs)
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
        """Filters trades to the requested strategy names.

        Raises ValidationError if fewer valid strategies are found than min_assets requires.
        """
        valid_names = [
            strategy_name
            for strategy_name in requested_names
            if strategy_name in self.loaded_expert_names
        ]
        missing = [n for n in requested_names if n not in self.loaded_expert_names]
        if missing:
            logger.warning(
                f"Strategies not found (check spelling): {', '.join(missing)}"
            )
        if len(valid_names) < min_assets:
            raise ValidationError(
                f"Only {len(valid_names)} valid strategies found, but {min_assets} required."
            )
        return all_trades_long.filter(pl.col("Strategy").is_in(valid_names))

    def _apply_date_filter(
        self,
        all_trades_long: pl.DataFrame,
        date_initial: str | None,
        date_final: str | None,
    ) -> pl.DataFrame:
        """Filters trades to the specified date range (inclusive on both ends).

        Accepts dates in YYYY-MM-DD format.
        Raises ValidationError if the resulting DataFrame is empty.
        """
        from datetime import datetime

        mask = pl.lit(True)
        if date_initial:
            start_dt = datetime.strptime(date_initial, "%Y-%m-%d")
            mask = mask & (pl.col("Horário") >= start_dt)
        if date_final:
            end_dt = datetime.strptime(date_final, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59
            )
            mask = mask & (pl.col("Horário") <= end_dt)

        filtered = all_trades_long.filter(mask)

        if filtered.is_empty():
            raise ValidationError(
                f"No trades found in the specified date range "
                f"({date_initial or 'start'} → {date_final or 'end'})."
            )

        original_count = len(all_trades_long)
        filtered_count = len(filtered)
        logger.info(
            f"Date filter applied: {date_initial or 'start'} → {date_final or 'end'} "
            f"| {filtered_count}/{original_count} trades retained."
        )
        return filtered

    def _save_best_portfolio_trades(
        self, portfolios: list[dict], file_path: str
    ) -> int:
        """Exports trades for one or more portfolios to CSV or Parquet.

        When multiple portfolios are provided a 'portfolio_rank' column is added
        so trades from different portfolios can be distinguished.

        Returns the number of rows written.
        """
        multi = len(portfolios) > 1
        all_dfs = []

        for rank, portfolio in enumerate(portfolios, start=1):
            combo = portfolio["Combo"]
            combo_list = (
                [s.strip() for s in combo.split(",")]
                if isinstance(combo, str)
                else list(combo)
            )

            for name in combo_list:
                if name in self.portfolio_manager.strategies:
                    lot = self.portfolio_manager.strategy_lots.get(name, 1.0)
                    df = self.portfolio_manager.strategies[name].with_columns(
                        pl.lit(name).alias("Strategy"),
                        pl.lit(lot).alias("Lot"),
                    )
                    if multi:
                        df = df.with_columns(pl.lit(rank).alias("portfolio_rank"))
                    all_dfs.append(df)

        if not all_dfs:
            logger.warning("No trades found for export.")
            return 0

        portfolio_trades = pl.concat(all_dfs).sort(
            ["portfolio_rank", "Horário"] if multi else ["Horário"]
        )

        # Column order: rank (if multi), timestamp, strategy, profit
        base_cols = ["portfolio_rank"] if multi else []
        remaining = [c for c in portfolio_trades.columns if c not in base_cols]
        portfolio_trades = portfolio_trades.select(base_cols + remaining)

        lower_path = file_path.lower()
        if lower_path.endswith(".parquet"):
            portfolio_trades.write_parquet(file_path)
            logger.info(
                f"Trade history saved to Parquet: {file_path} ({len(portfolio_trades)} rows, {len(portfolios)} portfolio(s))"
            )
        elif lower_path.endswith(".csv"):
            portfolio_trades.write_csv(file_path)
            logger.info(
                f"Trade history saved to CSV: {file_path} ({len(portfolio_trades)} rows, {len(portfolios)} portfolio(s))"
            )
        else:
            final_path = f"{file_path}.csv"
            portfolio_trades.write_csv(final_path)
            logger.info(f"Unknown extension. Defaulting to CSV: {final_path}")

        return len(portfolio_trades)

    def _ensure_dir(self, file_path: str):
        """Ensures the directory for a file path exists."""
        directory = os.path.dirname(file_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)

    def _export_to_json(self, portfolio_result: dict, filename: str):
        """Exports the best portfolio to a JSON file."""
        if not filename.endswith(".json"):
            filename += ".json"
        self._ensure_dir(filename)

        portfolio_name = filename.replace(".json", "")
        export_payload = {
            "name": portfolio_name,
            "strategies": list(portfolio_result["Combo"]),
        }
        try:
            with open(filename, "w") as f:
                json.dump(export_payload, f, indent=4)
            logger.info(f"Portfolio exported to: {filename}")
        except Exception as e:
            logger.error(f"Failed to export JSON: {e}")

    def _compute_weights(self, combo) -> dict[str, float]:
        """Volatility-inverse weights normalised to sum to 1.

        Each strategy is weighted by 1/std(returns). Strategies with zero
        variance (or missing from memory) fall back to equal weight.
        """
        import numpy as np

        strats = list(combo)
        vols = []
        for name in strats:
            if name in self.portfolio_manager.strategies:
                returns = self.portfolio_manager.strategies[name][
                    "Net_Profit"
                ].to_numpy()
                vols.append(float(np.std(returns)) if len(returns) > 0 else 0.0)
            else:
                vols.append(0.0)

        if any(v == 0.0 for v in vols):
            w = round(1.0 / len(strats), 4)
            return {name: w for name in strats}

        inv = [1.0 / v for v in vols]
        total = sum(inv)
        return {
            name: round(iv / total, 4) for name, iv in zip(strats, inv, strict=True)
        }

    def _save_output_dir(self, engine, kwargs: dict) -> str:
        """Saves all optimization outputs to a structured directory.

        Generates three files:
          portfolios.json   — all top-N portfolios with metrics + run config
          trades.parquet    — all top-N trades in long format (portfolio_rank column)
          report.html       — interactive Plotly HTML report

        Returns the absolute path of the output directory.
        """
        from datetime import datetime as dt

        raw_dir: str = kwargs["output_dir"]
        now = dt.now()
        timestamp = now.strftime("%Y-%m-%d_%H-%M")
        output_dir: str = raw_dir if raw_dir else f"run_{timestamp}"
        os.makedirs(output_dir, exist_ok=True)

        # 1. rank.json — all top-N with full metrics and run config
        portfolios_path = os.path.join(output_dir, "rank.json")
        serialized = []
        for i, p in enumerate(engine.best_portfolios):
            combo = p["Combo"]
            entry = {
                "rank": i + 1,
                "strategies": list(combo),
                "lots": {
                    name: self.portfolio_manager.strategy_lots.get(name, 1.0)
                    for name in combo
                },
                "weights": self._compute_weights(combo),
                "metrics": {
                    k: (round(v, 4) if isinstance(v, float) else v)
                    for k, v in p.items()
                    if k != "Combo"
                },
            }
            serialized.append(entry)
        payload = {
            "generated_at": now.isoformat(timespec="seconds"),
            "config": {
                "rank_by": kwargs.get("rank_by", "RetDD"),
                "max_corr": kwargs.get("max_correlation"),
                "corr_period": kwargs.get("corr_period", "D"),
                "min_assets": kwargs.get("min_assets"),
                "max_assets": kwargs.get("max_assets"),
                "greedy": kwargs.get("greedy", False),
                "date_initial": kwargs.get("date_initial"),
                "date_final": kwargs.get("date_final"),
                "min_metric": kwargs.get("min_metric", 0.0),
            },
            "portfolios": serialized,
        }
        with open(portfolios_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        logger.info(f"[output] rank.json → {os.path.abspath(portfolios_path)}")

        # 3. portfolios/ — one parquet per ranked portfolio
        portfolios_dir = os.path.join(output_dir, "portfolios")
        os.makedirs(portfolios_dir, exist_ok=True)
        for i, portfolio in enumerate(engine.best_portfolios, start=1):
            rank_path = os.path.join(portfolios_dir, f"rank_{i:02d}.parquet")
            self._save_best_portfolio_trades([portfolio], rank_path)
        logger.info(
            f"[output] portfolios/ → {os.path.abspath(portfolios_dir)} ({len(engine.best_portfolios)} files)"
        )

        # 4. report.html
        report_path = os.path.join(output_dir, "report.html")
        generate_portfolio_report_html(
            engine.best_portfolios,
            self.portfolio_manager.strategies,
            output_path=report_path,
            open_browser=False,
        )
        logger.info(f"[output] report.html → {os.path.abspath(report_path)}")

        logger.info(f"Output directory: {os.path.abspath(output_dir)}")
        return os.path.abspath(output_dir)

    def import_saved_portfolio(self, json_filepath: str, plot_after_load: bool = False):
        """Loads a previously exported portfolio file and optionally plots it.

        Accepts three formats:
          - portfolios/rank_XX.parquet: adds new strategies to memory and updates cache.
          - rank.json  (output of --output): top-ranked portfolio is loaded.
          - legacy export JSON: {"name": "...", "strategies": [...]}.
        """
        if not os.path.exists(json_filepath):
            logger.error(f"File not found: {json_filepath}")
            return
        try:
            if json_filepath.lower().endswith(".parquet"):
                self._import_from_parquet(json_filepath, plot_after_load)
            else:
                self._import_from_json(json_filepath, plot_after_load)
        except Exception as e:
            logger.error(f"Failed to import: {e}")

    def _import_from_parquet(self, filepath: str, plot_after_load: bool) -> None:
        """Imports strategies from a long-format portfolio parquet file.

        Adds only strategies not already present in memory, then rewrites the cache.
        """
        df = pl.read_parquet(filepath)
        if "Strategy" not in df.columns or "Net_Profit" not in df.columns:
            logger.error(
                "Parquet file is missing required columns (Strategy, Net_Profit)."
            )
            return

        strategy_names = sorted(df["Strategy"].unique().to_list())
        cache_filepath = self.default_config.get("cache_path", "cache.parquet")
        added = []
        lots_updated = False

        has_lot_col = "Lot" in df.columns
        for name in strategy_names:
            # Always update lot from parquet if available — even for existing strategies
            if has_lot_col:
                lot_vals = (
                    df.filter(pl.col("Strategy") == name).select("Lot").drop_nulls()
                )
                if len(lot_vals) > 0:
                    lot_median = lot_vals["Lot"].median()
                    if lot_median is not None:
                        new_lot = float(lot_median)  # type: ignore[arg-type]
                        if self.portfolio_manager.strategy_lots.get(name) != new_lot:
                            self.portfolio_manager.strategy_lots[name] = new_lot
                            lots_updated = True

            if name in self.portfolio_manager.strategies:
                logger.info(f"[import] '{name}' already in cache — skipped.")
                continue
            strat_df = (
                df.filter(pl.col("Strategy") == name)
                .select(["Horário", "Net_Profit"])
                .sort("Horário")
            )
            self.portfolio_manager.strategies[name] = strat_df
            if name not in self.loaded_expert_names:
                self.loaded_expert_names.append(name)
            added.append(name)

        if added:
            logger.info(
                f"[import] {len(added)} new strategies added: {', '.join(added)}"
            )
            try:
                self.portfolio_manager.get_returns_matrix().write_parquet(
                    cache_filepath
                )
                logger.info(f"Cache updated: {os.path.abspath(cache_filepath)}")
            except Exception as e:
                logger.error(f"Failed to update cache: {e}")
            self.portfolio_manager.save_lots_cache(cache_filepath)
        elif lots_updated:
            logger.info("[import] Lot values updated from parquet.")
            self.portfolio_manager.save_lots_cache(cache_filepath)
        else:
            logger.info("[import] All strategies already in cache — nothing added.")

        if plot_after_load:
            plot_portfolio_equity(
                tuple(strategy_names), self.portfolio_manager.strategies
            )

    def _import_from_json(self, filepath: str, plot_after_load: bool) -> None:
        """Imports a portfolio from rank.json or legacy export JSON."""
        with open(filepath) as f:
            data = json.load(f)

        # rank.json: {"portfolios": [{"rank": 1, "strategies": [...], "metrics": {...}}, ...]}
        if "portfolios" in data:
            portfolios = data["portfolios"]
            if not portfolios:
                logger.error("No portfolios found in file.")
                return
            best = min(portfolios, key=lambda p: p.get("rank", 1))
            strategy_list = best["strategies"]
            label = f"rank #{best.get('rank', 1)}"
        else:
            strategy_list = data["strategies"]
            label = data.get("name", filepath)

        missing = [
            name
            for name in strategy_list
            if name not in self.portfolio_manager.strategies
        ]
        if missing:
            logger.error(f"Missing strategies in memory: {missing}")
            return
        logger.info(f"Imported portfolio: {label} ({len(strategy_list)} strategies)")
        if plot_after_load:
            plot_portfolio_equity(
                tuple(strategy_list), self.portfolio_manager.strategies
            )

    def _run_montecarlo(
        self,
        portfolio: dict,
        n_iterations: int,
        output_path: str = "montecarlo_report.html",
        open_browser: bool = True,
    ) -> None:
        """Runs Monte Carlo simulation on a portfolio and generates an HTML report.

        Extracts the combined trade sequence for all strategies in the portfolio combo,
        then shuffles it N times to estimate drawdown distribution.
        """
        from trademachine.portifoliomaster.services.montecarlo import run_montecarlo

        combo = portfolio.get("Combo", ())
        if isinstance(combo, str):
            combo = tuple(s.strip() for s in combo.split(","))
        else:
            combo = tuple(combo)

        all_dfs = [
            self.portfolio_manager.strategies[name]
            for name in combo
            if name in self.portfolio_manager.strategies
        ]
        if not all_dfs:
            logger.warning("Monte Carlo: no trade data found for portfolio combo.")
            return

        combined = pl.concat(all_dfs).sort("Horário")
        returns = combined["Net_Profit"].to_numpy().astype(float)

        if len(returns) < 2:
            logger.warning("Monte Carlo: not enough trades for simulation.")
            return

        logger.info(
            f"Running Monte Carlo: {n_iterations} iterations on "
            f"{len(returns)} trades from {len(combo)} strategy(ies)..."
        )
        mc_result = run_montecarlo(returns, n_iterations)
        report_path = generate_montecarlo_report_html(
            mc_result, combo, output_path=output_path, open_browser=open_browser
        )
        logger.info(f"Monte Carlo report saved to: {report_path}")

    # ------------------------------------------------------------------
    # cache subcommands
    # ------------------------------------------------------------------

    def cache_info(self, cache_path: str | None = None) -> None:
        """Displays metadata about the current cache file."""
        path = cache_path or self.default_config.get("cache_path", "cache.parquet")
        abs_path = os.path.abspath(path)

        if not os.path.exists(path):
            print(f"No cache found at: {abs_path}")
            return

        size_bytes = os.path.getsize(path)
        size_str = (
            f"{size_bytes / 1_048_576:.1f} MB"
            if size_bytes >= 1_048_576
            else f"{size_bytes / 1024:.1f} KB"
        )
        import time as _time

        modified = _time.strftime(
            "%Y-%m-%d %H:%M", _time.localtime(os.path.getmtime(path))
        )

        try:
            df = pl.read_parquet(path)
            strats = [c for c in df.columns if c != "Horário"]
            n_strats = len(strats)
            if "Horário" in df.columns and n_strats > 0:
                dates = df["Horário"].drop_nulls()
                date_min = str(dates.min())[:10] if len(dates) > 0 else "N/A"
                date_max = str(dates.max())[:10] if len(dates) > 0 else "N/A"
                date_range = f"{date_min} → {date_max}"
            else:
                date_range = "N/A"
        except Exception as e:
            print(f"Cache exists but could not be read: {e}")
            return

        sep = "─" * 44
        print(f"\nCache: {abs_path}")
        print(sep)
        print(f"{'Size:':<16}{size_str}")
        print(f"{'Strategies:':<16}{n_strats}")
        print(f"{'Date range:':<16}{date_range}")
        print(f"{'Modified:':<16}{modified}")

    def cache_rebuild(self, directory: str, cache_path: str | None = None) -> None:
        """Forces re-parse of HTML reports and overwrites the cache."""
        if cache_path:
            self.default_config["cache_path"] = cache_path
        self.loaded_expert_names = []
        self.portfolio_manager = PortfolioManager()
        self.load_reports(directory_path=directory, use_cache=False)

    def cache_clear(self, cache_path: str | None = None) -> None:
        """Deletes the cache file and its lots sidecar."""
        path = cache_path or self.default_config.get("cache_path", "cache.parquet")
        if not os.path.exists(path):
            print(f"Nothing to clear — no cache at: {os.path.abspath(path)}")
            return
        try:
            os.remove(path)
            print(f"Cache deleted: {os.path.abspath(path)}")
        except Exception as e:
            logger.error(f"Failed to delete cache: {e}")
        lots_path = self.portfolio_manager._lots_cache_path(path)
        if os.path.exists(lots_path):
            try:
                os.remove(lots_path)
                print(f"Lots cache deleted: {os.path.abspath(lots_path)}")
            except Exception as e:
                logger.error(f"Failed to delete lots cache: {e}")

    # ------------------------------------------------------------------
    # config subcommands
    # ------------------------------------------------------------------

    def config_show(self, config_path: str = "config.json") -> None:
        """Displays the active configuration."""
        from trademachine.portifoliomaster.core.config import AppConfig

        cfg = AppConfig.from_json(config_path)
        src = "config.json" if os.path.exists(config_path) else "defaults"

        sep = "─" * 44
        print(f"\nActive configuration  (source: {src})")
        print(sep)
        for field, value in cfg.model_dump().items():
            print(f"  {field:<32}{value}")

    def config_validate(self, config_path: str = "config.json") -> None:
        """Validates config.json and reports any errors."""
        import json

        from pydantic import ValidationError as PydanticValidationError
        from trademachine.portifoliomaster.core.config import AppConfig

        abs_path = os.path.abspath(config_path)
        if not os.path.exists(config_path):
            print(f"No config.json found at: {abs_path}")
            print("Default values will be used on next run.")
            return

        try:
            with open(config_path, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"[INVALID JSON] {abs_path}")
            print(f"  {e}")
            return

        try:
            AppConfig(**data)
            print(f"[OK] {abs_path}")
            print("  All fields are valid.")
        except PydanticValidationError as e:
            print(f"[INVALID] {abs_path}")
            for err in e.errors():
                field = " → ".join(str(loc) for loc in err["loc"])
                print(f"  {field}: {err['msg']}")

    # ------------------------------------------------------------------
    # drawdown subcommands
    # ------------------------------------------------------------------

    def drawdown_pairing(
        self, target_dd: float = 4000.0, lot_tick: float = 0.1, apply: bool = False
    ) -> None:
        """Calculates the optimal lot size per strategy to match the target drawdown.

        For each loaded strategy, reads the actual lot used in the backtest (from the
        Volume column, persisted in cache_lots.json) and computes the absolute lot
        (rounded to the nearest lot_tick) whose drawdown is closest to target_dd.

        With apply=True, scales every strategy's Net_Profit history by the computed
        factor (paired_lot / base_lot), updates strategy_lots, and rewrites the cache
        so that all downstream commands (--list, --optimize, etc.) see the normalised
        values.

        Args:
            target_dd: Desired maximum drawdown in account currency (default: 4000).
            lot_tick:  Minimum lot increment of the instrument (e.g. 0.1).
            apply:     If True, persist the scaled values to memory and cache.
        """
        if not self._ensure_loaded():
            return

        # Guard: refuse to apply if already applied to prevent double-scaling
        if apply and self.portfolio_manager._lots_meta.get("dd_paired"):
            prev_target = self.portfolio_manager._lots_meta.get("target", "?")
            prev_tick = self.portfolio_manager._lots_meta.get("tick", "?")
            print(
                f"[!] DD Pairing already applied (target={prev_target}, tick={prev_tick}). "
                "Run 'cache rebuild <dir>' to reset before applying again."
            )
            return

        import math

        from trademachine.portifoliomaster.services.metrics import (
            compute_vector_metrics,
        )

        # Determine display precision from lot_tick
        if lot_tick >= 1.0:
            decimals = 0
        else:
            decimals = max(1, -int(math.floor(math.log10(lot_tick))))

        has_lots = bool(self.portfolio_manager.strategy_lots)
        if not has_lots:
            logger.warning(
                "Lot data not available (cache_lots.json missing). "
                "Reload via --load <dir> to extract lots from HTML reports. "
                "Falling back to base lot = 1.0 for all strategies."
            )

        rows: list[dict[str, object]] = []
        for name in sorted(self.loaded_expert_names):
            if name not in self.portfolio_manager.strategies:
                continue
            df = self.portfolio_manager.strategies[name]
            profits = df["Net_Profit"].to_numpy()
            if len(profits) == 0:
                continue

            metrics = compute_vector_metrics(profits)
            orig_dd = metrics["MaxDD"]
            orig_profit = metrics["Profit"]
            base_lot = self.portfolio_manager.strategy_lots.get(name, 1.0)

            if orig_dd == 0.0:
                rows.append(
                    {
                        "name": name,
                        "base_lot": base_lot,
                        "paired_lot": None,
                        "orig_dd": orig_dd,
                        "paired_dd": 0.0,
                        "paired_profit": orig_profit,
                        "diff": 0.0,
                    }
                )
                continue

            # Ideal absolute lot = base_lot scaled so that DD reaches target_dd
            ideal_lot = (target_dd / orig_dd) * base_lot
            n_ticks = max(1, round(ideal_lot / lot_tick))
            paired_lot = n_ticks * lot_tick

            # Scale all money values by the ratio of new lot to original lot
            scale = paired_lot / base_lot
            paired_dd = scale * orig_dd
            paired_profit = scale * orig_profit

            rows.append(
                {
                    "name": name,
                    "base_lot": base_lot,
                    "paired_lot": paired_lot,
                    "orig_dd": orig_dd,
                    "paired_dd": paired_dd,
                    "paired_profit": paired_profit,
                    "diff": paired_dd - target_dd,
                }
            )

        if not rows:
            print("No strategies loaded.")
            return

        mode = "  [--apply: cache will be updated]" if apply else ""
        header = (
            f"{'Strategy':<30} | {'Base Lot':>9} | {'Paired Lot':>10} | "
            f"{'DD (orig)':>12} | {'DD (paired)':>12} | {'Diff':>10} | {'Profit (paired)':>15}"
        )
        sep = "─" * len(header)
        print(
            f"\nDrawdown Pairing  |  Target: {target_dd:,.0f}  |  Lot tick: {lot_tick}{mode}"
        )
        print(sep)
        print(header)
        print(sep)

        for row in rows:
            base_str = f"{float(row['base_lot']):.{decimals}f}"  # type: ignore[arg-type]
            lot_str = (
                f"{float(row['paired_lot']):.{decimals}f}"  # type: ignore[arg-type]
                if row["paired_lot"] is not None
                else "N/A"
            )
            print(
                f"{str(row['name'])[:30]:<30} | {base_str:>9} | {lot_str:>10} | "
                f"{float(row['orig_dd']):>12,.2f} | {float(row['paired_dd']):>12,.2f} | "  # type: ignore[arg-type]
                f"{float(row['diff']):>+10,.2f} | {float(row['paired_profit']):>15,.2f}"  # type: ignore[arg-type]
            )

        print(sep)
        print()

        if not apply:
            return

        # ------------------------------------------------------------------
        # Apply: scale Net_Profit history and persist to cache
        # ------------------------------------------------------------------
        cache_filepath = self.default_config.get("cache_path", "cache.parquet")
        applied = 0
        for row in rows:
            name = str(row["name"])
            if row["paired_lot"] is None:
                # MaxDD == 0: nothing to scale
                continue
            scale = float(row["paired_lot"]) / float(row["base_lot"])  # type: ignore[arg-type]
            if abs(scale - 1.0) < 1e-9:
                # Already at target; skip to avoid floating-point drift
                continue
            self.portfolio_manager.strategies[name] = self.portfolio_manager.strategies[
                name
            ].with_columns((pl.col("Net_Profit") * scale).alias("Net_Profit"))
            self.portfolio_manager.strategy_lots[name] = float(row["paired_lot"])  # type: ignore[arg-type]
            applied += 1

        if applied == 0:
            print(
                "[OK] No changes applied — all strategies already at target drawdown."
            )
            return

        try:
            self.portfolio_manager.get_returns_matrix().write_parquet(cache_filepath)
            logger.info(f"Cache updated: {os.path.abspath(cache_filepath)}")
        except Exception as e:
            logger.error(f"Failed to update cache: {e}")

        self.portfolio_manager._lots_meta = {
            "dd_paired": True,
            "target": target_dd,
            "tick": lot_tick,
        }
        self.portfolio_manager.save_lots_cache(cache_filepath)
        print(f"[OK] Scaling applied to {applied} strategy(ies). Cache updated.")

    # ------------------------------------------------------------------
    # inspect subcommands
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> bool:
        """Auto-loads from cache if strategies are not yet in memory."""
        if self.loaded_expert_names:
            return True
        self.load_reports()
        return bool(self.loaded_expert_names)

    def inspect_correlations(
        self, period: str = "D", top_n: int = 10, threshold: float | None = None
    ) -> None:
        """Displays the pairwise correlation matrix between all loaded strategies."""
        if not self._ensure_loaded():
            return

        import numpy as np

        all_trades = self.portfolio_manager.get_all_trades_long()
        strategy_names = sorted(all_trades["Strategy"].unique().to_list())
        n = len(strategy_names)

        corr = self.portfolio_manager.compute_periodic_correlation(
            all_trades, strategy_names, period
        )
        upper_idx = np.triu_indices(n, k=1)
        upper_vals = corr[upper_idx]

        valid = upper_vals[~np.isnan(upper_vals)]
        n_pairs = len(valid)

        sep = "─" * 60
        print(
            f"\nCorrelation Matrix — Period: {period.upper()} | {n} strategies | {n_pairs} pairs"
        )
        print(sep)
        if n_pairs > 0:
            print(
                f"  Mean: {np.nanmean(valid):+.3f}  |  "
                f"Min: {np.nanmin(valid):+.3f}  |  "
                f"Max: {np.nanmax(valid):+.3f}"
            )

        # For small n, show full matrix; for large n, show pairs list
        if n <= 12:
            print()
            col_w = 8
            name_w = max(len(s) for s in strategy_names)
            name_w = min(name_w, 24)
            header = " " * (name_w + 2) + "  ".join(
                s[:col_w].rjust(col_w) for s in strategy_names
            )
            print(header)
            print("─" * len(header))
            for i, row_name in enumerate(strategy_names):
                row_vals = "  ".join(
                    f"{corr[i, j]:+.3f}".rjust(col_w)
                    if not np.isnan(corr[i, j])
                    else "   N/A ".rjust(col_w)
                    for j in range(n)
                )
                print(f"{row_name[:name_w]:<{name_w}}  {row_vals}")
        else:
            # Build sorted pair list
            pairs = []
            for idx in range(len(upper_idx[0])):
                i, j = upper_idx[0][idx], upper_idx[1][idx]
                v = corr[i, j]
                if not np.isnan(v):
                    pairs.append((v, strategy_names[i], strategy_names[j]))
            pairs.sort(reverse=True)

            if threshold is not None:
                filtered = [(v, a, b) for v, a, b in pairs if v >= threshold]
                print(
                    f"\n  Pairs with correlation >= {threshold:.2f}  ({len(filtered)} found)"
                )
                print()
                for v, a, b in filtered:
                    print(f"  {a[:28]:<28} × {b[:28]:<28}  {v:+.3f}")
            else:
                show = min(top_n, len(pairs))
                if show > 0:
                    print(f"\n  TOP {show} most correlated:")
                    for v, a, b in pairs[:show]:
                        print(f"    {a[:28]:<28} × {b[:28]:<28}  {v:+.3f}")
                if len(pairs) > show:
                    print(f"\n  BOTTOM {show} least correlated:")
                    for v, a, b in pairs[-show:]:
                        print(f"    {a[:28]:<28} × {b[:28]:<28}  {v:+.3f}")

        print()

    def inspect_strategy(self, name: str, show_chart: bool = False) -> None:
        """Displays detailed metrics for a single strategy."""
        if not self._ensure_loaded():
            return

        # Fuzzy match: exact first, then case-insensitive substring
        if name not in self.portfolio_manager.strategies:
            name_lower = name.lower()
            candidates = [
                n for n in self.loaded_expert_names if name_lower in n.lower()
            ]
            if not candidates:
                print(f"Strategy '{name}' not found.")
                print(
                    "  Loaded strategies: "
                    + ", ".join(sorted(self.loaded_expert_names)[:10])
                    + ("..." if len(self.loaded_expert_names) > 10 else "")
                )
                return
            if len(candidates) > 1:
                print(f"Ambiguous name '{name}'. Matches:")
                for c in sorted(candidates):
                    print(f"  {c}")
                return
            name = candidates[0]

        from trademachine.portifoliomaster.services.metrics import (
            compute_performance_ratios,
            compute_vector_metrics,
        )

        df = self.portfolio_manager.strategies[name]
        profits = df["Net_Profit"].to_numpy()
        total = len(profits)

        # Use shared metrics
        vm = compute_vector_metrics(profits)
        net_profit = vm["Profit"]
        max_dd = vm["MaxDD"]
        ret_dd = vm["RetDD"]
        pr = compute_performance_ratios(df)
        win_rate = pr["win_percentage"]
        avg_win = pr["avg_win"]
        avg_loss = pr["avg_loss"]
        wl_ratio = pr["win_loss_ratio"]

        # Date range
        dates = df["Horário"].drop_nulls()
        date_from = str(dates.min())[:10] if len(dates) > 0 else "N/A"
        date_to = str(dates.max())[:10] if len(dates) > 0 else "N/A"

        sep = "─" * 44
        print(f"\nStrategy: {name}")
        print(sep)
        print(f"  {'Net Profit:':<22}{net_profit:>14,.2f}")
        print(f"  {'Max Drawdown:':<22}{max_dd:>14,.2f}")
        print(f"  {'Ret/DD:':<22}{ret_dd:>14.2f}")
        print(f"  {'Total Trades:':<22}{total:>14}")
        print(f"  {'Win Rate:':<22}{win_rate:>13.1f}%")
        print(f"  {'Avg Win:':<22}{avg_win:>14,.2f}")
        print(f"  {'Avg Loss:':<22}{avg_loss:>14,.2f}")
        print(f"  {'Win/Loss Ratio:':<22}{wl_ratio:>14.2f}")
        print(f"  {'Date Range:':<22}{date_from} → {date_to}")
        print()

        if show_chart:
            plot_portfolio_equity((name,), self.portfolio_manager.strategies)

    # ------------------------------------------------------------------
    # adherence subcommand
    # ------------------------------------------------------------------

    def adherence_run(
        self,
        mt5_dir: str = "tests/reports",
        sqx_dir: str = "tests/reports-sqx",
        output_dir: str | None = None,
        threshold: float = 0.80,
        pearson_threshold: float = 0.85,
        open_browser: bool = True,
        quiet: bool = False,
    ) -> bool:
        """Compares SQX backtests against MT5 backtests and reports adherence.

        Returns:
            True if all strategies passed, False if any failed.
        """
        import json
        from datetime import datetime as dt
        from pathlib import Path

        result = run_adherence_check(mt5_dir, sqx_dir, threshold, pearson_threshold)

        # Print terminal summary (suppressed in quiet mode)
        if not quiet:
            sep = "─" * 96
            print(
                f"\nAdherence Check — trade>={threshold:.0%}  pearson>={pearson_threshold:.2f}"
            )
            print(sep)
            header = (
                f"{'Strategy':<30} {'MT5':>6} {'SQX':>6} {'Trade%':>8} "
                f"{'Pearson':>8} {'MT5 WR':>8} {'SQX WR':>8} "
                f"{'MT5RDD':>8} {'SQXrdd':>8}  Status"
            )
            print(header)
            print(sep)
            for s in result.strategies:
                pass_str = "PASS" if s.passes else "FAIL"
                print(
                    f"{s.name:<30} {s.mt5_trades:>6} {s.sqx_trades:>6} "
                    f"{s.trade_ratio * 100:>7.1f}% "
                    f"{s.pearson:>8.3f} "
                    f"{s.mt5_win_rate * 100:>7.1f}% "
                    f"{s.sqx_win_rate * 100:>7.1f}% "
                    f"{s.mt5_retdd:>8.2f} {s.sqx_retdd:>8.2f}  {pass_str}"
                )
            print(sep)
            print(
                f"Summary: {result.passed}/{result.total} passed ({result.pass_rate:.1f}% pass rate)"
            )
            print()

        # Output folder — always created (auto-timestamped when not specified)
        now = dt.now()
        timestamp = now.strftime("%Y-%m-%d_%H-%M")
        if output_dir is not None:
            final_out_dir = output_dir if output_dir else f"adherence_{timestamp}"
        else:
            final_out_dir = f"adherence_{timestamp}"
        Path(final_out_dir).mkdir(parents=True, exist_ok=True)

        # JSON output — always saved alongside the HTML
        data = adherence_result_to_dict(result)
        json_filename = "results.json"
        json_path = os.path.join(final_out_dir, json_filename)
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        logger.info(f"[output] {json_filename} → {os.path.abspath(json_path)}")

        # HTML report — always saved in the same folder
        report_filename = "adherence_report.html"
        report_path = os.path.join(final_out_dir, report_filename)
        abs_html = generate_adherence_report_html(result, report_path, open_browser)
        logger.info(f"[output] {report_filename} → {abs_html}")
        logger.info(f"Output directory: {os.path.abspath(final_out_dir)}")

        return result.failed == 0

    def start_interactive_shell(self, default_csv_cols: list[str] | None = None):
        """Enters an interactive loop for command execution using the Typer app."""
        import typer
        from trademachine.portifolio_master_cli.typer_app import app

        banner_art = (
            f"\n{Fore.CYAN}{Style.BRIGHT}"
            r"  _____           _   _  __      _ _        __  __           _            "
            + "\n"
            r"  |  __ \         | | (_)/ _|    | (_)      |  \/  |         | |           "
            + "\n"
            r"  | |__) |__  _ __| |_ _| |_ ___ | |_  ___  | \  / | __ _ ___| |_ ___ _ __ "
            + "\n"
            r"  |  ___/ _ \| '__| __| |  _/ _ \| | |/ _ \ | |\/| |/ _` / __| __/ _ \ '__|"
            + "\n"
            r"  | |  | (_) | |  | |_| | || (_) | | | (_) || |  | | (_| \__ \ ||  __/ |   "
            + "\n"
            r"  |_|   \___/|_|   \__|_|_| \___/|_|_|\___/ |_|  |_|\__,_|___/\__\___|_|   "
        )
        separator = f"{Fore.WHITE}{'═' * 76}"
        title = (
            f"  {' ' * 20}{Fore.CYAN}{Style.BRIGHT}PortfolioMaster"
            f"{Fore.WHITE} - {Fore.GREEN}v0.1.0"
        )
        commands = (
            f"  {Fore.CYAN}optimize{Fore.WHITE} | {Fore.CYAN}adherence{Fore.WHITE} | "
            f"{Fore.CYAN}inspect{Fore.WHITE} | {Fore.CYAN}cache{Fore.WHITE} | "
            f"{Fore.CYAN}config{Fore.WHITE} | {Fore.CYAN}drawdown{Fore.WHITE}"
        )
        hint = f"  {Fore.WHITE}Type {Fore.YELLOW}'help'{Fore.WHITE} for full help or {Fore.YELLOW}'exit'{Fore.WHITE} to quit."
        mode_label = f"  {Fore.YELLOW}● INTERACTIVE MODE ●"
        print(banner_art)
        print(separator)
        print(title)
        print(separator)
        print(mode_label)
        print()
        print(f"  {Style.BRIGHT}COMMANDS:{Style.NORMAL}")
        print(f"  {commands}")
        print()
        print(hint)
        print(separator)

        while True:
            try:
                user_input = input(f"\n{Fore.GREEN}PMaster> {Style.RESET_ALL}").strip()
                if not user_input:
                    continue
                if user_input.lower() in ("exit", "quit", "q"):
                    break

                try:
                    split_args = shlex.split(user_input)
                except ValueError as e:
                    logger.error(f"Invalid command syntax: {e}")
                    continue

                if not split_args:
                    continue

                # Map bare 'help' / 'help <cmd>' to '--help' / '<cmd> --help'
                if split_args[0].lower() == "help":
                    split_args = (
                        split_args[1:] + ["--help"]
                        if len(split_args) > 1
                        else ["--help"]
                    )

                # Run command through Typer
                try:
                    # Using standalone_mode=False to avoid sys.exit() on help or errors
                    app(split_args, standalone_mode=False)
                except (typer.Exit, typer.Abort):
                    continue
                except Exception as e:
                    logger.error(f"Command Error: {e}")

            except KeyboardInterrupt:
                break
            except EOFError:
                break
            except Exception as error:
                logger.error(f"Shell Error: {error}")
