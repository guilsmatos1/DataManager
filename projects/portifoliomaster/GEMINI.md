# PortifolioMaster Context & Instructions

This file provides foundational context and operational mandates for working with the **PortifolioMaster** codebase.

## Project Overview
**PortifolioMaster** is a high-performance portfolio optimization tool for MetaTrader 5 (MT5) trading strategies. It leverages vectorized linear algebra (NumPy) and a Rust-based DataFrame engine (Polars) to analyze millions of strategy combinations in seconds. The code currently versioned in this repository is centered on a local CLI workflow.

### Main Technologies
- **Language:** Python 3.12+
- **Data Processing:** `polars`, `numpy`, `pandas`
- **Configuration:** `pydantic`, `pydantic-settings`
- **Parsing:** `beautifulsoup4`, `lxml`
- **Visualization:** `plotly`
- **Caching:** `pyarrow` (Parquet)
- **Testing:** `pytest`
- **Linting/Formatting:** `ruff`

### Architecture & Key Modules
The project follows a `src/portifoliomaster/` layout.

- `src/portifoliomaster/main.py`: CLI entry point, configuration loading, and argument parsing.
- `src/portifoliomaster/api/cli.py`: Central orchestrator (`PortifolioCLI`) for CLI flows and interactive shell commands.
- `src/portifoliomaster/services/portfolio.py`: `PortfolioManager` for strategy data management.
- `src/portifoliomaster/services/optimization.py`: `BruteForceEngine` (Brute-Force & Greedy algorithms).
- `src/portifoliomaster/services/metrics.py`: Vectorized quantitative metrics (Profit, MaxDD, RetDD, Sharpe, etc.).
- `src/portifoliomaster/utils/mt5_parser.py`: Specialized parser for MT5 HTML backtest reports.
- `src/portifoliomaster/utils/visualizer.py`: Interactive Plotly equity curves and HTML reports.
- `src/portifoliomaster/core/config.py`: Centralized `AppConfig` using Pydantic Settings (loads from `config.json`, `.env`, or defaults).
- `src/portifoliomaster/services/adherence.py`: MT5 vs SQX adherence checks and report generation.
- `src/portifoliomaster/utils/sqx_parser.py`: SQX CSV parsing used by adherence flows.

---

## Building and Running

### Installation
The project uses `pyproject.toml`. It is recommended to use `uv` for dependency management.
```bash
# Using uv
uv sync
# Using pip
pip install .
```

### Common Commands
- **CLI Tool:** `portifoliomaster [args]` or `python -m portifoliomaster [args]`
- **Interactive Shell:** `portifoliomaster -i`
- **Run Tests:** `pytest` (Configured to include `src/` in `PYTHONPATH`)
- **Linting:** `ruff check .`

---

## Development Conventions

### Performance Standards
- **Vectorization First:** Always prefer NumPy/Polars vectorized operations (e.g., matrix multiplication `@`) over Python loops.
- **Batch Processing:** Use batching for correlation filtering and matrix algebra to manage memory.

### Data Handling
- **Caching:** Parsed reports are cached in `cache.parquet`.
- **Lots Sidecar:** Representative lot sizes are cached in `cache_lots.json`.
- **Normalization:** MT5 reports use inconsistent locales (PT/EN). Use `MT5ReportParser` and `services.metrics.clean_mt5_numeric_string()` for normalization.

### Testing & Validation
- **Pathing:** Always run tests from the root. `pyproject.toml` handles the `src` pathing.
- **Consistency:** `tests/test_brute_force_consistency.py` is the primary regression test.

### Configuration
- Use `AppConfig` from `portifoliomaster.core.config`.
- CLI arguments take precedence over `config.json` and `.env`.

---

## Technical Debt & Caveats
- **HTML Parsing:** MT5 reports are fragile; updates to MT5 may require parser adjustments in `utils/mt5_parser.py`.
- **Multiprocessing:** Enabled in CLI optimization runs; behavior depends on platform and strategy count.
- **Memory Limits:** Brute-force is OOM-prone for large asset sets (>8-10). Use `--greedy` mode for these cases.
