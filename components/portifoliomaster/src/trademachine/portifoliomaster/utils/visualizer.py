"""
Visualizer Module
=================
Handles plotting of equity curves using Plotly.
Uses trade-level data (not period-aggregated) for accurate drawdown display.
"""

import json

import numpy as np
import plotly.graph_objects as go
import polars as pl


def _build_equity_data(
    combo: tuple[str, ...], strategies: dict[str, pl.DataFrame]
) -> tuple[list[tuple], tuple[list, list]]:
    """Builds per-strategy and portfolio equity series from trade-level data.

    Returns:
        strategy_traces: list of (name, timestamps, cumulative_equity)
        portfolio_trace: (timestamps, cumulative_equity)
    """
    strategy_traces = []
    all_dfs = []

    for name in combo:
        if name not in strategies:
            continue
        df = strategies[name].sort("Horário")
        ts = df["Horário"].to_list()
        equity = df["Net_Profit"].cum_sum().to_list()
        strategy_traces.append((name, ts, equity))
        all_dfs.append(df)

    if all_dfs:
        portfolio_df = pl.concat(all_dfs).sort("Horário")
        port_ts = portfolio_df["Horário"].to_list()
        port_equity = portfolio_df["Net_Profit"].cum_sum().to_list()
    else:
        port_ts, port_equity = [], []

    return strategy_traces, (port_ts, port_equity)


def plot_portfolio_equity(
    combo: tuple[str, ...], strategies: dict[str, pl.DataFrame]
) -> None:
    """Generates an interactive Plotly chart for the portfolio and its components."""
    if not combo:
        raise ValueError("combo cannot be empty.")

    strategy_traces, (port_ts, port_equity) = _build_equity_data(combo, strategies)

    fig = go.Figure()

    for name, ts, equity in strategy_traces:
        fig.add_trace(
            go.Scatter(
                x=ts,
                y=equity,
                name=name,
                line=dict(width=1, dash="dot"),
                opacity=0.5,
            )
        )

    fig.add_trace(
        go.Scatter(
            x=port_ts,
            y=port_equity,
            name="PORTFOLIO",
            line=dict(color="royalblue", width=4),
        )
    )

    fig.update_layout(
        title=f"Portfolio Performance: {', '.join(combo)}",
        xaxis_title="Time",
        yaxis_title="Net Profit",
        template="plotly_dark",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )

    fig.show()


