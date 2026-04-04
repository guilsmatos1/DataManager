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

  {B}optimize{R}             Run the portfolio optimization pipeline.
                      Supports loading reports, filtering strategies,
                      brute-force search, greedy mode, and exports.

  {B}load{R}                 Load MT5 reports into memory and refresh the cache.
                      Can also list the loaded strategies immediately.

  {B}benchmark{R}            Measure real throughput and extrapolate search capacity
                      for a target time window.

  {B}adherence{R}            Compare MT5 reports against SQX CSV reports.
                      Uses only the shared history window for calculations.

  {B}pairing{R}              Normalize strategy lot sizes to a target drawdown.
                      Can apply the scaled values directly to the cache.

{B}{BL}OPTIMIZATION PARAMETERS{R}

  {B}optimize --list{R}           List loaded strategies with Profit, Trades, MaxDD, RetDD.
  {B}load <path>{R}               Load MT5 HTML reports from a directory.
  {B}load --workers <N>{R}        Set parsing workers for report loading ({C}0{R} = auto).
  {B}benchmark --target-time <N>{R} Estimate how many combinations fit in N seconds.
  {B}benchmark --sample-seconds <N>{R} Measure throughput for N real seconds.
  {B}optimize --min <N>{R}        Minimum strategies per combination (Default: 5).
  {B}optimize --max <N>{R}        Maximum strategies per combination (Default: 5).
  {B}optimize --top <N>{R}        Number of top results to keep (Default: 10).
  {B}optimize --corr <X.X>{R}     Max allowed internal correlation (Default: 0.3).
  {B}optimize --corr-period <P>{R} Correlation timeframe: {C}H{R}, {C}D{R}, {C}W{R}, {C}M{R}.
  {B}optimize --rank <Metric>{R}  Ranking metric: {C}RetDD{R} or {C}NetProfit{R}.
  {B}optimize --greedy{R}         Forward-selection mode starting from the best seed of size --min.
  {B}optimize --greedy-loops <N>{R} Repeat greedy optimization N times, removing
                             selected strategies from cache after each loop.
  {B}optimize --prune-cache{R} Remove the strategies from the rank 1 portfolio
                             from cache after the run finishes.
  {B}optimize --filter <X>{R}     Minimum accepted value for the selected ranking metric.
  {B}optimize --montecarlo <N>{R} Run N robustness simulations for the rank 1 portfolio.

{B}{BL}DATA FILTERS & EXPORTS{R}

  {B}optimize --date-initial{R}   Filter trades from this date ({C}YYYY-MM-DD{R}).
  {B}optimize --date-final{R}     Filter trades until this date ({C}YYYY-MM-DD{R}).
  {B}optimize --strats <L>{R}     Limit to a comma-separated list of strategy names.
  {B}optimize --exclude-strats <L>{R} Exclude a comma-separated list of strategy names.
                               {C}Note:{R} cannot be combined with {C}--strats{R}.
  {B}optimize --save-trades <F>{R} Export detailed history for the rank 1 portfolio (.csv or .parquet).
  {B}optimize --output <dir>{R}   Save artifacts such as rank.json, parquet files, and HTML report.

