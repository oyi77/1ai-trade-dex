"""Evolution engine APScheduler jobs.

Wave 10: Evolution Scheduler — Part 7
Contains the job functions for fitness evaluation, mutation cycles, crossover cycles,
necromancy analysis, and regime rebalancing.

Track 3.4: When EVOLUTION_BACKEND is set to 'deap', mutation and crossover
cycles delegate to the EvolutionHarness (NSGA-II multi-objective optimization).

NOTE: This module is now a backward-compatible re-export layer.
The actual implementations live in:
  - genome_helpers.py      (helper functions and constants)
  - evolution_cycles.py    (core evolution cycle logic)
  - scheduler_jobs.py      (APScheduler job wrappers)
"""

# Re-export all constants and helper functions from genome_helpers.py
from backend.config import settings
from backend.application.agi.genome_helpers import (  # noqa: F401
    SHADOW_TO_PAPER_MIN_TRADES,
    SHADOW_TO_PAPER_MIN_WIN_RATE,
    SHADOW_TO_PAPER_MIN_SHARPE,
    PAPER_TO_LIVE_MIN_TRADES,
    PAPER_TO_LIVE_MIN_WIN_RATE,
    PAPER_TO_LIVE_MIN_SHARPE,
    PAPER_TO_LIVE_MAX_DRAWDOWN,
    AUTO_KILL_MAX_DRAWDOWN,
    AUTO_KILL_MIN_SHARPE,
    AUTO_KILL_MIN_WIN_RATE,
    _DEFAULT_GENE_BOUNDS,
    _genome_to_individual,
    _individual_to_genome,
    _to_strategy_genome_from_genome,
    _safe_load_json,
    _fitness_metrics_for,
    _fitness_score_for,
    _chromosomes_for,
    _to_strategy_genome,
    _chromosomes_to_json,
    _upsert_genome,
    _sync_genome_fitness_from_shadow_trades,
)

# Re-export core evolution cycle functions from evolution_cycles.py
from backend.application.agi.evolution_cycles import (  # noqa: F401
    run_mutation_cycle,
    run_crossover_cycle,
    update_fitness_from_shadow,
    rebalance_population,
    log_evolution_action,
    targeted_mutation,
)

# Re-export APScheduler job wrappers from scheduler_jobs.py
from backend.application.agi.scheduler_jobs import (  # noqa: F401
    fitness_evaluation_job,
    mutation_cycle_job,
    crossover_cycle_job,
    necromancy_analysis_job,
    regime_rebalancing_job,
    shadow_validation_job,
    full_population_review_job,
    legend_evaluation_job,
)

__all__ = [
    # Constants
    "SHADOW_TO_PAPER_MIN_TRADES",
    "SHADOW_TO_PAPER_MIN_WIN_RATE",
    "SHADOW_TO_PAPER_MIN_SHARPE",
    "PAPER_TO_LIVE_MIN_TRADES",
    "PAPER_TO_LIVE_MIN_WIN_RATE",
    "PAPER_TO_LIVE_MIN_SHARPE",
    "PAPER_TO_LIVE_MAX_DRAWDOWN",
    "AUTO_KILL_MAX_DRAWDOWN",
    "AUTO_KILL_MIN_SHARPE",
    "AUTO_KILL_MIN_WIN_RATE",
    # Genome helpers (private but importable for backward compat)
    "_DEFAULT_GENE_BOUNDS",
    "_genome_to_individual",
    "_individual_to_genome",
    "_to_strategy_genome_from_genome",
    "_safe_load_json",
    "_fitness_metrics_for",
    "_fitness_score_for",
    "_chromosomes_for",
    "_to_strategy_genome",
    "_chromosomes_to_json",
    "_upsert_genome",
    "_sync_genome_fitness_from_shadow_trades",
    # Evolution cycles
    "run_mutation_cycle",
    "run_crossover_cycle",
    "update_fitness_from_shadow",
    "rebalance_population",
    "log_evolution_action",
    "targeted_mutation",
    # Scheduler jobs
    "fitness_evaluation_job",
    "mutation_cycle_job",
    "crossover_cycle_job",
    "necromancy_analysis_job",
    "regime_rebalancing_job",
    "shadow_validation_job",
    "full_population_review_job",
    "legend_evaluation_job",
]
