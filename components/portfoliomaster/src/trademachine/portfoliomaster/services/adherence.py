"""
Adherence Service
=================
Compares SQX backtests against MT5 backtests to validate strategy adherence.

Pass/fail criteria (two independent gates):
  1. trade_ratio  = sqx_trades / mt5_trades  >= threshold       (hard gate, default 0.80)
  2. pearson      = Pearson correlation of daily P&L             >= pearson_threshold (default 0.85)

Win rate is computed and displayed as informational context but does NOT affect pass/fail.
RetDD is kept as informational context but does NOT affect pass/fail.

Rationale:
  - trade_ratio checks that the entry/exit logic produces roughly the same signals.
  - Pearson on daily P&L is scale-invariant: it measures whether both engines gain/lose
    on the same days, regardless of absolute P&L magnitude differences caused by
    different spread/commission/execution models between MT5 and SQX.
  - RetDD ratios are sensitive to systematic P&L scale differences between engines,
    causing false negatives on good strategies.
"""

import dataclasses
import glob
import logging
import os

import numpy as np
from trademachine.core.logger import LOGGER_NAME
from trademachine.core.metrics import compute_equity_curve
from trademachine.mt5.parser import MT5ReportParser
from trademachine.portfoliomaster.services.metrics import compute_vector_metrics
from trademachine.portfoliomaster.services.portfolio import PortfolioManager
from trademachine.portfoliomaster.utils.sqx_parser import parse_sqx_directory

logger = logging.getLogger(LOGGER_NAME)


@dataclasses.dataclass
class StrategyAdherence:
    name: str
    # Trade counts
    mt5_trades: int
    sqx_trades: int
    trade_ratio: float  # sqx / mt5
    # Win rates (informational)
    mt5_win_rate: float  # % of profitable trades
    sqx_win_rate: float
    win_rate_ratio: float  # sqx / mt5
    # Pearson correlation of daily P&L (decision metric)
    pearson: float
    common_days: int  # number of days used in Pearson computation
    # RetDD (informational only — not used in pass/fail)
    mt5_retdd: float
    sqx_retdd: float
    retdd_ratio: float
    # Other financials (informational)
    mt5_profit: float
    sqx_profit: float
    mt5_maxdd: float
    sqx_maxdd: float
    # Pass/fail
    passes: bool
    # Equity curves for chart
    mt5_equity: np.ndarray
    sqx_equity: np.ndarray
    mt5_timestamps: list


@dataclasses.dataclass
class AdherenceResult:
    strategies: list
    total: int
    passed: int
    failed: int
    pass_rate: float
    threshold: float  # trade_ratio gate
    pearson_threshold: float  # pearson gate


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _win_rate(returns: np.ndarray) -> float:
    """Percentage of trades with Net_Profit >= 0 (MT5 convention)."""
    if len(returns) == 0:
        return 0.0
    return float(np.sum(returns >= 0) / len(returns))


def _parse_date(ts: str) -> str:
    """Extracts YYYY-MM-DD from either '2018-01-11 22:00:00' or '2018.01.11 22:00:00'."""
    return ts[:10].replace(".", "-")


def _daily_pnl(returns: np.ndarray, timestamps: list) -> dict[str, float]:
    """Groups trade returns by calendar date, returning {date_str: sum_pnl}."""
    daily: dict[str, float] = {}
    for ret, ts in zip(returns, timestamps, strict=False):
        date = _parse_date(str(ts))
        daily[date] = daily.get(date, 0.0) + float(ret)
    return daily


def _pearson_daily(
    mt5_daily: dict[str, float],
    sqx_daily: dict[str, float],
) -> tuple[float, int]:
    """Pearson correlation on common trading days.

    Returns:
        (pearson_r, n_common_days)
        pearson_r is 0.0 if fewer than 5 common days exist.
    """
    common = sorted(set(mt5_daily) & set(sqx_daily))
    n = len(common)
    if n < 5:
        return 0.0, n

    a = np.array([mt5_daily[d] for d in common], dtype=np.float64)
    b = np.array([sqx_daily[d] for d in common], dtype=np.float64)

    # np.corrcoef returns NaN if one array has zero variance
    if np.std(a) == 0 or np.std(b) == 0:
        return 0.0, n

    return float(np.corrcoef(a, b)[0, 1]), n