{B}{BL}DIAGNOSTICS & SYSTEM (Subcommands){R}

  {B}inspect correlations{R}  Show pairwise correlation matrix for loaded data.
                        Flags: {C}--corr-period H|D|W|M{R}  {C}--top N{R}  {C}--threshold X{R}
  {B}inspect strategy <N>{R}  Show deep-dive metrics and chart for a single strategy.
  {B}cache info{R}            Show cache metadata (size, strategies, date range).
  {B}cache save <file>{R}     Save the current cache and lots sidecar to another file.
  {B}cache load <file>{R}     Load a saved cache file into the active cache location.
  {B}cache merge <A> <B> <C>{R} Merge two saved cache files into a destination file.
                               {C}Note:{R} all three paths must be distinct.
  {B}cache clear{R}           Delete the cache.parquet file.
  {B}cache rebuild <dir>{R}   Re-parse HTML reports and overwrite the cache.
  {B}config show|validate{R}  Manage application settings (config.json).
  {B}load <dir>{R}            Load MT5 HTML reports into memory and cache.
                        Flags: {C}--workers N{R}  {C}--list{R}
  {B}benchmark{R}             Estimate optimization throughput on the current dataset.
                        Flags: {C}--load <dir>{R}  {C}--load-workers N{R}  {C}--min N{R}  {C}--max N{R}
                               {C}--corr X{R}  {C}--workers N{R}  {C}--sample-seconds N{R}
                               {C}--target-time N{R}
  {B}adherence --output <D>{R} Compare SQX vs MT5 backtests for fidelity.
                        Flags: {C}--threshold X{R}  {C}--pearson X{R}
                               {C}--export-passed-reports{R}  {C}--no-browser{R}
  {B}pairing{R}               Match strategy lot sizes to a target drawdown.
                        Flags: {C}--load <dir>{R}  {C}--workers N{R}  {C}--target N{R}  {C}--tick X{R}
                               {C}--apply{R}  {C}--report file.csv{R}
                        Validation: {C}--report{R} must end with {C}.csv{R}.
                        Loads from the given directory when {C}--load{R} is provided;
                        otherwise it uses the existing cache.
  {B}interactive{R}           Launch the interactive command shell (REPL).
  {B}help{R}                  Display this documentation.

──────────────────────────────────────────────────────────────────────────────
{B}{G}COMMON USE CASES{R}

{B}1. Initial Exploration{R}
   $ portifoliomaster load reports/ --workers 8 --list
   $ portifoliomaster inspect correlations --corr-period D --threshold 0.5
   $ portifoliomaster adherence --mt5-dir reports/mt5 --sqx-dir reports/sqx

{B}2. Standard Brute-Force Optimization (5-Asset, 0.3 Corr Limit){R}
   $ portifoliomaster optimize --load reports/ --load-workers 8 --min 5 --max 5 --print

{B}3. Exclude Strategies From the Search Space{R}
   $ portifoliomaster optimize --load reports/ --load-workers 8 --min 5 --max 5 --exclude-strats EA_1,EA_2 --print

{B}4. Throughput Benchmark (Estimate 10 Minutes of Processing){R}
   $ portifoliomaster benchmark --load reports/ --load-workers 8 --min 5 --max 5 --corr 0.3 --workers 8 --sample-seconds 5 --target-time 600

{B}5. Greedy Optimization (Faster for large asset sets){R}
   $ portifoliomaster optimize --load reports/ --load-workers 8 --greedy --min 5 --corr 0.25 --top 10 --print

{B}6. Robustness Validation (Monte Carlo on best results){R}
   $ portifoliomaster optimize --load reports/ --load-workers 8 --min 4 --max 6 --montecarlo 2000 --output ./run_01

{B}7. Multi-Loop Greedy Optimization{R}
   $ portifoliomaster optimize --load reports/ --load-workers 8 --greedy --greedy-loops 3 --min 5 --top 10 --output ./run_greedy

{B}8. Prune Top-1 Strategies From Cache After Optimization{R}
   $ portifoliomaster optimize --load reports/ --load-workers 8 --min 5 --max 5 --prune-cache --output ./run_pruned

{B}9. Cache Snapshot Merge{R}
   $ portifoliomaster cache merge ./backups/a.parquet ./backups/b.parquet ./backups/merged.parquet

{B}10. Time-Window Analysis (Last Year Only){R}
   $ portifoliomaster optimize --load reports/ --load-workers 8 --date-initial 2024-01-01 --print

{B}11. Strategy Comparison (SQX vs MT5){R}
   $ portifoliomaster adherence --mt5-dir reports/mt5 --sqx-dir reports/sqx --output ./adherence_run

{B}12. Drawdown Pairing (Normalize lot sizes to a target drawdown){R}
   $ portifoliomaster pairing --load reports/ --workers 8 --target 4000 --tick 0.1 --apply

{B}13. Pairing CSV Report Export{R}
   $ portifoliomaster pairing --load reports/ --workers 8 --target 4000 --tick 0.1 --report ./pairing.csv

{B}14. Export Passed MT5 Reports After Adherence{R}
   $ portifoliomaster adherence --mt5-dir reports/mt5 --sqx-dir reports/sqx --output ./adherence_run --export-passed-reports

──────────────────────────────────────────────────────────────────────────────
For bug reports or feature requests, please check the project repository.
"""
