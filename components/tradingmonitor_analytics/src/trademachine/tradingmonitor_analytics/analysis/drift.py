import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
from trademachine.core.logger import LOGGER_NAME
from trademachine.tradingmonitor_analytics.metrics.calculator import (
    calculate_metrics_from_df,
)
from trademachine.tradingmonitor_analytics.metrics.repository import (
    get_backtest_deals,
    get_backtest_equity,
    get_strategy_deals,
    get_strategy_equity_curve,
)
from trademachine.tradingmonitor_storage.public import (
    Backtest,
    SessionLocal,
    Settings,
    Strategy,
    get_settings,
    notifier,
)

logger = logging.getLogger(LOGGER_NAME)
DRAWDOWN_WARNING_THRESHOLD = 0.8
settings = get_settings()


@dataclass
class DriftReport:
    strategy_id: str
    backtest_id: int | None
    live_trades: int
    backtest_metrics: dict | None
    live_metrics: dict
    is_drifting: bool
    reasons: list[str]


def _compute_var(equity_series: pd.Series, percentile: float = 95) -> float | None:
    """Compute Value at Risk (VaR) from equity series using daily returns."""
    if len(equity_series) < 5:
        return None

    # Calculate daily returns
    daily_equity = equity_series.resample("D").last().ffill().dropna()
    if len(daily_equity) < 2:
        return None

    returns = daily_equity.pct_change().dropna()
    returns = returns[~np.isnan(returns) & ~np.isinf(returns)]

    if len(returns) < 5:
        return None

    # VaR is the negative of the specified percentile of the returns
    var = -np.percentile(returns, 100 - percentile)
    return float(var)


def _check_var_breach(live_equity_df: pd.DataFrame, var_limit: float) -> str | None:
    """Check if VaR 95% exceeds the configured limit."""
    var_95 = _compute_var(live_equity_df["equity"], percentile=95)
    if var_95 and var_95 * 100 > var_limit:
        return f"VaR 95% Breach: {var_95 * 100:.2f}% (Limit: {var_limit:.2f}%)"
    return None


def _check_drawdown_limit(live_metrics: dict, strategy: Strategy | None) -> str | None:
    """Check if live drawdown exceeds the per-strategy hard limit."""
    if not strategy or strategy.max_allowed_drawdown is None:
        return None
    live_dd = live_metrics.get("Drawdown", 0) or 0
    limit_pct = float(strategy.max_allowed_drawdown)
    if limit_pct <= 0 or live_dd < limit_pct * DRAWDOWN_WARNING_THRESHOLD:
        return None
    pct_used = (live_dd / limit_pct) * 100
    severity = "CRITICAL" if live_dd >= limit_pct else "WARNING"
    return (
        f"Drawdown Limit [{severity}]: {live_dd:.1f}% / {limit_pct:.1f}%"
        f" ({pct_used:.0f}% of limit)"
    )


def _check_win_rate_drift(
    live_metrics: dict, bt_metrics: dict, threshold: float
) -> str | None:
    """Check if live win rate dropped beyond threshold vs backtest."""
    bt_wr = bt_metrics.get("Win Rate (%)", 0)
    live_wr = live_metrics.get("Win Rate (%)", 0)
    if bt_wr <= 0:
        return None
    wr_drop = (bt_wr - live_wr) / bt_wr * 100
    if wr_drop > threshold:
        return f"Win Rate drop: {wr_drop:.1f}% (BT: {bt_wr:.1f}%, Live: {live_wr:.1f}%)"
    return None


def _check_profit_factor_drift(
    live_metrics: dict, bt_metrics: dict, threshold: float
) -> str | None:
    """Check if live profit factor dropped beyond threshold vs backtest."""
    bt_pf = bt_metrics.get("Profit Factor", 0)
    live_pf = live_metrics.get("Profit Factor", 0)
    if bt_pf <= 0:
        return None
    pf_drop = (bt_pf - live_pf) / bt_pf * 100
    if pf_drop > threshold:
        return (
            f"Profit Factor drop: {pf_drop:.1f}% (BT: {bt_pf:.2f}, Live: {live_pf:.2f})"
        )
    return None


