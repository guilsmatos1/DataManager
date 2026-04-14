"""
IO Commands Module
==================
Import, export, and output functionality for PortfolioCLI.
"""

import json
import logging
import os
from typing import TYPE_CHECKING, Any

import polars as pl
from trademachine.core.logger import LOGGER_NAME
from trademachine.portfoliomaster.public import (
    OptimizationOutputService,
    generate_montecarlo_report_html,
    plot_portfolio_equity,
)

logger = logging.getLogger(LOGGER_NAME)


class IOMixin:
    """Import/export and output functionality for PortfolioCLI."""

    if TYPE_CHECKING:
        portfolio_manager: Any

    def _optimization_output_service(self) -> OptimizationOutputService:
        """Returns an output service bound to the current in-memory strategies."""
        from trademachine.portfolio_master_cli import cli as cli_module

        return OptimizationOutputService(
            self.portfolio_manager.strategies,
            self.portfolio_manager.strategy_lots,
            save_portfolio_trades=self._save_best_portfolio_trades,
            report_generator=cli_module.generate_portfolio_report_html,
        )

    @staticmethod
    def _ensure_dir(file_path: str):
        """Ensures the directory for a file path exists."""
        directory = os.path.dirname(file_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)

    @staticmethod
    def _suffix_output_path(path: str, suffix: str) -> str:
        """Appends a suffix before the file extension."""
        root, ext = os.path.splitext(path)
        return f"{root}_{suffix}{ext}" if ext else f"{path}_{suffix}"

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

    def _save_output_dir(self, engine, kwargs: dict) -> str:
        """Saves all optimization outputs to a structured directory.

        Generates three files:
          portfolios.json   — all top-N portfolios with metrics + run config
          trades.parquet    — all top-N trades in long format (portfolio_rank column)
          report.html       — interactive Plotly HTML report

        Returns the absolute path of the output directory.
        """
        output_service = self._optimization_output_service()
        final_dir = output_service.save_output_bundle(
            engine.best_portfolios,
            output_dir=kwargs["output_dir"],
            config={
                "rank_by": kwargs.get("rank_by", "RetDD"),
                "max_corr": kwargs.get("max_correlation"),
                "corr_period": kwargs.get("corr_period", "D"),
                "min_assets": kwargs.get("min_assets"),
                "max_assets": kwargs.get("max_assets"),
                "greedy": kwargs.get("greedy", False),
                "genetic": kwargs.get("genetic", False),
                "ga_loop": kwargs.get("ga_loop", 1),
                "ga_population": kwargs.get("ga_population"),
                "ga_generations": kwargs.get("ga_generations"),
                "ga_crossover": kwargs.get("ga_crossover"),
                "ga_mutation": kwargs.get("ga_mutation"),
                "date_initial": kwargs.get("date_initial"),
                "date_final": kwargs.get("date_final"),
                "min_metric": kwargs.get("min_metric", 0.0),
            },
            strategy_names=engine.strategy_names,
            correlation_matrix=engine.correlation_matrix,
            correlation_period=kwargs.get("corr_period", "D"),
        )
        logger.info(f"[output] rank.json → {os.path.join(final_dir, 'rank.json')}")
        logger.info(
            f"[output] portfolios/ → {os.path.join(final_dir, 'portfolios')} "
            f"({len(engine.best_portfolios)} files)"
        )
        logger.info(f"[output] report.html → {os.path.join(final_dir, 'report.html')}")
        logger.info(f"Output directory: {final_dir}")
        return final_dir  # type: ignore[no-any-return]

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
            if name not in self.loaded_expert_names:  # type: ignore[attr-defined]
                self.loaded_expert_names.append(name)  # type: ignore[attr-defined]
            added.append(name)

        if added:
            logger.info(
                f"[import] {len(added)} new strategies added: {', '.join(added)}"
            )
            self._cache_service().persist_manager(  # type: ignore[attr-defined]
                self.portfolio_manager,
                self.loaded_expert_names,  # type: ignore[attr-defined]
            )
        elif lots_updated:
            logger.info("[import] Lot values updated from parquet.")
            self._cache_service().persist_manager(  # type: ignore[attr-defined]
                self.portfolio_manager,
                self.loaded_expert_names,  # type: ignore[attr-defined]
            )
        else:
            logger.info("[import] All strategies already in cache — nothing added.")

        if plot_after_load:
            plot_portfolio_equity(
                tuple(strategy_names),
                self.portfolio_manager.strategies,
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
                tuple(strategy_list),
                self.portfolio_manager.strategies,
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
        from trademachine.portfoliomaster.public import run_montecarlo

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
