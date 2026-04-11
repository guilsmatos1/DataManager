"""
Help Documentation Module
=========================
Contains the unified detailed help text for both CLI and Interactive modes.
"""

# ANSI Color Codes
B = "\033[1m"
G = "\033[32m"
BL = "\033[34m"
C = "\033[36m"
Y = "\033[33m"
R = "\033[0m"


def get_detailed_help() -> str:
    return f"""
{B}{G}PortfolioMaster v0.1.0{R} - {C}Current CLI Contract{R}
──────────────────────────────────────────────────────────────────────────────

{B}{BL}Core Workflow{R}

  {Y}Load reports{R}
    portfoliomaster load reports/

  {Y}Run optimization from disk in one step{R}
    portfoliomaster optimize --load reports/ --min 3 --max 5 --top 10
    optimize --exclude-strats <L>
    optimize --prune-cache
    optimize --greedy-loops <N>
    --report file.csv

  {Y}Benchmark the current search space{R}
    portfoliomaster benchmark --load reports/ --min 3 --max 5

{B}{BL}Cache Commands{R}

  cache save <PATH>
  cache load <PATH>
  cache merge <A> <B> <C>

{B}{BL}Other Commands{R}

  adherence --export-passed-reports
  pairing --load reports/ --output pairing.csv

──────────────────────────────────────────────────────────────────────────────
This help intentionally documents the subcommand-based CLI and excludes the
legacy flag-only contract.
"""