def _check_drawdown_breach(
    live_metrics: dict, bt_metrics: dict, multiplier: float
) -> str | None:
    """Check if live drawdown exceeds backtest drawdown * multiplier."""
    bt_dd = bt_metrics.get("Drawdown", 0)
    live_dd = live_metrics.get("Drawdown", 0)
    if bt_dd <= 0:
        return None
    limit = bt_dd * multiplier
    if live_dd > limit:
        return f"Drawdown breach: {live_dd:.1f}% (BT Limit: {limit:.1f}%)"
    return None


def check_performance_drift(
    strategy_id: str, settings: Settings | None = None
) -> DriftReport | None:
    """Compare live performance against the best available backtest and check risk limits.

    Args:
        strategy_id: The strategy identifier to check.
        settings: Optional Settings instance for dependency injection (testing).
                 If not provided, uses the cached production settings.
    """
    resolved_settings = settings or globals()["settings"]

    db = SessionLocal()
    try:
        strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()

        live_deals = get_strategy_deals(strategy_id)
        live_equity_df = get_strategy_equity_curve(strategy_id)

        if live_deals.empty or live_equity_df.empty:
            return None

        reasons: list[str] = []

        # Risk checks (always run)
        var_reason = _check_var_breach(
            live_equity_df, resolved_settings.var_95_threshold
        )
        if var_reason:
            reasons.append(var_reason)

        live_metrics = calculate_metrics_from_df(live_deals, live_equity_df)

        dd_reason = _check_drawdown_limit(live_metrics, strategy)
        if dd_reason:
            reasons.append(dd_reason)

        # Performance drift checks (require backtest)
        backtest = None
        bt_metrics = None

        if (
            resolved_settings.enable_drift_alerts
            and len(live_deals) >= resolved_settings.drift_min_trades
        ):
            backtest = (
                db.query(Backtest)
                .filter(
                    Backtest.strategy_id == strategy_id, Backtest.status == "complete"
                )
                .order_by(Backtest.created_at.desc())
                .first()
            )

            if backtest:
                bt_deals = get_backtest_deals(backtest.id)
                bt_equity = get_backtest_equity(backtest.id)
                bt_metrics = calculate_metrics_from_df(bt_deals, bt_equity)

                drift_checks = [
                    _check_win_rate_drift(
                        live_metrics,
                        bt_metrics,
                        resolved_settings.drift_win_rate_threshold,
                    ),
                    _check_profit_factor_drift(
                        live_metrics,
                        bt_metrics,
                        resolved_settings.drift_profit_factor_threshold,
                    ),
                    _check_drawdown_breach(
                        live_metrics,
                        bt_metrics,
                        resolved_settings.drift_max_drawdown_multiplier,
                    ),
                ]
                reasons.extend(r for r in drift_checks if r)

        report = DriftReport(
            strategy_id=strategy_id,
            backtest_id=backtest.id if backtest else None,
            live_trades=len(live_deals),
            backtest_metrics=bt_metrics,
            live_metrics=live_metrics,
            is_drifting=bool(reasons),
            reasons=reasons,
        )

        if report.is_drifting:
            _notify_drift(report)

        return report

    except Exception as e:  # noqa: BLE001
        logger.error(
            "Error checking drift/risk for strategy %s: %s",
            strategy_id,
            e,
            exc_info=True,
        )
        return None
    finally:
        db.close()


def _notify_drift(report: DriftReport) -> None:
    """Send alert via notifier."""
    reasons_text = "\n".join([f"• {r}" for r in report.reasons])
    msg = (
        f"🚨 <b>PERFORMANCE DRIFT DETECTED</b>\n"
        f"Strategy: <code>{report.strategy_id}</code>\n"
        f"Live Trades: {report.live_trades}\n\n"
        f"<b>Issues:</b>\n{reasons_text}\n\n"
        f"Check the dashboard for details."
    )
    notifier.send_message_sync(msg)
