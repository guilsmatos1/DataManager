import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
from trademachine.core.logger import LOGGER_NAME
from trademachine.tradingmonitor.config import Settings, get_settings
from trademachine.tradingmonitor.db.database import SessionLocal
from trademachine.tradingmonitor.db.models import Backtest, Strategy
from trademachine.tradingmonitor.metrics.calculator import calculate_metrics_from_df
from trademachine.tradingmonitor.metrics.repository import (
    get_backtest_deals,
    get_backtest_equity,
    get_strategy_deals,
    get_strategy_equity_curve,
)
from trademachine.tradingmonitor.utils.notifications import notifier

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


def check_performance_drift(
    strategy_id: str, settings: Settings | None = None
) -> DriftReport | None:
    """Compare live performance against the best available backtest and check risk limits.

    Args:
        strategy_id: The strategy identifier to check.
        settings: Optional Settings instance for dependency injection (testing).
                 If not provided, uses the cached production settings.
    """
    # We always check VaR even if drift alerts are disabled, as it's a hard risk limit
    resolved_settings = settings or globals()["settings"]

    db = SessionLocal()
    try:
        strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()

        # VaR limit from config (env var VAR_95_THRESHOLD)
        var_limit = resolved_settings.var_95_threshold

        # 1. Fetch live data
        live_deals = get_strategy_deals(strategy_id)
        live_equity_df = get_strategy_equity_curve(strategy_id)

        if live_deals.empty or live_equity_df.empty:
            return None

        # 2. Risk Check: VaR 95%
        reasons = []
        is_drifting = False

        var_95 = _compute_var(live_equity_df["equity"], percentile=95)
        if var_95 and var_95 * 100 > var_limit:
            is_drifting = True
            reasons.append(
                f"VaR 95% Breach: {var_95 * 100:.2f}% (Limit: {var_limit:.2f}%)"
            )

        # 2b. Drawdown Limit Check (per-strategy hard limit set by user)
        live_metrics = calculate_metrics_from_df(live_deals, live_equity_df)
        if strategy and strategy.max_allowed_drawdown is not None:
            live_dd = live_metrics.get("Max Drawdown (%)", 0) or 0
            limit_pct = float(strategy.max_allowed_drawdown)
            if limit_pct > 0 and live_dd >= limit_pct * DRAWDOWN_WARNING_THRESHOLD:
                is_drifting = True
                pct_used = (live_dd / limit_pct) * 100
                severity = "CRITICAL" if live_dd >= limit_pct else "WARNING"
                reasons.append(
                    f"Drawdown Limit [{severity}]: {live_dd:.1f}% / {limit_pct:.1f}%"
                    f" ({pct_used:.0f}% of limit)"
                )

        # 3. Performance Drift Check (requires backtest)
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

                # Win Rate Drift
                bt_wr = bt_metrics.get("Win Rate (%)", 0)
                live_wr = live_metrics.get("Win Rate (%)", 0)
                if bt_wr > 0:
                    wr_drop = (bt_wr - live_wr) / bt_wr * 100
                    if wr_drop > resolved_settings.drift_win_rate_threshold:
                        is_drifting = True
                        reasons.append(
                            f"Win Rate drop: {wr_drop:.1f}% (BT: {bt_wr:.1f}%, Live: {live_wr:.1f}%)"
                        )

                # Profit Factor Drift
                bt_pf = bt_metrics.get("Profit Factor", 0)
                live_pf = live_metrics.get("Profit Factor", 0)
                if bt_pf > 0:
                    pf_drop = (bt_pf - live_pf) / bt_pf * 100
                    if pf_drop > resolved_settings.drift_profit_factor_threshold:
                        is_drifting = True
                        reasons.append(
                            f"Profit Factor drop: {pf_drop:.1f}% (BT: {bt_pf:.2f}, Live: {live_pf:.2f})"
                        )

                # Drawdown Breach
                bt_dd = bt_metrics.get("Max Drawdown (%)", 0)
                live_dd = live_metrics.get("Max Drawdown (%)", 0)
                if bt_dd > 0:
                    if live_dd > (
                        bt_dd * resolved_settings.drift_max_drawdown_multiplier
                    ):
                        is_drifting = True
                        reasons.append(
                            f"Max Drawdown breach: {live_dd:.1f}% (BT Limit: {bt_dd * resolved_settings.drift_max_drawdown_multiplier:.1f}%)"
                        )

        report = DriftReport(
            strategy_id=strategy_id,
            backtest_id=backtest.id if backtest else None,
            live_trades=len(live_deals),
            backtest_metrics=bt_metrics,
            live_metrics=live_metrics,
            is_drifting=is_drifting,
            reasons=reasons,
        )

        if is_drifting:
            _notify_drift(report)

        return report

    except Exception as e:  # noqa: BLE001
        # Broad catch needed: DB errors (SQLAlchemy), network issues,
        # plus any unexpected errors from calculate_metrics_from_df which
        # itself has resilient plugin handling.
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
