"""
Help Documentation Module
=========================
Contains the unified detailed help text for both CLI and Interactive modes.
Uses ANSI colors for professional terminal display.
"""

# ANSI Color Codes
B = "\033[1m"  # Bold
G = "\033[32m"  # Green
BL = "\033[34m"  # Blue
C = "\033[36m"  # Cyan
Y = "\033[33m"  # Yellow
R = "\033[0m"  # Reset


def get_detailed_help():
    return f"""
{B}{G}PortifolioMaster v0.1.0{R} - {C}Advanced MT5 Portfolio Optimization Engine{R}
──────────────────────────────────────────────────────────────────────────────

{B}Welcome to PortifolioMaster.{R} This tool analyzes MetaTrader 5 backtest reports
to find the most robust strategy combinations using vectorized linear algebra.

{B}{BL}CORE COMMANDS{R}

  {B}--load <path>{R}        Load MT5 HTML reports from a directory.
                      Automatically manages 'cache.parquet' for fast loading.
                      {Y}Example:{R} portifoliomaster --load ./reports

  {B}--list{R}               List all strategies currently in memory with metrics.
                      Displays Profit, Trades, MaxDD, and Return/DD.

  {B}--optimize{R}           Execute the brute-force optimization engine.
                      {Y}Example:{R} portifoliomaster --optimize --min 3 --max 5

{B}{BL}OPTIMIZATION PARAMETERS{R}

  {B}--min <N>{R}            Minimum strategies per combination (Default: 5).
  {B}--max <N>{R}            Maximum strategies per combination (Default: 5).
  {B}--top <N>{R}            Number of top results to display (Default: 10).
  {B}--corr <X.X>{R}         Max allowed internal correlation (Default: 0.3).
  {B}--corr-period <P>{R}    Correlation timeframe: {C}H{R} (Hourly), {C}D{R} (Daily), {C}W{R} (Weekly), {C}M{R} (Monthly).
  {B}--rank <Metric>{R}      Sorting criteria: {C}RetDD{R} or {C}NetProfit{R}.
  {B}--greedy{R}             Fast forward-selection mode for large portfolios.
  {B}--filter <X>{R}         Skip portfolios with metric below this value (Performance boost).
  {B}--montecarlo [N]{R}     Run N simulations (default 1000) to validate robustness.

{B}{BL}DATA FILTERS & EXPORTS{R}

  {B}--date-initial{R}       Filter trades from this date ({C}YYYY-MM-DD{R}).
  {B}--date-final{R}         Filter trades until this date ({C}YYYY-MM-DD{R}).
  {B}--strats <L>{R}         Limit to comma-separated list of strategy names.
  {B}--save-trades <F>{R}    Export detailed history for Rank 1 (.csv or .parquet).
  {B}--output <dir>{R}       Save ALL artifacts (JSON, Parquet, HTML) to a directory.

{B}{BL}DIAGNOSTICS & SYSTEM (Subcommands){R}

  {B}inspect correlations{R}  Show pairwise correlation matrix for loaded data.
                        Flags: {C}--corr-period H|D|W|M{R}  {C}--top N{R}  {C}--threshold X{R}
  {B}inspect strategy <N>{R}  Show deep-dive metrics and chart for a single strategy.
  {B}cache info{R}            Show cache metadata (size, strategies, date range).
  {B}cache clear{R}           Delete the cache.parquet file.
  {B}cache rebuild <dir>{R}   Re-parse HTML reports and overwrite the cache.
  {B}config show|validate{R}  Manage application settings (config.json).
  {B}adherence [--output D]{R} Compare SQX vs MT5 backtests for fidelity.
  {B}drawdown pairing{R}      Calculate optimal lot size per strategy to match a target drawdown.
                        Flags: {C}--target N{R} (default: 4000)  {C}--tick X{R} (default: 0.1)
                               {C}--apply{R}   Scale Net_Profit history and update cache.

  {B}-i, --interactive{R}     Launch the interactive command shell (REPL).
  {B}help{R}                  Display this documentation.

──────────────────────────────────────────────────────────────────────────────
{B}{G}COMMON USE CASES{R}

{B}1. Initial Exploration{R}
   $ portifoliomaster --load reports/ --list
   $ portifoliomaster inspect correlations --corr-period D --threshold 0.5
   $ portifoliomaster adherence --mt5-dir reports/mt5 --sqx-dir reports/sqx

{B}2. Standard Brute-Force Optimization (5-Asset, 0.3 Corr Limit){R}
   $ portifoliomaster --optimize --min 5 --max 5 --print

{B}3. Greedy Optimization (Faster for large asset sets){R}
   $ portifoliomaster --optimize --greedy --min 5 --corr 0.25 --print

{B}4. Robustness Validation (Monte Carlo on best results){R}
   $ portifoliomaster --optimize --min 4 --max 6 --montecarlo 2000 --output ./run_01

{B}5. Time-Window Analysis (Last Year Only){R}
   $ portifoliomaster --optimize --date-initial 2024-01-01 --print

{B}6. Strategy Comparison (SQX vs MT5){R}
   $ portifoliomaster adherence --mt5-dir reports/mt5 --sqx-dir reports/sqx

{B}7. Drawdown Pairing (Normalize lot sizes to a target drawdown){R}
   $ portifoliomaster drawdown pairing --target 4000 --tick 0.1

──────────────────────────────────────────────────────────────────────────────
For bug reports or feature requests, please check the project repository.
"""
