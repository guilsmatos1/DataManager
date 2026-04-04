"""
Optimization Output Service
===========================
Centralizes optimization output artifacts such as rank.json, portfolio parquet
exports and HTML reports.
"""

import json
import os
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

import numpy as np
import polars as pl


class OptimizationOutputService:
    """Builds and persists optimization output artifacts."""

    def __init__(
        self,
        strategies: dict[str, pl.DataFrame],
        strategy_lots: dict[str, float],
        save_portfolio_trades: Callable[[list[dict], str], int],
        report_generator: Callable[..., str],
    ):
        self.strategies = strategies
        self.strategy_lots = strategy_lots
        self.save_portfolio_trades = save_portfolio_trades
        self.report_generator = report_generator

    def compute_weights(self, combo: Sequence[str]) -> dict[str, float]:
        """Returns volatility-inverse weights normalized to 1.0."""
        strats = list(combo)
        vols = []
        for name in strats:
            if name in self.strategies:
                returns = self.strategies[name]["Net_Profit"].to_numpy()
                vols.append(float(np.std(returns)) if len(returns) > 0 else 0.0)
            else:
                vols.append(0.0)

        if any(vol == 0.0 for vol in vols):
            weight = round(1.0 / len(strats), 4)
            return {name: weight for name in strats}

        inv = [1.0 / vol for vol in vols]
        total = sum(inv)
        return {
            name: round(inv_vol / total, 4)
            for name, inv_vol in zip(strats, inv, strict=True)
        }

    def build_rank_payload(
        self,
        portfolios: Sequence[dict[str, Any]],
        config: dict[str, Any],
        generated_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Builds the rank.json payload."""
        now = generated_at or datetime.now()
        serialized = []
        for rank, portfolio in enumerate(portfolios, start=1):
            combo = portfolio["Combo"]
            serialized.append(
                {
                    "rank": rank,
                    "strategies": list(combo),
                    "lots": {
                        name: round(self.strategy_lots.get(name, 1.0), 2)
                        for name in combo
                    },
                    "weights": self.compute_weights(combo),
                    "metrics": {
                        key: (round(value, 4) if isinstance(value, float) else value)
                        for key, value in portfolio.items()
                        if key != "Combo"
                    },
                }
            )

        return {
            "generated_at": now.isoformat(timespec="seconds"),
            "config": config,
            "portfolios": serialized,
        }

    def save_rank_json(
        self, output_dir: str, payload: dict[str, Any]
    ) -> str:
        """Writes rank.json and returns the absolute path."""
        portfolios_path = os.path.join(output_dir, "rank.json")
        with open(portfolios_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return os.path.abspath(portfolios_path)

    def save_portfolio_parquets(
        self, portfolios: Sequence[dict[str, Any]], output_dir: str
    ) -> str:
        """Exports one parquet file per ranked portfolio."""
        portfolios_dir = os.path.join(output_dir, "portfolios")
        os.makedirs(portfolios_dir, exist_ok=True)
        for rank, portfolio in enumerate(portfolios, start=1):
            rank_path = os.path.join(portfolios_dir, f"rank_{rank:02d}.parquet")
            self.save_portfolio_trades([portfolio], rank_path)
        return os.path.abspath(portfolios_dir)

    def generate_report(
        self,
        portfolios: Sequence[dict[str, Any]],
        *,
        output_path: str | None = None,
        open_browser: bool = False,
        strategy_names: list[str] | None = None,
        correlation_matrix: np.ndarray | None = None,
        correlation_period: str = "D",
    ) -> str:
        """Generates the optimization HTML report."""
        return self.report_generator(
            portfolios,
            self.strategies,
            output_path=output_path,
            open_browser=open_browser,
            strategy_names=strategy_names,
            correlation_matrix=correlation_matrix,
            correlation_period=correlation_period,
        )

    def save_output_bundle(
        self,
        portfolios: Sequence[dict[str, Any]],
        *,
        output_dir: str | None,
        config: dict[str, Any],
        strategy_names: list[str] | None,
        correlation_matrix: np.ndarray | None,
        correlation_period: str,
        generated_at: datetime | None = None,
    ) -> str:
        """Writes rank.json, per-rank parquet files and report.html."""
        now = generated_at or datetime.now()
        timestamp = now.strftime("%Y-%m-%d_%H-%M")
        final_output_dir = output_dir or f"run_{timestamp}"
        os.makedirs(final_output_dir, exist_ok=True)

        payload = self.build_rank_payload(portfolios, config, generated_at=now)
        self.save_rank_json(final_output_dir, payload)
        self.save_portfolio_parquets(portfolios, final_output_dir)
        self.generate_report(
            portfolios,
            output_path=os.path.join(final_output_dir, "report.html"),
            open_browser=False,
            strategy_names=strategy_names,
            correlation_matrix=correlation_matrix,
            correlation_period=correlation_period,
        )
        return os.path.abspath(final_output_dir)
