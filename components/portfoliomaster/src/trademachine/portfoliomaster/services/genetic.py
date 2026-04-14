"""
Genetic Algorithm Optimization Engine
======================================
Portfolio optimization using evolutionary algorithms via DEAP.
Finds high-quality strategy combinations without exhaustive enumeration,
making it practical for large search spaces where brute force is infeasible.

Same input/output interface as BruteForceEngine.
"""

import heapq
import itertools
import logging
import math
import random
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

import numpy as np
import polars as pl
from deap import algorithms, base, creator, tools
from tqdm import tqdm
from trademachine.core.logger import LOGGER_NAME
from trademachine.portfoliomaster.core.constants import MT5_TIMESTAMP_FORMAT
from trademachine.portfoliomaster.services.metrics import calculate_metrics_from_deals
from trademachine.portfoliomaster.services.optimization import (
    METRIC_IDX_NET_PROFIT,
    METRIC_IDX_RET_DD,
    compute_batch_performance,
)
from trademachine.portfoliomaster.services.portfolio import PortfolioManager

logger = logging.getLogger(LOGGER_NAME)

# Sentinel used to register DEAP types only once per process
_DEAP_TYPES_REGISTERED = False
_BASE_RESULT_KEYS = {"Combo", "Net_Profit", "RetDD", "Maximum_Drawdown"}


def _ensure_deap_types() -> None:
    """Registers DEAP fitness/individual types exactly once."""
    global _DEAP_TYPES_REGISTERED
    if _DEAP_TYPES_REGISTERED:
        return
    if not hasattr(creator, "FitnessMax"):
        creator.create("FitnessMax", base.Fitness, weights=(1.0,))
    if not hasattr(creator, "Individual"):
        creator.create("Individual", list, fitness=creator.FitnessMax)
    _DEAP_TYPES_REGISTERED = True


def _repair_individual(
    individual: list[int],
    min_assets: int,
    max_assets: int,
    rng: random.Random,
) -> list[int]:
    """Ensures the individual has between min_assets and max_assets active genes.

    - Too few active genes: randomly activates inactive ones.
    - Too many active genes: randomly deactivates excess ones.
    """
    active = [i for i, bit in enumerate(individual) if bit]
    inactive = [i for i, bit in enumerate(individual) if not bit]

    if len(active) < min_assets:
        needed = min_assets - len(active)
        if len(inactive) >= needed:
            to_activate = rng.sample(inactive, needed)
            for idx in to_activate:
                individual[idx] = 1
        else:
            # Not enough inactive genes — activate all remaining
            for idx in inactive:
                individual[idx] = 1

    active = [i for i, bit in enumerate(individual) if bit]
    if len(active) > max_assets:
        excess = len(active) - max_assets
        to_deactivate = rng.sample(active, excess)
        for idx in to_deactivate:
            individual[idx] = 0

    return individual


def _check_correlation_violation(
    selected: list[int],
    correlation_matrix: np.ndarray,
    max_corr: float,
) -> bool:
    """Returns True if any pair of selected strategies violates max_corr."""
    if len(selected) < 2:
        return False
    for i in range(len(selected)):
        for j in range(i + 1, len(selected)):
            val = correlation_matrix[selected[i], selected[j]]
            if not np.isnan(val) and val > max_corr:
                return True
    return False


def _strip_detailed_metrics(results: list[dict]) -> list[dict]:
    """Keeps only the base GA result shape used before detailed enrichment."""
    return [
        {key: value for key, value in result.items() if key in _BASE_RESULT_KEYS}
        for result in results
    ]