def _load_mt5_strategies(mt5_dir: str) -> tuple[dict, dict]:
    """Parses all MT5 HTML reports.

    Returns:
        (returns_by_name, timestamps_by_name)
    """
    html_files = glob.glob(os.path.join(mt5_dir, "*.html"))
    if not html_files:
        raise ValueError(f"No MT5 HTML reports found in '{mt5_dir}'.")

    parser = MT5ReportParser()
    portfolio_manager = PortfolioManager()

    logger.info(f"[MT5] Parsing {len(html_files)} reports from '{mt5_dir}'...")
    for filepath in sorted(html_files):
        try:
            expert_name = parser.parse_report(filepath)
            deals_df = parser.deals_by_expert[expert_name]
            portfolio_manager.add_strategy(expert_name, deals_df)
        except Exception as e:
            logger.warning(f"Skipped MT5 file '{os.path.basename(filepath)}': {e}")

    returns_by_name: dict[str, np.ndarray] = {}
    timestamps_by_name: dict[str, list] = {}

    for name, df in portfolio_manager.strategies.items():
        returns_by_name[name] = df["Net_Profit"].to_numpy().astype(np.float64)
        timestamps_by_name[name] = df["Horário"].cast(str).to_list()

    logger.info(f"[MT5] {len(returns_by_name)} strategies loaded successfully.")
    return returns_by_name, timestamps_by_name


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_adherence_check(
    mt5_dir: str,
    sqx_dir: str,
    threshold: float = 0.80,
    pearson_threshold: float = 0.85,
) -> AdherenceResult:
    """Compares SQX backtests against MT5 backtests for all matched strategies.

    Pass/fail uses two gates:
      1. trade_ratio  >= threshold         (default 0.80)
      2. pearson      >= pearson_threshold  (default 0.85)

    Args:
        mt5_dir:           Directory with MT5 HTML reports.
        sqx_dir:           Directory with SQX CSV files.
        threshold:         Minimum trade count ratio. Default: 0.80.
        pearson_threshold: Minimum Pearson correlation of daily P&L. Default: 0.85.

    Returns:
        AdherenceResult with per-strategy comparison and aggregate summary.
    """
    mt5_returns, mt5_timestamps = _load_mt5_strategies(mt5_dir)
    sqx_data = parse_sqx_directory(sqx_dir)

    mt5_names = set(mt5_returns.keys())
    sqx_names = set(sqx_data.keys())

    for name in sorted(mt5_names - sqx_names):
        logger.warning(f"[adherence] '{name}' found in MT5 but not in SQX — skipped.")
    for name in sorted(sqx_names - mt5_names):
        logger.warning(f"[adherence] '{name}' found in SQX but not in MT5 — skipped.")

    matched = mt5_names & sqx_names
    logger.info(
        f"[adherence] Comparing {len(matched)} strategies "
        f"(trade>={threshold:.0%}, pearson>={pearson_threshold:.2f})."
    )

    results: list[StrategyAdherence] = []

    for name in sorted(matched):
        mt5_ret = mt5_returns[name]
        sqx_ret, sqx_ts = sqx_data[name]
        mt5_ts = mt5_timestamps.get(name, [])

        # Core metrics (informational)
        mt5_metrics = compute_vector_metrics(mt5_ret)
        sqx_metrics = compute_vector_metrics(sqx_ret)

        mt5_trades = len(mt5_ret)
        sqx_trades = len(sqx_ret)

        # Gate 1: trade count ratio
        trade_ratio = (sqx_trades / mt5_trades) if mt5_trades > 0 else 0.0

        # Gate 2: Pearson correlation on daily P&L
        mt5_daily = _daily_pnl(mt5_ret, mt5_ts)
        sqx_daily = _daily_pnl(sqx_ret, sqx_ts)
        pearson, common_days = _pearson_daily(mt5_daily, sqx_daily)

        # Win rate (informational)
        mt5_win_rate = _win_rate(mt5_ret)
        sqx_win_rate = _win_rate(sqx_ret)
        win_rate_ratio = (sqx_win_rate / mt5_win_rate) if mt5_win_rate > 0 else 0.0

        # RetDD (informational)
        retdd_ratio = (
            sqx_metrics["RetDD"] / mt5_metrics["RetDD"]
            if mt5_metrics["RetDD"] > 0
            else 0.0
        )

        passes = trade_ratio >= threshold and pearson >= pearson_threshold

        results.append(
            StrategyAdherence(
                name=name,
                mt5_trades=mt5_trades,
                sqx_trades=sqx_trades,
                trade_ratio=round(trade_ratio, 4),
                mt5_win_rate=round(mt5_win_rate, 4),
                sqx_win_rate=round(sqx_win_rate, 4),
                win_rate_ratio=round(win_rate_ratio, 4),
                pearson=round(pearson, 4),
                common_days=common_days,
                mt5_retdd=mt5_metrics["RetDD"],
                sqx_retdd=sqx_metrics["RetDD"],
                retdd_ratio=round(retdd_ratio, 4),
                mt5_profit=mt5_metrics["Profit"],
                sqx_profit=sqx_metrics["Profit"],
                mt5_maxdd=mt5_metrics["MaxDD"],
                sqx_maxdd=sqx_metrics["MaxDD"],
                passes=passes,
                mt5_equity=compute_equity_curve(mt5_ret),
                sqx_equity=compute_equity_curve(sqx_ret),
                mt5_timestamps=mt5_ts,
            )
        )

    passed = sum(1 for r in results if r.passes)
    total = len(results)

    return AdherenceResult(
        strategies=results,
        total=total,
        passed=passed,
        failed=total - passed,
        pass_rate=round(passed / total * 100, 2) if total > 0 else 0.0,
        threshold=threshold,
        pearson_threshold=pearson_threshold,
    )


def adherence_result_to_dict(result: AdherenceResult) -> dict:
    """Converts AdherenceResult to a JSON-serializable dict (equity arrays excluded)."""
    import datetime

    return {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "config": {
            "threshold": result.threshold,
            "pearson_threshold": result.pearson_threshold,
        },
        "summary": {
            "total": result.total,
            "passed": result.passed,
            "failed": result.failed,
            "pass_rate": result.pass_rate,
        },
        "passed_strategies": [s.name for s in result.strategies if s.passes],
        "failed_strategies": [s.name for s in result.strategies if not s.passes],
        "strategies": [
            {
                "name": s.name,
                "mt5_trades": s.mt5_trades,
                "sqx_trades": s.sqx_trades,
                "trade_ratio": s.trade_ratio,
                "mt5_win_rate": s.mt5_win_rate,
                "sqx_win_rate": s.sqx_win_rate,
                "win_rate_ratio": s.win_rate_ratio,
                "pearson": s.pearson,
                "common_days": s.common_days,
                "mt5_retdd": s.mt5_retdd,
                "sqx_retdd": s.sqx_retdd,
                "retdd_ratio": s.retdd_ratio,
                "mt5_profit": s.mt5_profit,
                "sqx_profit": s.sqx_profit,
                "mt5_maxdd": s.mt5_maxdd,
                "sqx_maxdd": s.sqx_maxdd,
                "passes": s.passes,
            }
            for s in result.strategies
        ],
    }
