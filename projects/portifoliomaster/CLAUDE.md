# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies (including dev tools)
uv sync --dev

# Interactive mode (recommended — data persists in memory between commands)
uv run portifoliomaster -i

# Direct: load reports and list strategies
uv run portifoliomaster --load tests/reports/ --list

# Direct: optimize 5-asset portfolios with 30% max correlation
uv run portifoliomaster --load tests/reports/ --optimize --min 5 --max 5 --corr 0.3 --print

# Direct: save optimization results to CSV
uv run portifoliomaster --optimize --min 3 --max 5 --save results.csv

# Direct: export best portfolio trade history
uv run portifoliomaster --optimize --min 5 --save-trades trades.parquet

# Import and visualize a saved portfolio JSON
uv run portifoliomaster --import-p my_portfolio.json --report

# Run all tests
uv run pytest tests/

# Run a single test file
uv run pytest tests/test_engine.py -v

# Lint (with auto-fix) and format
uv run ruff check --fix . && uv run ruff format .
```

## Architecture

**PortifolioMaster** is a Python tool for analyzing and optimizing trading strategy combinations from MetaTrader 5 (MT5) HTML backtest reports. It performs brute-force portfolio optimization using vectorized NumPy/Polars calculations to find optimal strategy combinations based on risk-adjusted returns and correlation filtering.

### Core Principle

All optimization runs on **100% of the trade history** (trade-by-trade, not bar-by-bar). Correlation filtering uses **max pairwise correlation** (not mean) — every pair must independently satisfy the threshold.

### Module Responsibilities

```
src/portifoliomaster/main.py              → CLI entry point; routes -i flag to interactive shell or executes single command
src/portifoliomaster/api/cli.py           → PortifolioCLI: pipeline orchestration, caching, interactive shell
src/portifoliomaster/core/config.py       → AppConfig: Pydantic BaseSettings (loads from .env + validates)
src/portifoliomaster/core/exceptions.py   → Custom exception hierarchy (ValidationError, ParserError, etc.)
src/portifoliomaster/services/
  optimization.py                         → BruteForceEngine: brute-force + greedy forward-selection
  portfolio.py                            → PortfolioManager: strategy storage, returns matrix construction
  metrics.py                              → compute_vector_metrics(), calculate_metrics_from_deals(), MT5 string cleaning
src/portifoliomaster/utils/
  mt5_parser.py                           → MT5ReportParser: HTML parsing (multi-encoding), deal table extraction
  visualizer.py                           → plot_portfolio_equity(), generate_portfolio_report_html() (Plotly)
  logger.py                               → setup_logger(): console + file handler (log.log)
  help.py                                 → get_detailed_help(): unified help text for CLI and interactive shell
```

### Data Flow

```
User (CLI / -i shell)
  → PortifolioCLI (src/portifoliomaster/api/cli.py)
    → MT5ReportParser.parse_report()     → deals DataFrame (or cache.parquet)
    → PortfolioManager.add_strategy()    → Polars DataFrames per strategy
    → BruteForceEngine.run()             → ranked portfolios list
    → visualizer / CSV / JSON export
```

### Optimization Pipeline (BruteForceEngine)

1. Build wide trade matrix `(timestamps × strategies)` float64
2. Compute pairwise correlation matrix filtered by period (H/D/W/M)
3. Generate all k-asset combinations via `itertools.combinations`
4. Filter batches by **max** pairwise correlation ≤ `max_corr`
5. Vectorized metric calculation via NumPy: `trade_matrix @ strategy_mask`
6. Track top-N results with a min-heap (O(log N) inserts)
7. Compute full MT5-style metrics for top portfolios only

**Greedy mode (`--greedy`):** runs brute-force for seed size (`--min`), then iteratively adds the strategy that most improves the ranking metric while respecting the correlation threshold.

### Caching

Parsed MT5 HTML is saved as `cache.parquet` (Polars/PyArrow). Loads in <1s vs 30–60s for raw HTML parsing. Cache is read from the current working directory; falls back to HTML re-parsing if invalid or missing.

### Primary Ranking Metric

`RetDD` (Net Profit / Max Drawdown). Configurable via `.env` or `--rank` flag.

### Correlation Periods

`H` (hourly), `D` (daily — default), `W` (weekly), `M` (monthly). Larger periods = coarser granularity = faster computation.

## Ruff Workflow

Always run Ruff after implementing or editing Python files.

```bash
# Lint and auto-fix
uv run ruff check --fix .

# Format
uv run ruff format .

# Full run (recommended)
uv run ruff check --fix . && uv run ruff format .
```

### Workflow Rules
1. Implement the requested functionality.
2. Run `uv run ruff check --fix . && uv run ruff format .`
3. Check if any warnings remain.