class GeneticEngine:
    """
    Portfolio optimization engine using a genetic algorithm (DEAP).

    Explores the strategy-selection search space via evolutionary operators
    instead of exhaustive enumeration. Suitable for large universes (n > 30)
    where BruteForceEngine becomes computationally prohibitive.

    Output is identical in structure to BruteForceEngine.best_portfolios.
    """

    def __init__(
        self,
        all_trades_df: pl.DataFrame,
        correlation_period: str = "D",
        correlation_matrix: np.ndarray | None = None,
        initial_balance: float = 100_000.0,
    ):
        self.all_trades_raw = all_trades_df.sort("Horário")
        self.strategy_names = sorted(self.all_trades_raw["Strategy"].unique().to_list())
        self.initial_balance = initial_balance
        self.correlation_period = correlation_period

        self.wide_trades = (
            self.all_trades_raw.pivot(
                index="Horário",
                on="Strategy",
                values="Net_Profit",
                aggregate_function="sum",
            )
            .fill_null(0.0)
            .sort("Horário")
            .select(["Horário"] + self.strategy_names)
        )

        # Pre-compute trade matrix once; reused by run()
        self.trade_matrix = (
            self.wide_trades.drop("Horário").to_numpy().astype(np.float64)
        )

        if correlation_matrix is not None:
            self.correlation_matrix = correlation_matrix
        else:
            self.correlation_matrix = self._compute_correlation(correlation_period)

        self.best_portfolios: list[dict] = []
        _ensure_deap_types()

    def _compute_correlation(self, period: str) -> np.ndarray:
        logger.info(f"Computing correlation matrix (Period: {period})...")
        pm = PortfolioManager()
        corr = pm.compute_periodic_correlation(
            self.all_trades_raw, self.strategy_names, period
        )
        upper = corr[np.triu_indices_from(corr, k=1)]
        valid = upper[~np.isnan(upper)]
        if len(valid) > 0:
            logger.info(
                f"Pairwise correlation — min: {valid.min():.3f} | "
                f"max: {valid.max():.3f} | mean: {valid.mean():.3f}"
            )
        return corr  # type: ignore[no-any-return]

    def run(
        self,
        min_assets: int = 5,
        max_assets: int = 5,
        top_n: int = 10,
        rank_by: str = "RetDD",
        max_corr: float = 0.3,
        population_size: int = 300,
        generations: int = 100,
        crossover_prob: float = 0.7,
        mutation_prob: float = 0.2,
        tournament_size: int = 3,
        elite_size: int = 5,
        enrich_details: bool = True,
        random_seed: int = 0,
    ) -> list[dict]:
        """Runs the genetic algorithm and returns the top-N portfolios."""
        n = len(self.strategy_names)
        trade_matrix = self.trade_matrix
        sort_metric_index = (
            METRIC_IDX_RET_DD if rank_by == "RetDD" else METRIC_IDX_NET_PROFIT
        )
        rng = random.Random(random_seed)

        logger.info(
            f"Genetic optimization: {n} strategies | "
            f"pop={population_size} | gen={generations} | "
            f"cx={crossover_prob} | mut={mutation_prob} | rank_by={rank_by} | "
            f"seed={random_seed}"
        )

        # --- Fitness function ---
        def evaluate(individual: list[int]) -> tuple[float]:
            selected = [i for i, bit in enumerate(individual) if bit]
            count = len(selected)
            if count < min_assets or count > max_assets:
                return (-1e9,)
            if _check_correlation_violation(
                selected, self.correlation_matrix, max_corr
            ):
                return (-1e9,)
            returns = trade_matrix[:, selected].sum(axis=1)
            metrics = compute_batch_performance(returns[:, None])
            value = float(metrics[0, sort_metric_index])
            return (value,)

        # --- Toolbox setup ---
        toolbox = base.Toolbox()

        def _make_individual() -> Any:
            """Creates a random individual with exactly min_assets active genes."""
            bits = [0] * n
            active_count = rng.randint(min_assets, max_assets)
            active_count = min(active_count, n)
            for idx in rng.sample(range(n), active_count):
                bits[idx] = 1
            return creator.Individual(bits)

        toolbox.register("individual", _make_individual)
        toolbox.register("population", tools.initRepeat, list, toolbox.individual)
        toolbox.register("evaluate", evaluate)
        toolbox.register("mate", tools.cxUniform, indpb=0.5)
        toolbox.register("mutate", tools.mutFlipBit, indpb=2.0 / max(n, 1))
        toolbox.register("select", tools.selTournament, tournsize=tournament_size)

        # --- Repair decorator: applied after mate/mutate ---
        def _repair_after(func):
            def wrapper(*args, **kwargs):
                offspring = func(*args, **kwargs)
                # offspring may be a tuple (cx) or single (mut)
                if isinstance(offspring, tuple):
                    for ind in offspring:
                        _repair_individual(ind, min_assets, max_assets, rng)
                        del ind.fitness.values
                    return offspring
                else:
                    _repair_individual(offspring, min_assets, max_assets, rng)
                    del offspring.fitness.values
                    return (offspring,)

            return wrapper

        toolbox.decorate("mate", _repair_after)
        toolbox.decorate("mutate", _repair_after)

        # --- Global top-N heap (tracks best unique combos across all generations) ---
        top_heap: list = []
        heap_counter = itertools.count()
        seen_combos: set[frozenset] = set()

        def _update_heap(ind: Any) -> None:
            selected = [i for i, bit in enumerate(ind) if bit]
            key = frozenset(selected)
            if key in seen_combos:
                return
            fit = ind.fitness.values[0]
            if fit <= -1e8:
                return
            seen_combos.add(key)
            result = {
                "Combo": tuple(self.strategy_names[i] for i in sorted(selected)),
                "Net_Profit": 0.0,
                "RetDD": 0.0,
                "Maximum_Drawdown": 0.0,
            }
            # Compute full metrics for bookkeeping
            returns = trade_matrix[:, sorted(selected)].sum(axis=1)
            m = compute_batch_performance(returns[:, None])
            result["Net_Profit"] = float(m[0, METRIC_IDX_NET_PROFIT])
            result["RetDD"] = float(m[0, METRIC_IDX_RET_DD])
            result["Maximum_Drawdown"] = float(m[0, 1])

            tiebreaker = next(heap_counter)
            if len(top_heap) < top_n:
                heapq.heappush(top_heap, (fit, tiebreaker, result))
            elif fit > top_heap[0][0]:
                heapq.heapreplace(top_heap, (fit, tiebreaker, result))

        # --- Initial population ---
        total_search_space = sum(
            math.comb(n, assets) for assets in range(min_assets, max_assets + 1)
        )
        if total_search_space <= 5_000:
            from trademachine.portfoliomaster.services.optimization import (
                BruteForceEngine,
            )

            brute_force = BruteForceEngine(
                self.all_trades_raw,
                correlation_period=self.correlation_period,
                correlation_matrix=self.correlation_matrix,
            )
            results = brute_force.run(
                min_assets=min_assets,
                max_assets=max_assets,
                top_n=top_n,
                rank_by=rank_by,
                max_corr=max_corr,
                min_metric=-1e9,
            )
            if not enrich_details:
                results = _strip_detailed_metrics(results)
            self.best_portfolios = results
            return self.best_portfolios

        if total_search_space <= population_size and total_search_space <= 5_000:
            population = []
            for assets in range(min_assets, max_assets + 1):
                for combo in itertools.combinations(range(n), assets):
                    bits = [0] * n
                    for idx in combo:
                        bits[idx] = 1
                    population.append(creator.Individual(bits))
        else:
            population = toolbox.population(n=population_size)

        # Evaluate initial population
        fitnesses = list(map(toolbox.evaluate, population))
        for ind, fit in zip(population, fitnesses, strict=False):
            ind.fitness.values = fit

        # Seed heap from initial population
        for ind in population:
            _update_heap(ind)

        logger.info(f"Starting evolution: {generations} generations...")

        # --- Evolutionary loop with elitism ---
        progress = tqdm(range(generations), desc="GA Generations", unit="gen")
        for _gen in progress:
            # Select elite individuals before variation
            elite = tools.selBest(population, elite_size)
            elite = [toolbox.clone(ind) for ind in elite]

            # Select and clone offspring
            offspring = toolbox.select(population, len(population) - elite_size)
            offspring = algorithms.varAnd(
                offspring, toolbox, crossover_prob, mutation_prob
            )

            # Evaluate offspring that need re-evaluation
            invalid = [ind for ind in offspring if not ind.fitness.valid]
            fitnesses = list(map(toolbox.evaluate, invalid))
            for ind, fit in zip(invalid, fitnesses, strict=False):
                ind.fitness.values = fit

            # Merge elite back
            population[:] = elite + offspring

            # Update global heap
            for ind in population:
                if ind.fitness.valid:
                    _update_heap(ind)

            # Progress display
            best_fit = max(ind.fitness.values[0] for ind in population)
            progress.set_postfix({"best": f"{best_fit:.2f}", "top_n": len(top_heap)})

        progress.close()

        winners = [
            item[2] for item in sorted(top_heap, key=lambda x: x[0], reverse=True)
        ]

        if enrich_details:
            logger.info("Calculating detailed metrics for top portfolios...")
            self._enrich_with_detailed_metrics(winners)

        self.best_portfolios = winners
        logger.info(f"Genetic optimization complete — {len(winners)} portfolios found.")
        return self.best_portfolios

    def ensure_detailed_metrics(self) -> None:
        """Enriches best_portfolios with full MT5-style metrics if not yet done."""
        if not self.best_portfolios:
            return
        needs_enrichment = [p for p in self.best_portfolios if "Total_Trades" not in p]
        if needs_enrichment:
            self._enrich_with_detailed_metrics(needs_enrichment)

    def _enrich_with_detailed_metrics(self, portfolios: list[dict]) -> None:
        for portfolio_result in tqdm(portfolios, desc="Finalizing"):
            combo = portfolio_result["Combo"]
            deals_df = self._build_portfolio_deals_df(combo)
            detailed = calculate_metrics_from_deals(deals_df)
            for key, value in detailed.items():
                if key not in ("Net_Profit", "RetDD", "Maximum_Drawdown"):
                    portfolio_result[key] = value

    def _build_portfolio_deals_df(self, combo: tuple[str, ...]) -> Any:
        """Constructs a mock MT5 deals DataFrame for the combined portfolio trades."""
        import pandas as pd

        initial_balance = self.initial_balance
        portfolio_trades = self.all_trades_raw.filter(
            pl.col("Strategy").is_in(combo)
        ).sort("Horário")

        if not portfolio_trades.is_empty():
            first_timestamp = portfolio_trades["Horário"][0].strftime(
                MT5_TIMESTAMP_FORMAT
            )
        else:
            first_timestamp = "2000.01.01 00:00:00"

        mock_data: dict = {
            "Horário": [first_timestamp],
            "Tipo": ["balance"],
            "Direção": [""],
            "Lucro": [0.0],
            "Comissão": [0.0],
            "Swap": [0.0],
            "Saldo": [initial_balance],
        }

        if not portfolio_trades.is_empty():
            num_trades = len(portfolio_trades)
            timestamps = (
                portfolio_trades["Horário"].dt.strftime(MT5_TIMESTAMP_FORMAT).to_list()
            )
            profits = portfolio_trades["Net_Profit"].to_list()
            cumulative = (
                portfolio_trades["Net_Profit"].cum_sum() + initial_balance
            ).to_list()

            mock_data["Horário"].extend(timestamps)
            mock_data["Tipo"].extend(["buy"] * num_trades)
            mock_data["Direção"].extend(["out"] * num_trades)
            mock_data["Lucro"].extend(profits)
            zeros = [0.0] * num_trades
            mock_data["Comissão"].extend(zeros)
            mock_data["Swap"].extend(zeros)
            mock_data["Saldo"].extend(cumulative)

        return pd.DataFrame(mock_data)

    def print_results(self, _columns: list[str] | None = None) -> None:
        """Prints top portfolios to terminal in the same format as BruteForceEngine."""
        if not self.best_portfolios:
            return
        print("\n🏆 TOP PORTFOLIOS (Genetic Algorithm):")
        header = (
            f"{'Rank':<4} | {'Combo':<45} | {'# of Trades':>12} | "
            f"{'Net Profit':>12} | {'RetDD':>8}"
        )
        print("=" * len(header))
        print(header)
        print("-" * len(header))
        for rank, res in enumerate(self.best_portfolios, 1):
            combo_str = ", ".join(res["Combo"])
            if len(combo_str) > 45:
                combo_str = combo_str[:42] + "..."
            row = (
                f"{rank:<4} | "
                f"{combo_str:<45} | "
                f"{res.get('Total_Trades', 0):>12} | "
                f"{res.get('Net_Profit', 0.0):>12.2f} | "
                f"{res.get('RetDD', 0.0):>8.2f}"
            )
            print(row)
        print("=" * len(header))
