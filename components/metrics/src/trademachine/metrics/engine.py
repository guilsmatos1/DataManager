"""Metrics engine — orchestrates formula calls."""

from __future__ import annotations

from trademachine.metrics.formulas.drawdown import (
    drawdown as calc_drawdown,
)
from trademachine.metrics.formulas.drawdown import (
    drawdown_pct as calc_drawdown_pct,
)
from trademachine.metrics.formulas.drawdown import (
    stagnation_days as calc_stagnation_days,
)
from trademachine.metrics.formulas.drawdown import (
    stagnation_pct as calc_stagnation_pct,
)
from trademachine.metrics.formulas.exposure import exposure as calc_exposure
from trademachine.metrics.formulas.profit import (
    average_loss,
    average_trade,
    average_win,
    daily_avg_profit,
    gross_loss,
    gross_profit,
    monthly_avg_profit,
    total_profit,
    yearly_avg_profit,
)
from trademachine.metrics.formulas.ratios import (
    payout_ratio,
    profit_factor,
    return_dd_ratio,
    winning_pct,
    wins_losses_ratio,
)
from trademachine.metrics.formulas.returns import (
    annual_over_maxdd,
    cagr,
    yearly_avg_return_pct,
)
from trademachine.metrics.formulas.streaks import max_consec_losses, max_consec_wins
from trademachine.metrics.types import (
    EquityPoint,
    MetricsInput,
    MetricsResult,
    TradeRecord,
)


def compute_all(
    trades: list[TradeRecord],
    equity: list[EquityPoint],
    initial_capital: float,
    risk_per_trade: float | None = None,
) -> MetricsResult:
    """Compute every supported metric."""
    inp = MetricsInput(
        trades=trades,
        equity=equity,
        initial_capital=initial_capital,
        risk_per_trade=risk_per_trade,
    )

    pnls = [t.pnl for t in inp.trades]
    equity_values = [e.equity for e in inp.equity]
    equity_timestamps = [e.timestamp for e in inp.equity]
    ending_capital = equity_values[-1] if equity_values else initial_capital

    # ── period bounds from trade timestamps ──────────────────────────────────
    if inp.trades:
        period_start = min(t.entry_time for t in inp.trades)
        period_end = max(t.exit_time for t in inp.trades)
    else:
        period_start = period_end = None

    # ── profit group ─────────────────────────────────────────────────────────
    tp = total_profit(ending_capital, initial_capital)
    gp = gross_profit(pnls)
    gl = gross_loss(pnls)
    aw = average_win(pnls)
    al = average_loss(pnls)
    at_ = average_trade(pnls)
    daily = daily_avg_profit(tp, period_start, period_end) if period_start else None
    monthly = monthly_avg_profit(tp, period_start, period_end) if period_start else None
    yearly = yearly_avg_profit(tp, period_start, period_end) if period_start else None

    # ── returns group ─────────────────────────────────────────────────────────
    yar = yearly_avg_return_pct(tp, initial_capital) if period_start else None
    cagr_val = (
        cagr(initial_capital, ending_capital, period_start, period_end)
        if period_start
        else None
    )

    # ── ratios group ──────────────────────────────────────────────────────────
    pf = profit_factor(pnls)
    wp = winning_pct(pnls)
    wl = wins_losses_ratio(pnls)
    pr = payout_ratio(aw, al)

    # ── drawdown group ────────────────────────────────────────────────────────
    dd_val = calc_drawdown(equity_values)
    dd_pct_val = calc_drawdown_pct(equity_values)
    stag_days = (
        calc_stagnation_days(equity_values, equity_timestamps)
        if equity_timestamps
        else None
    )
    stag_pct = (
        calc_stagnation_pct(equity_values, equity_timestamps)
        if equity_timestamps
        else None
    )

    rdd = return_dd_ratio(tp, dd_val) if dd_val else None
    aod = annual_over_maxdd(cagr_val, dd_pct_val)

    # ── streaks group ─────────────────────────────────────────────────────────
    mcw = max_consec_wins(pnls)
    mcl = max_consec_losses(pnls)

    # ── exposure ──────────────────────────────────────────────────────────────
    exp = calc_exposure(inp.trades, period_start, period_end) if period_start else None

    return MetricsResult(
        total_profit=tp,
        gross_profit=gp,
        gross_loss=gl,
        average_win=aw,
        average_loss=al,
        average_trade=at_,
        daily_avg_profit=daily,
        monthly_avg_profit=monthly,
        yearly_avg_profit=yearly,
        yearly_avg_return_pct=yar,
        cagr=cagr_val,
        annual_over_maxdd=aod,
        profit_factor=pf,
        return_dd_ratio=rdd,
        payout_ratio=pr,
        wins_losses_ratio=wl,
        winning_pct=wp,
        drawdown=dd_val,
        drawdown_pct=dd_pct_val,
        stagnation_days=stag_days,
        stagnation_pct=stag_pct,
        max_consec_wins=mcw,
        max_consec_losses=mcl,
        exposure=exp,
    )


def compute_subset(
    trades: list[TradeRecord],
    equity: list[EquityPoint],
    initial_capital: float,
    metrics: set[str],
    risk_per_trade: float | None = None,
) -> dict[str, float | int | None]:
    """Compute only the requested metric names."""
    result = compute_all(trades, equity, initial_capital, risk_per_trade)
    dumped = result.model_dump()
    return {name: dumped[name] for name in metrics if name in dumped}
