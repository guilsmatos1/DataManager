"""Metrics engine — orchestrates formula calls."""

from __future__ import annotations

from trademachine.metrics.formulas.distribution import (
    deviation as calc_deviation,
)
from trademachine.metrics.formulas.distribution import (
    stability as calc_stability,
)
from trademachine.metrics.formulas.distribution import (
    z_probability as calc_z_probability,
)
from trademachine.metrics.formulas.distribution import (
    z_score as calc_z_score,
)
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
from trademachine.metrics.formulas.risk import (
    expectancy as calc_expectancy,
)
from trademachine.metrics.formulas.risk import (
    r_expectancy as calc_r_expectancy,
)
from trademachine.metrics.formulas.risk import (
    r_expectancy_score as calc_r_expectancy_score,
)
from trademachine.metrics.formulas.risk import (
    sqn as calc_sqn,
)
from trademachine.metrics.formulas.risk import (
    sqn_score as calc_sqn_score,
)
from trademachine.metrics.formulas.streaks import max_consec_losses, max_consec_wins
from trademachine.metrics.formulas.symmetry import (
    nsymmetry as calc_nsymmetry,
)
from trademachine.metrics.formulas.symmetry import (
    symmetry as calc_symmetry,
)
from trademachine.metrics.formulas.symmetry import (
    trades_symmetry as calc_trades_symmetry,
)
from trademachine.metrics.types import (
    EquityPoint,
    MetricsInput,
    MetricsResult,
    TradeRecord,
)
from trademachine.metrics.utils.time import years_between


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

    # ── period bounds ──────────────────────────────────────────────────────────
    if inp.trades:
        period_start = min(t.entry_time for t in inp.trades)
        period_end = max(t.exit_time for t in inp.trades)
        years = years_between(period_start, period_end)
    else:
        period_start = period_end = None
        years = 0.0

    # ── profit ────────────────────────────────────────────────────────────────
    tp = total_profit(ending_capital, initial_capital)
    gp = gross_profit(pnls)
    gl = gross_loss(pnls)
    aw = average_win(pnls)
    al = average_loss(pnls)
    at_ = average_trade(pnls)
    daily = daily_avg_profit(tp, period_start, period_end) if period_start else None
    monthly = monthly_avg_profit(tp, period_start, period_end) if period_start else None
    yearly = yearly_avg_profit(tp, period_start, period_end) if period_start else None

    # ── returns ───────────────────────────────────────────────────────────────
    yar = yearly_avg_return_pct(tp, initial_capital) if period_start else None
    cagr_val = (
        cagr(initial_capital, ending_capital, period_start, period_end)
        if period_start
        else None
    )

    # ── ratios ────────────────────────────────────────────────────────────────
    pf = profit_factor(pnls)
    wp = winning_pct(pnls)
    wl = wins_losses_ratio(pnls)
    pr = payout_ratio(aw, al)

    # ── drawdown ──────────────────────────────────────────────────────────────
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

    # ── streaks ───────────────────────────────────────────────────────────────
    mcw = max_consec_wins(pnls)
    mcl = max_consec_losses(pnls)

    # ── exposure ──────────────────────────────────────────────────────────────
    exp = calc_exposure(inp.trades, period_start, period_end) if period_start else None

    # ── risk ──────────────────────────────────────────────────────────────────
    exp_val = calc_expectancy(pnls)
    re = (
        calc_r_expectancy(pnls, inp.risk_per_trade)
        if inp.risk_per_trade is not None
        else None
    )
    res = (
        calc_r_expectancy_score(pnls, inp.risk_per_trade, years)
        if inp.risk_per_trade is not None
        else None
    )
    sqn_val = calc_sqn(pnls)
    sqn_score_val = calc_sqn_score(pnls, years) if years > 0 else None

    # ── distribution ──────────────────────────────────────────────────────────
    dev = calc_deviation(pnls)
    zs = calc_z_score(pnls)
    zp = calc_z_probability(pnls)
    stab = calc_stability(equity_values)

    # ── symmetry ──────────────────────────────────────────────────────────────
    sym = calc_symmetry(inp.trades)
    tsym = calc_trades_symmetry(inp.trades)
    nsym = calc_nsymmetry(inp.trades)

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
        expectancy=exp_val,
        r_expectancy=re,
        r_expectancy_score=res,
        sqn=sqn_val,
        sqn_score=sqn_score_val,
        deviation=dev,
        z_score=zs,
        z_probability=zp,
        stability=stab,
        symmetry=sym,
        trades_symmetry=tsym,
        nsymmetry=nsym,
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