def generate_portfolio_report_html(
    portfolios: list[dict],
    strategies: dict[str, pl.DataFrame],
    output_path: str = "portfolio_report.html",
    open_browser: bool = True,
) -> str:
    """Generates a self-contained HTML report with a metrics table and per-portfolio
    equity charts. Clicking a row opens the chart; a back arrow returns to the table.
    Charts are lazily initialized (only rendered when first viewed) to avoid
    Plotly dimension issues with hidden elements.
    Returns the absolute path of the generated file.
    """
    import os
    import webbrowser
    from datetime import datetime
    from pathlib import Path

    # --- Build per-portfolio chart JSON data (lazy init on click) ---
    chart_data_json: list[str] = []
    for idx, portfolio in enumerate(portfolios):
        combo = tuple(portfolio.get("Combo", ()))
        try:
            strategy_traces, (port_ts, port_equity) = _build_equity_data(
                combo, strategies
            )
            if not port_ts:
                raise ValueError("No trade data found for this portfolio.")

            fig = go.Figure()
            for name, ts, equity in strategy_traces:
                fig.add_trace(
                    go.Scatter(
                        x=ts,
                        y=equity,
                        name=name,
                        line=dict(width=2, dash="solid"),
                        opacity=0.7,
                    )
                )
            fig.add_trace(
                go.Scatter(
                    x=port_ts,
                    y=port_equity,
                    name="PORTFOLIO",
                    line=dict(color="white", width=4),
                )
            )
            fig.update_layout(
                title=f"Portfolio #{idx + 1}: {', '.join(combo)}",
                xaxis_title="Time",
                yaxis_title="Net Profit",
                template="plotly_dark",
                hovermode="x unified",
                height=580,
                margin=dict(t=80, b=40, l=60, r=40),
                legend=dict(
                    orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1
                ),
            )
            chart_json = fig.to_json()
        except Exception as exc:
            chart_json = json.dumps({"error": str(exc)})
        chart_data_json.append(chart_json)

    # --- Embed chart data as JSON script tags ---
    chart_data_scripts = "\n".join(
        f'<script type="application/json" id="chart-data-{i}">{d}</script>'
        for i, d in enumerate(chart_data_json)
    )

    # --- Chart view divs (empty containers, filled on first click) ---
    chart_sections_html = "\n".join(
        f'<div id="chart-{i}" class="chart-view">'
        f'<div class="chart-header">'
        f'<button class="back-btn" onclick="showTable()">&#8592; Back to Table</button>'
        f'<span class="chart-title">Portfolio #{i + 1} &mdash; {", ".join(p.get("Combo", ()))}</span>'
        f"</div>"
        f'<div id="chart-body-{i}" class="chart-body"></div>'
        f"</div>"
        for i, p in enumerate(portfolios)
    )

    # --- Table column definitions ---
    columns = [
        ("#", lambda p, i: str(i + 1)),
        ("Strategies", lambda p, i: ", ".join(p.get("Combo", ()))),
        ("# of Trades", lambda p, i: str(p.get("Total_Trades", ""))),
        ("Net Profit", lambda p, i: f"{p.get('Net_Profit', 0):,.2f}"),
        ("Gross Profit", lambda p, i: f"{p.get('Gross_Profit', 0):,.2f}"),
        ("Gross Loss", lambda p, i: f"{p.get('Gross_Loss', 0):,.2f}"),
        ("RetDD", lambda p, i: f"{p.get('RetDD', 0):.2f}"),
        ("Max Drawdown", lambda p, i: f"{p.get('Maximum_Drawdown', 0):,.2f}"),
        ("Rel DD %", lambda p, i: f"{p.get('Relative_Drawdown', 0):.2f}%"),
        ("Profit Factor", lambda p, i: f"{p.get('Profit_Factor', 0):.2f}"),
        ("Win %", lambda p, i: f"{p.get('Win_Percentage', 0):.1f}%"),
        ("Win / Loss", lambda p, i: f"{p.get('Win_Loss_Ratio', 0):.2f}"),
        ("Avg Win", lambda p, i: f"{p.get('Avg_Win', 0):,.2f}"),
        ("Avg Loss", lambda p, i: f"{p.get('Avg_Loss', 0):,.2f}"),
        ("Payoff", lambda p, i: f"{p.get('Payoff', 0):,.2f}"),
        ("Wins", lambda p, i: str(p.get("Winning_Trades_Count", ""))),
        ("Losses", lambda p, i: str(p.get("Losing_Trades_Count", ""))),
        ("Avg Consec. Wins", lambda p, i: f"{p.get('Avg_Consecutive_Wins', 0):.1f}"),
        (
            "Avg Consec. Losses",
            lambda p, i: f"{p.get('Avg_Consecutive_Losses', 0):.1f}",
        ),
    ]

    headers_html = "".join(f"<th>{name}</th>" for name, _ in columns)
    rows_html = "\n".join(
        f'<tr onclick="showChart({i})" title="Click to view equity chart">'
        + "".join(f"<td>{fn(p, i)}</td>" for _, fn in columns)
        + "</tr>"
        for i, p in enumerate(portfolios)
    )

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    n = len(portfolios)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Portfolio Report</title>
<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
{chart_data_scripts}
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: #1a1a2e; color: #e0e0e0; font-family: 'Segoe UI', Arial, sans-serif; min-height: 100vh; }}

