"""Metrics engine — orchestrates formula calls."""

from __future__ import annotations

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

    # drawdown is computed in PR3; placeholders for ratio formulas that need it
    dd_val: float | None = None
    dd_pct_val: float | None = None

    rdd = return_dd_ratio(tp, dd_val) if dd_val is not None else None
    aod = annual_over_maxdd(cagr_val, dd_pct_val)

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
