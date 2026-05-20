import random
from copy import deepcopy
from backend.domain.genome.models import StrategyGenome, LineageData
from backend.domain.evolution.mutation_engine import mutate_genome


def crossover_genomes(
    parent_a: StrategyGenome, parent_b: StrategyGenome, market_regime: str = "neutral"
) -> StrategyGenome:
    """
    Breeds two ELITE strategies. Eligibility: both must have fitness > 0.75.
    Chromosome selection is regime-weighted (not random uniform).
    """
    # Check eligibility - both parents must be ELITE
    if parent_a.fitness_metrics.sharpe_ratio <= 0.5:
        raise ValueError(
            f"Parent A not ELITE (sharpe={parent_a.fitness_metrics.sharpe_ratio})"
        )
    if parent_b.fitness_metrics.sharpe_ratio <= 0.5:
        raise ValueError(
            f"Parent B not ELITE (sharpe={parent_b.fitness_metrics.sharpe_ratio})"
        )

    child = StrategyGenome(
        strategy_name=f"cross_{parent_a.strategy_name[:8]}_{parent_b.strategy_name[:8]}",
        archetype="crossover",
        lineage=LineageData(
            parent_genome_ids=[parent_a.genome_id, parent_b.genome_id],
            generation=max(parent_a.lineage.generation, parent_b.lineage.generation)
            + 1,
            creator="crossover",
        ),
        chromosomes={},
        stage="DRAFT",
    )

    for chromosome_name in ["perception", "cognition", "execution", "risk", "meta"]:
        if market_regime == "volatile":
            # In volatile regimes, prefer the parent with lower drawdown on risk chromosome
            if chromosome_name == "risk":
                winner = (
                    parent_a
                    if parent_a.fitness_metrics.max_drawdown_pct
                    < parent_b.fitness_metrics.max_drawdown_pct
                    else parent_b
                )
            else:
                winner = parent_a if random.random() < 0.5 else parent_b

        elif market_regime == "trending":
            # In trending regimes, prefer parent with higher alpha_per_trade on cognition
            if chromosome_name == "cognition":
                winner = (
                    parent_a
                    if parent_a.fitness_metrics.alpha_per_trade
                    > parent_b.fitness_metrics.alpha_per_trade
                    else parent_b
                )
            else:
                winner = parent_a if random.random() < 0.5 else parent_b

        elif market_regime == "mean_reverting":
            # In mean-reverting regimes, prefer parent with higher win_rate on execution
            if chromosome_name == "execution":
                winner = (
                    parent_a
                    if parent_a.fitness_metrics.win_rate
                    > parent_b.fitness_metrics.win_rate
                    else parent_b
                )
            else:
                winner = parent_a if random.random() < 0.5 else parent_b

        else:  # neutral or unknown regime
            winner = parent_a if random.random() < 0.5 else parent_b

        child.chromosomes[chromosome_name] = deepcopy(
            winner.chromosomes[chromosome_name]
        )

    # Apply a light mutation to introduce fresh genetic material
    child, _ = mutate_genome(child, market_regime, fitness_score=0.5)

    return child
