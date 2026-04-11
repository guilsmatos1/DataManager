"""
Pairing Service
===============
Centralizes drawdown pairing calculations, CSV export and in-memory apply logic.
"""

import os
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

import polars as pl
from trademachine.portfoliomaster.services.metrics import compute_vector_metrics
from trademachine.portfoliomaster.services.portfolio import PortfolioManager


@dataclass(slots=True)
class PairingRow:
    name: str
    base_lot: float
    paired_lot: float | None
    orig_dd: float
    paired_dd: float
    paired_profit: float
    diff: float

    def to_record(self) -> dict[str, object]:
        """Converts the row to a serializable dict."""
        return {
            "name": self.name,
            "base_lot": self.base_lot,
            "paired_lot": self.paired_lot,
            "orig_dd": self.orig_dd,
            "paired_dd": self.paired_dd,
            "paired_profit": self.paired_profit,
            "diff": self.diff,
        }


@dataclass(slots=True)
class PairingApplyResult:
    analyzed: int
    changed: int
    unchanged: int


class PairingService:
    """Encapsulates drawdown pairing analysis, export and apply behavior."""

    def __init__(self, target_dd: float = 4000.0, lot_tick: float = 0.1):
        self.target_dd = float(target_dd)
        self.lot_tick = float(lot_tick)

    @property
    def decimals(self) -> int:
        """Returns the display precision derived from lot_tick."""
        normalized = Decimal(str(self.lot_tick)).normalize()
        return max(0, -normalized.as_tuple().exponent)  # type: ignore[operator]

    def analyze(
        self,
        strategy_names: Sequence[str],
        strategies: dict[str, pl.DataFrame],
        strategy_lots: dict[str, float],
    ) -> list[PairingRow]:
        """Builds the drawdown pairing table for the provided strategies."""
        rows: list[PairingRow] = []
        for name in sorted(strategy_names):
            if name not in strategies:
                continue

            df = strategies[name]
            profits = df["Net_Profit"].to_numpy()
            if len(profits) == 0:
                continue

            metrics = compute_vector_metrics(profits)
            orig_dd = metrics["MaxDD"]
            orig_profit = metrics["Profit"]
            base_lot = float(strategy_lots.get(name, 1.0))

            if orig_dd == 0.0:
                rows.append(
                    PairingRow(
                        name=name,
                        base_lot=base_lot,
                        paired_lot=None,
                        orig_dd=orig_dd,
                        paired_dd=0.0,
                        paired_profit=orig_profit,
                        diff=0.0,
                    )
                )
                continue

            ideal_lot = (self.target_dd / orig_dd) * base_lot
            n_ticks = max(1, round(ideal_lot / self.lot_tick))
            paired_lot = PortfolioManager.round_lot(n_ticks * self.lot_tick)
            scale = paired_lot / base_lot

            rows.append(
                PairingRow(
                    name=name,
                    base_lot=base_lot,
                    paired_lot=paired_lot,
                    orig_dd=orig_dd,
                    paired_dd=scale * orig_dd,
                    paired_profit=scale * orig_profit,
                    diff=(scale * orig_dd) - self.target_dd,
                )
            )

        return rows

    def export_report(self, rows: Sequence[PairingRow], report_path: str) -> str:
        """Writes the pairing rows to CSV and returns the absolute output path."""
        report_df = pl.DataFrame([row.to_record() for row in rows]).with_columns(
            [
                pl.col("base_lot").cast(pl.Float64),
                pl.col("paired_lot").cast(pl.Float64),
                pl.col("orig_dd").cast(pl.Float64),
                pl.col("paired_dd").cast(pl.Float64),
                pl.col("paired_profit").cast(pl.Float64),
                pl.col("diff").cast(pl.Float64),
            ]
        )
        abs_report_path = os.path.abspath(report_path)
        os.makedirs(os.path.dirname(abs_report_path) or ".", exist_ok=True)
        report_df.write_csv(abs_report_path)
        return abs_report_path

    def apply(
        self, portfolio_manager: PortfolioManager, rows: Sequence[PairingRow]
    ) -> PairingApplyResult:
        """Applies the paired lots to in-memory strategies and lots metadata."""
        changed = 0
        unchanged = 0

        for row in rows:
            if row.paired_lot is None:
                unchanged += 1
                continue

            scale = row.paired_lot / row.base_lot
            if abs(scale - 1.0) < 1e-9:
                unchanged += 1
                continue

            portfolio_manager.strategies[row.name] = portfolio_manager.strategies[
                row.name
            ].with_columns((pl.col("Net_Profit") * scale).alias("Net_Profit"))
            portfolio_manager.strategy_lots[row.name] = PortfolioManager.round_lot(
                row.paired_lot
            )
            changed += 1

        if changed > 0:
            portfolio_manager._lots_meta = {
                "dd_paired": True,
                "target": self.target_dd,
                "tick": self.lot_tick,
            }

        return PairingApplyResult(
            analyzed=len(rows),
            changed=changed,
            unchanged=unchanged,
        )