/* TABLE VIEW */
#table-view {{ padding: 32px; }}
.report-header {{ margin-bottom: 24px; }}
.report-header h1 {{ font-size: 1.7rem; color: #4fc3f7; font-weight: 600; }}
.report-header .subtitle {{ color: #888; margin-top: 6px; font-size: 0.85rem; }}

.table-wrapper {{ overflow-x: auto; }}
table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; white-space: nowrap; }}
thead th {{
  position: sticky;
  top: 0;
  background: #16213e;
  color: #4fc3f7;
  padding: 10px 12px;
  text-align: left;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  font-size: 0.72rem;
  border-bottom: 2px solid #4fc3f7;
}}
tbody tr {{
  border-bottom: 1px solid #252545;
  cursor: pointer;
  transition: background 0.12s;
}}
tbody tr:hover {{ background: #0f3460 !important; }}
tbody tr:nth-child(odd) {{ background: #1e1e38; }}
tbody tr:nth-child(even) {{ background: #16213e; }}
td {{ padding: 8px 12px; vertical-align: middle; }}
td:first-child {{ font-weight: 700; color: #4fc3f7; text-align: center; width: 36px; }}
td:nth-child(2) {{ color: #ccc; font-size: 0.8rem; max-width: 300px; white-space: normal; word-break: break-word; }}
.click-hint {{ color: #444; font-size: 0.78rem; margin-top: 10px; text-align: right; }}

/* CHART VIEW */
.chart-view {{ display: none; flex-direction: column; height: 100vh; }}
.chart-header {{
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 20px;
  background: #16213e;
  border-bottom: 1px solid #252545;
  flex-shrink: 0;
}}
.back-btn {{
  background: #0f3460;
  color: #4fc3f7;
  border: 1px solid #4fc3f7;
  padding: 7px 18px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.92rem;
  font-weight: 600;
  transition: background 0.15s, color 0.15s;
  white-space: nowrap;
  line-height: 1.4;
}}
.back-btn:hover {{ background: #4fc3f7; color: #1a1a2e; }}
.chart-title {{ color: #ccc; font-size: 0.95rem; }}
.chart-body {{ flex: 1; overflow: hidden; padding: 8px; min-height: 0; }}
</style>
</head>
<body>

<div id="table-view">
  <div class="report-header">
    <h1>Portfolio Optimization Results</h1>
    <div class="subtitle">Generated {generated_at} &mdash; {n} portfolio(s) ranked &mdash; click any row to view equity chart</div>
  </div>
  <div class="table-wrapper">
  <table>
    <thead><tr>{headers_html}</tr></thead>
    <tbody>
{rows_html}
    </tbody>
  </table>
  </div>
  <div class="click-hint">Click any row to view the equity chart &#8594;</div>
</div>

{chart_sections_html}

<script>
var initializedCharts = {{}};

function showChart(idx) {{
  document.getElementById('table-view').style.display = 'none';
  var view = document.getElementById('chart-' + idx);
  view.style.display = 'flex';

  if (!initializedCharts[idx]) {{
    initializedCharts[idx] = true;
    var dataEl = document.getElementById('chart-data-' + idx);
    var chartData = JSON.parse(dataEl.textContent);
    var body = document.getElementById('chart-body-' + idx);

    if (chartData.error) {{
      body.innerHTML = "<p style='color:#e74c3c;padding:20px'>Chart error: " + chartData.error + "</p>";
      return;
    }}

    var layout = Object.assign({{}}, chartData.layout, {{
      autosize: true,
      height: undefined
    }});
    Plotly.newPlot(body, chartData.data, layout, {{responsive: true}});
  }} else {{
    requestAnimationFrame(function() {{
      var plotDiv = document.getElementById('chart-body-' + idx).querySelector('.js-plotly-plot');
      if (plotDiv) Plotly.Plots.resize(plotDiv);
    }});
  }}
}}

function showTable() {{
  document.querySelectorAll('.chart-view').forEach(function(el) {{ el.style.display = 'none'; }});
  document.getElementById('table-view').style.display = 'block';
}}
</script>

</body>
</html>"""

    abs_path = os.path.abspath(output_path)
    Path(abs_path).parent.mkdir(parents=True, exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as fh:
        fh.write(html)

    if open_browser:
        webbrowser.open(f"file://{abs_path}")
    return abs_path


def generate_montecarlo_report_html(
    mc_result,
    combo: tuple[str, ...],
    output_path: str = "montecarlo_report.html",
    open_browser: bool = True,
) -> str:
    """Generates a self-contained HTML Monte Carlo simulation report.

    Args:
        mc_result: MonteCarloResult dataclass from services.montecarlo.run_montecarlo.
        combo: Tuple of strategy names in the portfolio.
        output_path: Destination file path for the HTML report.
        open_browser: Whether to open the report in the default browser.

    Returns:
        Absolute path of the generated HTML file.
    """
    import os
    import webbrowser
    from datetime import datetime
    from pathlib import Path

    s = mc_result.summary
    n_iter = s["n_iterations"]
    n_trades = s["n_trades"]
    combo_label = ", ".join(combo)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # --- Figure 1: Equity Curves ---
    fig_eq = go.Figure()

    # MC curves as a single Scattergl trace with NaN separators (efficient for many curves)
    n_curves, n_pts = mc_result.simulated_equities.shape
    null_col = np.full((n_curves, 1), np.nan)
    with_nans = np.hstack([mc_result.simulated_equities, null_col])
    y_mc = with_nans.ravel().tolist()
    x_row = list(range(n_pts)) + [None]
    x_mc = x_row * n_curves

    fig_eq.add_trace(
        go.Scattergl(
            x=x_mc,
            y=y_mc,
            mode="lines",
            line=dict(color="#4fc3f7", width=0.5),
            opacity=0.05,
            name=f"MC Simulations ({n_iter})",
            showlegend=True,
        )
    )
    fig_eq.add_trace(
        go.Scatter(
            x=list(range(len(mc_result.original_equity))),
            y=mc_result.original_equity.tolist(),
            mode="lines",
            line=dict(color="white", width=3),
            name="Original",
        )
    )
    fig_eq.update_layout(
        title="Equity Curves — Monte Carlo vs Original",
        xaxis_title="Trade #",
        yaxis_title="Cumulative PnL",
        template="plotly_dark",
        height=500,
        margin=dict(t=60, b=40, l=60, r=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )

    # --- Figure 2: MaxDD Distribution ---
    mdd = s["max_dd"]
    fig_mdd = go.Figure()
    fig_mdd.add_trace(
        go.Histogram(
            x=mc_result.max_dd_distribution.tolist(),
            nbinsx=50,
            marker_color="#4fc3f7",
            name="Max DD",
        )
    )
    fig_mdd.update_layout(
        title="Max Drawdown Distribution",
        xaxis_title="Max Drawdown",
        yaxis_title="Count",
        template="plotly_dark",
        height=500,
        margin=dict(t=60, b=40, l=60, r=20),
        shapes=[
            dict(
                type="line",
                x0=mc_result.original_max_dd,
                x1=mc_result.original_max_dd,
                y0=0,
                y1=1,
                yref="paper",
                line=dict(color="white", dash="dash", width=2),
            ),
            dict(
                type="line",
                x0=mdd["median"],
                x1=mdd["median"],
                y0=0,
                y1=1,
                yref="paper",
                line=dict(color="#fdd835", width=2),
            ),
            dict(
                type="line",
                x0=mdd["p5"],
                x1=mdd["p5"],
                y0=0,
                y1=1,
                yref="paper",
                line=dict(color="#ef5350", dash="dash", width=1.5),
            ),
            dict(
                type="line",
                x0=mdd["p95"],
                x1=mdd["p95"],
                y0=0,
                y1=1,
                yref="paper",
                line=dict(color="#ef5350", dash="dash", width=1.5),
            ),
        ],
        annotations=[
            dict(
                x=mc_result.original_max_dd,
                y=1,
                yref="paper",
                text="Original",
                showarrow=False,
                font=dict(color="white", size=11),
                xanchor="left",
            ),
            dict(
                x=mdd["median"],
                y=0.92,
                yref="paper",
                text="Median",
                showarrow=False,
                font=dict(color="#fdd835", size=11),
                xanchor="left",
            ),
            dict(
                x=mdd["p5"],
                y=0.84,
                yref="paper",
                text="P5",
                showarrow=False,
                font=dict(color="#ef5350", size=11),
                xanchor="left",
            ),
            dict(
                x=mdd["p95"],
                y=0.84,
                yref="paper",
                text="P95",
                showarrow=False,
                font=dict(color="#ef5350", size=11),
                xanchor="left",
            ),
        ],
    )

    # --- Figure 3: RetDD Distribution ---
    rdd = s["ret_dd"]
    fig_rdd = go.Figure()
    fig_rdd.add_trace(
        go.Histogram(
            x=mc_result.ret_dd_distribution.tolist(),
            nbinsx=50,
            marker_color="#4fc3f7",
            name="Ret/DD",
        )
    )
    fig_rdd.update_layout(
        title="Return/Drawdown Distribution",
        xaxis_title="Ret/DD",
        yaxis_title="Count",
        template="plotly_dark",
        height=500,
        margin=dict(t=60, b=40, l=60, r=20),
        shapes=[
            dict(
                type="line",
                x0=mc_result.original_ret_dd,
                x1=mc_result.original_ret_dd,
                y0=0,
                y1=1,
                yref="paper",
                line=dict(color="white", dash="dash", width=2),
            ),
            dict(
                type="line",
                x0=rdd["median"],
                x1=rdd["median"],
                y0=0,
                y1=1,
                yref="paper",
                line=dict(color="#fdd835", width=2),
            ),
            dict(
                type="line",
                x0=rdd["p5"],
                x1=rdd["p5"],
                y0=0,
                y1=1,
                yref="paper",
                line=dict(color="#ef5350", dash="dash", width=1.5),
            ),
            dict(
                type="line",
                x0=rdd["p95"],
                x1=rdd["p95"],
                y0=0,
                y1=1,
                yref="paper",
                line=dict(color="#ef5350", dash="dash", width=1.5),
            ),
        ],
        annotations=[
            dict(
                x=mc_result.original_ret_dd,
                y=1,
                yref="paper",
                text="Original",
                showarrow=False,
                font=dict(color="white", size=11),
                xanchor="left",
            ),
            dict(
                x=rdd["median"],
                y=0.92,
                yref="paper",
                text="Median",
                showarrow=False,
                font=dict(color="#fdd835", size=11),
                xanchor="left",
            ),
            dict(
                x=rdd["p5"],
                y=0.84,
                yref="paper",
                text="P5",
                showarrow=False,
                font=dict(color="#ef5350", size=11),
                xanchor="left",
            ),
            dict(
                x=rdd["p95"],
                y=0.84,
                yref="paper",
                text="P95",
                showarrow=False,
                font=dict(color="#ef5350", size=11),
                xanchor="left",
            ),
        ],
    )

    # Serialize charts to JSON
    chart_eq_json = fig_eq.to_json()
    chart_mdd_json = fig_mdd.to_json()
    chart_rdd_json = fig_rdd.to_json()

    # --- Summary table rows ---
    def _fmt(v: float) -> str:
        return f"{v:,.2f}"

    summary_rows = f"""
<tr>
  <td>Max Drawdown</td>
  <td>{_fmt(mc_result.original_max_dd)}</td>
  <td>{_fmt(mdd["mean"])}</td>
  <td>{_fmt(mdd["median"])}</td>
  <td>{_fmt(mdd["p5"])}</td>
  <td>{_fmt(mdd["p95"])}</td>
  <td>{_fmt(mdd["worst"])}</td>
</tr>
<tr>
  <td>Ret/DD</td>
  <td>{_fmt(mc_result.original_ret_dd)}</td>
  <td>{_fmt(rdd["mean"])}</td>
  <td>{_fmt(rdd["median"])}</td>
  <td>{_fmt(rdd["p5"])}</td>
  <td>{_fmt(rdd["p95"])}</td>
  <td>{_fmt(rdd["worst"])}</td>
</tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Monte Carlo Report</title>
<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
<script type="application/json" id="mc-chart-data-0">{chart_eq_json}</script>
<script type="application/json" id="mc-chart-data-1">{chart_mdd_json}</script>
<script type="application/json" id="mc-chart-data-2">{chart_rdd_json}</script>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: #1a1a2e; color: #e0e0e0; font-family: 'Segoe UI', Arial, sans-serif; min-height: 100vh; padding: 32px; }}
.report-header {{ margin-bottom: 24px; }}
.report-header h1 {{ font-size: 1.6rem; color: #4fc3f7; font-weight: 600; }}
.report-header .subtitle {{ color: #888; margin-top: 6px; font-size: 0.85rem; }}
.summary-section {{ margin-bottom: 28px; }}
.summary-section h2 {{ font-size: 1rem; color: #4fc3f7; margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.05em; }}
table {{ border-collapse: collapse; font-size: 0.85rem; white-space: nowrap; }}
thead th {{
  background: #16213e; color: #4fc3f7; padding: 8px 14px;
  text-align: center; font-weight: 600; letter-spacing: 0.04em;
  text-transform: uppercase; font-size: 0.72rem;
  border-bottom: 2px solid #4fc3f7;
}}
thead th:first-child {{ text-align: left; }}
tbody tr {{ border-bottom: 1px solid #252545; }}
tbody tr:nth-child(odd) {{ background: #1e1e38; }}
tbody tr:nth-child(even) {{ background: #16213e; }}
td {{ padding: 8px 14px; text-align: center; }}
td:first-child {{ text-align: left; color: #ccc; font-weight: 600; }}
.tab-nav {{ display: flex; gap: 8px; margin-bottom: 16px; }}
.tab-btn {{
  background: #16213e; color: #aaa; border: 1px solid #252545;
  padding: 8px 20px; border-radius: 6px; cursor: pointer;
  font-size: 0.88rem; font-weight: 500; transition: all 0.15s;
}}
.tab-btn:hover {{ background: #0f3460; color: #4fc3f7; border-color: #4fc3f7; }}
.tab-btn.active {{ background: #0f3460; color: #4fc3f7; border-color: #4fc3f7; font-weight: 700; }}
.mc-tab {{ display: none; }}
.mc-tab.active {{ display: block; }}
.chart-container {{ width: 100%; }}
</style>
</head>
<body>

<div class="report-header">
  <h1>Monte Carlo Simulation Report</h1>
  <div class="subtitle">
    Portfolio: {combo_label} &mdash;
    {n_iter} iterations &mdash;
    {n_trades} trades &mdash;
    Generated {generated_at}
  </div>
</div>

<div class="summary-section">
  <h2>Summary Statistics</h2>
  <table>
    <thead>
      <tr>
        <th>Metric</th>
        <th>Original</th>
        <th>MC Mean</th>
        <th>MC Median</th>
        <th>MC P5</th>
        <th>MC P95</th>
        <th>MC Worst</th>
      </tr>
    </thead>
    <tbody>
      {summary_rows}
    </tbody>
  </table>
</div>

<div class="tab-nav">
  <button class="tab-btn active" onclick="showTab(0)">Equity Curves</button>
  <button class="tab-btn" onclick="showTab(1)">MaxDD Distribution</button>
  <button class="tab-btn" onclick="showTab(2)">RetDD Distribution</button>
</div>

<div id="mc-tab-0" class="mc-tab active"><div id="mc-chart-0" class="chart-container"></div></div>
<div id="mc-tab-1" class="mc-tab"><div id="mc-chart-1" class="chart-container"></div></div>
<div id="mc-tab-2" class="mc-tab"><div id="mc-chart-2" class="chart-container"></div></div>

<script>
var mcInitialized = [false, false, false];

function showTab(idx) {{
  for (var i = 0; i < 3; i++) {{
    document.getElementById('mc-tab-' + i).className = 'mc-tab' + (i === idx ? ' active' : '');
  }}
  document.querySelectorAll('.tab-btn').forEach(function(btn, i) {{
    btn.className = 'tab-btn' + (i === idx ? ' active' : '');
  }});
  if (!mcInitialized[idx]) {{
    initChart(idx);
  }} else {{
    requestAnimationFrame(function() {{
      var plotDiv = document.getElementById('mc-chart-' + idx).querySelector('.js-plotly-plot');
      if (plotDiv) Plotly.Plots.resize(plotDiv);
    }});
  }}
}}

function initChart(idx) {{
  mcInitialized[idx] = true;
  var dataEl = document.getElementById('mc-chart-data-' + idx);
  var chartData = JSON.parse(dataEl.textContent);
  var container = document.getElementById('mc-chart-' + idx);
  var layout = Object.assign({{}}, chartData.layout, {{ autosize: true, height: undefined }});
  Plotly.newPlot(container, chartData.data, layout, {{responsive: true}});
}}

// Initialize the first tab on load
window.addEventListener('load', function() {{ initChart(0); }});
</script>

</body>
</html>"""

    abs_path = os.path.abspath(output_path)
    Path(abs_path).parent.mkdir(parents=True, exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as fh:
        fh.write(html)

    if open_browser:
        webbrowser.open(f"file://{abs_path}")
    return abs_path


def generate_adherence_report_html(
    result,
    output_path: str = "adherence_report.html",
    open_browser: bool = True,
) -> str:
    """Generates a self-contained HTML report comparing SQX vs MT5 backtests.

    Args:
        result:       AdherenceResult dataclass from services/adherence.py.
        output_path:  Path for the generated HTML file.
        open_browser: If True, opens the file in the default browser.

    Returns:
        Absolute path to the generated file.
    """
    import os
    import webbrowser
    from pathlib import Path

    import plotly.graph_objects as go

    # Build one Plotly figure per strategy (serialized to JSON for lazy loading)
    charts_json = []
    for s in result.strategies:
        mt5_x = list(range(len(s.mt5_equity)))
        sqx_x = list(range(len(s.sqx_equity)))

        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=mt5_x,
                y=[round(float(v), 2) for v in s.mt5_equity],
                name="MT5",
                line=dict(color="white", width=2),
                hovertemplate="Trade %{x}<br>Equity: %{y:,.2f}<extra>MT5</extra>",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=sqx_x,
                y=[round(float(v), 2) for v in s.sqx_equity],
                name="SQX",
                line=dict(color="#4fc3f7", width=2),
                hovertemplate="Trade %{x}<br>Equity: %{y:,.2f}<extra>SQX</extra>",
            )
        )
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="#1a1a2e",
            plot_bgcolor="#1a1a2e",
            hovermode="closest",
            title=dict(text=s.name, font=dict(size=14, color="#e0e0e0")),
            xaxis=dict(title="Trade #", gridcolor="#252545"),
            yaxis=dict(title="Cumulative P&L", gridcolor="#252545"),
            legend=dict(
                orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1
            ),
            margin=dict(l=60, r=20, t=60, b=40),
            height=380,
        )
        charts_json.append(fig.to_json())

    # Embed chart data as JSON script tags
    chart_scripts = "\n".join(
        f'<script type="application/json" id="adherence-chart-{i}">{cj}</script>'
        for i, cj in enumerate(charts_json)
    )

    # Build table rows
    rows_html = ""
    for i, s in enumerate(result.strategies):
        status_label = "PASS" if s.passes else "FAIL"
        status_color = "#2ecc71" if s.passes else "#e74c3c"
        row_bg = "" if s.passes else "background:rgba(231,76,60,0.08);"
        trade_pct = f"{s.trade_ratio * 100:.1f}%"
        trade_color = "#2ecc71" if s.trade_ratio >= result.threshold else "#e74c3c"
        pearson_color = (
            "#2ecc71" if s.pearson >= result.pearson_threshold else "#e74c3c"
        )
        wr_color = "#aaa"  # informational — no threshold

        rows_html += f"""
        <tr class="strategy-row" data-idx="{i}" style="{row_bg}cursor:pointer;" onclick="toggleChart({i})">
          <td style="color:#4fc3f7;font-weight:500">{s.name}</td>
          <td style="text-align:center">{s.mt5_trades}</td>
          <td style="text-align:center">{s.sqx_trades}</td>
          <td style="text-align:center;color:{trade_color};font-weight:600">{trade_pct}</td>
          <td style="text-align:center;color:{pearson_color};font-weight:600">{s.pearson:.3f}</td>
          <td style="text-align:center;color:{wr_color}">{s.mt5_win_rate * 100:.1f}%</td>
          <td style="text-align:center;color:{wr_color}">{s.sqx_win_rate * 100:.1f}%</td>
          <td style="text-align:center;color:#888">{s.mt5_retdd:.2f}</td>
          <td style="text-align:center;color:#888">{s.sqx_retdd:.2f}</td>
          <td style="text-align:center"><span style="color:{status_color};font-weight:700;background:rgba(0,0,0,0.3);padding:2px 10px;border-radius:4px">{status_label}</span></td>
        </tr>
        <tr id="chart-row-{i}" style="display:none">
          <td colspan="10" style="padding:0">
            <div id="chart-div-{i}" style="width:100%;padding:8px 0"></div>
          </td>
        </tr>"""

    threshold_pct = f"{result.threshold * 100:.0f}%"
    pearson_thr_str = f"{result.pearson_threshold:.2f}"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Adherence Report — SQX vs MT5</title>
<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #1a1a2e; color: #e0e0e0; font-family: 'Segoe UI', Arial, sans-serif; font-size: 14px; }}
  .header {{ background: #16213e; padding: 20px 32px; border-bottom: 1px solid #252545; }}
  .header h1 {{ font-size: 20px; color: #4fc3f7; font-weight: 600; margin-bottom: 12px; }}
  .summary {{ display: flex; gap: 24px; flex-wrap: wrap; }}
  .stat {{ background: rgba(0,0,0,0.2); border-radius: 6px; padding: 10px 20px; text-align: center; }}
  .stat .val {{ font-size: 22px; font-weight: 700; }}
  .stat .lbl {{ font-size: 11px; color: #888; margin-top: 2px; letter-spacing: .5px; text-transform: uppercase; }}
  .pass-rate {{ color: {"#2ecc71" if result.pass_rate >= 80 else "#e74c3c"}; }}
  .container {{ padding: 24px 32px; }}
  table {{ width: 100%; border-collapse: collapse; }}
  thead th {{ background: #16213e; padding: 10px 14px; text-align: left; font-size: 11px;
              letter-spacing: .5px; text-transform: uppercase; color: #888;
              border-bottom: 2px solid #252545; position: sticky; top: 0; z-index: 1; }}
  thead th.gate {{ color: #4fc3f7; }}
  thead th.info {{ color: #666; font-style: italic; }}
  tbody tr.strategy-row:hover {{ background: rgba(79,195,247,0.07) !important; }}
  tbody td {{ padding: 10px 14px; border-bottom: 1px solid #252545; vertical-align: middle; }}
  .threshold-note {{ font-size: 12px; color: #666; margin-bottom: 12px; }}
</style>
</head>
<body>

<div class="header">
  <h1>Adherence Report — SQX vs MT5</h1>
  <div class="summary">
    <div class="stat"><div class="val">{result.total}</div><div class="lbl">Total</div></div>
    <div class="stat"><div class="val" style="color:#2ecc71">{result.passed}</div><div class="lbl">Passed</div></div>
    <div class="stat"><div class="val" style="color:#e74c3c">{result.failed}</div><div class="lbl">Failed</div></div>
    <div class="stat"><div class="val pass-rate">{result.pass_rate:.1f}%</div><div class="lbl">Pass Rate</div></div>
    <div class="stat"><div class="val" style="color:#f39c12">{threshold_pct}</div><div class="lbl">Trade Gate</div></div>
    <div class="stat"><div class="val" style="color:#f39c12">{pearson_thr_str}</div><div class="lbl">Pearson Gate</div></div>
  </div>
</div>

<div class="container">
  <p class="threshold-note">
    Gates (colored): <strong>Trade %</strong> &ge; {threshold_pct} &nbsp;|&nbsp; <strong>Pearson</strong> &ge; {pearson_thr_str} &nbsp;&mdash;&nbsp;
    Informational (grey): Win Rate, RetDD &nbsp;&mdash;&nbsp;
    Click a row to compare equity curves.
  </p>
  <table>
    <thead>
      <tr>
        <th>Strategy</th>
        <th class="gate" style="text-align:center">MT5 Trades</th>
        <th class="gate" style="text-align:center">SQX Trades</th>
        <th class="gate" style="text-align:center">Trade %</th>
        <th class="gate" style="text-align:center">Pearson</th>
        <th class="info" style="text-align:center">MT5 WR</th>
        <th class="info" style="text-align:center">SQX WR</th>
        <th class="info" style="text-align:center">MT5 RetDD</th>
        <th class="info" style="text-align:center">SQX RetDD</th>
        <th style="text-align:center">Status</th>
      </tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>
</div>

{chart_scripts}

<script>
  var initializedCharts = {{}};

  function toggleChart(idx) {{
    var chartRow = document.getElementById('chart-row-' + idx);
    var isVisible = chartRow.style.display !== 'none';

    if (isVisible) {{
      chartRow.style.display = 'none';
      return;
    }}

    chartRow.style.display = '';

    if (!initializedCharts[idx]) {{
      initializedCharts[idx] = true;
      var scriptEl = document.getElementById('adherence-chart-' + idx);
      var figData = JSON.parse(scriptEl.textContent);
      var div = document.getElementById('chart-div-' + idx);
      Plotly.newPlot(div, figData.data, figData.layout, {{responsive: true, displayModeBar: false}});
    }}
  }}

  window.addEventListener('resize', function() {{
    Object.keys(initializedCharts).forEach(function(idx) {{
      var div = document.getElementById('chart-div-' + idx);
      if (div) Plotly.relayout(div, {{}});
    }});
  }});
</script>

</body>
</html>"""

    abs_path = os.path.abspath(output_path)
    Path(abs_path).parent.mkdir(parents=True, exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as fh:
        fh.write(html)

    if open_browser:
        webbrowser.open(f"file://{abs_path}")
    return abs_path
