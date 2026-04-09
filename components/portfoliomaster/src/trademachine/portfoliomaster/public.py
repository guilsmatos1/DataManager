"""Public API for the portfoliomaster component."""

from trademachine.portfoliomaster.core.config import AppConfig
from trademachine.portfoliomaster.core.exceptions import (
    DataError,
    ParserError,
    PortfolioMasterError,
    ValidationError,
)
from trademachine.portfoliomaster.services.adherence import (
    AdherenceResult,
    StrategyAdherence,
    adherence_result_to_dict,
    run_adherence_check,
)
from trademachine.portfoliomaster.services.cache import CacheInfo, CacheService
from trademachine.portfoliomaster.services.genetic import GeneticEngine
from trademachine.portfoliomaster.services.metrics import (
    calculate_metrics_from_deals,
    compute_vector_metrics,
    extract_closed_trades,
    preprocess_deals,
)
from trademachine.portfoliomaster.services.montecarlo import (
    MonteCarloResult,
    run_montecarlo,
)
from trademachine.portfoliomaster.services.optimization import (
    BenchmarkResult,
    BruteForceEngine,
)
from trademachine.portfoliomaster.services.output import OptimizationOutputService
from trademachine.portfoliomaster.services.pairing import (
    PairingApplyResult,
    PairingRow,
    PairingService,
)
from trademachine.portfoliomaster.services.portfolio import (
    PortfolioManager,
    exclude_strategies_from_trades,
    filter_trades_by_date,
    filter_trades_by_strategy,
)
from trademachine.portfoliomaster.utils.sqx_parser import (
    parse_sqx_csv,
    parse_sqx_directory,
)
from trademachine.portfoliomaster.utils.visualizer import (
    generate_adherence_report_html,
    generate_montecarlo_report_html,
    generate_portfolio_report_html,
    plot_portfolio_equity,
)

__all__ = [
    "AdherenceResult",
    "AppConfig",
    "BenchmarkResult",
    "BruteForceEngine",
    "CacheInfo",
    "CacheService",
    "DataError",
    "GeneticEngine",
    "MonteCarloResult",
    "OptimizationOutputService",
    "PairingApplyResult",
    "PairingRow",
    "PairingService",
    "ParserError",
    "PortfolioMasterError",
    "PortfolioManager",
    "StrategyAdherence",
    "ValidationError",
    "adherence_result_to_dict",
    "calculate_metrics_from_deals",
    "compute_vector_metrics",
    "exclude_strategies_from_trades",
    "extract_closed_trades",
    "filter_trades_by_date",
    "filter_trades_by_strategy",
    "generate_adherence_report_html",
    "generate_montecarlo_report_html",
    "generate_portfolio_report_html",
    "parse_sqx_csv",
    "parse_sqx_directory",
    "plot_portfolio_equity",
    "preprocess_deals",
    "run_adherence_check",
    "run_montecarlo",
]
