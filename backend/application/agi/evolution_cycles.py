"""Core evolution cycle logic — mutation, crossover, fitness, rebalancing.

Wave 10: Evolution Scheduler — Part 7
Contains the core evolution algorithms: mutation cycles, crossover cycles,
fitness updates from shadow trades, population rebalancing, and evolution
action logging.

Track 3.4: When EVOLUTION_BACKEND is set to 'deap', mutation and crossover
cycles delegate to the EvolutionHarness (NSGA-II multi-objective optimization).
"""

import json
import statistics
from datetime import datetime, timezone
from itertools import cycle

from sqlalchemy.orm import Session

from backend.config import settings
from backend.core.evolution_harness import (
    Individual,
    create_evolution_backend,
)
from backend.core.event_bus import publish_event
from backend.db.utils import get_db_session as _get_db_session
from backend.db.utils import utcnow
from backend.domain.evolution.fitness import calculate_fitness
from backend.domain.evolution.mutation_engine import mutate_genome
from backend.domain.evolution.crossover_engine import crossover_genomes
from backend.domain.evolution.seed import FOUNDING_ARCHETYPES
from backend.domain.evolution.evolution_action import EvolutionAction
from backend.domain.genome.models import (
    FitnessMetrics,
    StrategyGenome,
)
from backend.models.database import GenomeRegistry, EvolutionLog, ShadowTrade
from backend.application.agi.genome_helpers import (
    _DEFAULT_GENE_BOUNDS,
    _genome_to_individual,
    _individual_to_genome,
    _to_strategy_genome,
    _to_strategy_genome_from_genome,
    _fitness_score_for,
    _fitness_metrics_for,
    _upsert_genome,
)

from loguru import logger


def run_mutation_cycle() -> int:
    """Select elite genomes, mutate them, and persist offspring.

    When EVOLUTION_BACKEND is 'deap', uses the EvolutionHarness for
    NSGA-II multi-objective mutation; otherwise falls back to the
    legacy mutation engine.
    """
    if not settings.EVOLUTION_ENGINE_ENABLED:
        return 0

    with _get_db_session() as db:
        population = (
            db.query(GenomeRegistry)
            .filter(
                GenomeRegistry.stage.in_(
                    ["DRAFT", "SHADOW", "PAPER", "LIVE", "BREEDING"]
                )
            )
            .all()
        )
        if not population:
            return 0

        sorted_population = sorted(population, key=_fitness_score_for, reverse=True)
        elite_count = max(
            1, min(len(sorted_population), settings.AGI_POPULATION_SIZE // 2)
        )
        elites = sorted_population[:elite_count]

        offspring_target = max(
            1, int(round(settings.AGI_POPULATION_SIZE * settings.AGI_MUTATION_RATE))
        )

        # DEAP path: use evolution harness for mutation
        if settings.EVOLUTION_BACKEND == "deap":
            backend = create_evolution_backend("deap", gene_bounds=_DEFAULT_GENE_BOUNDS)
            individuals = [
                _genome_to_individual(_to_strategy_genome(r)) for r in elites
            ]

            # Evaluate current fitness
            def _fit_fn(ind: Individual) -> tuple[float, ...]:
                # Find matching genome row for fitness
                for row in elites:
                    if row.genome_id == ind.genome_id:
                        score = _fitness_score_for(row)
                        metrics = _fitness_metrics_for(row)
                        return (score, -metrics.max_drawdown_pct)
                return (0.0, 0.0)

            backend.evaluate(individuals, _fit_fn)
            mutated_individuals = [
                backend.mutate(ind, rate=settings.AGI_MUTATION_RATE)
                for ind in individuals[:offspring_target]
            ]

            created = 0
            for mut_ind in mutated_individuals:
                parent_row = elites[created % len(elites)]
                parent = _to_strategy_genome(parent_row)
                mutated = _individual_to_genome(
                    mut_ind, parent, f"{parent.strategy_name}-deap-mut-{created + 1}"
                )
                mutated.archetype = parent.archetype
                _upsert_genome(mutated, db)
                log_evolution_action(
                    EvolutionAction(
                        action_type="mutation",
                        genome_id=mutated.genome_id,
                        strategy_name=mutated.strategy_name,
                        details={
                            "parent_genome_id": parent.genome_id,
                            "backend": "deap",
                        },
                        from_stage=parent.stage,
                        to_stage=mutated.stage,
                    ),
                    db,
                )
                created += 1

            return created

        # Legacy path: use existing mutation engine
        created = 0
        for parent_row in cycle(elites):
            if created >= offspring_target:
                break
            parent = _to_strategy_genome(parent_row)
            mutated, mutations = mutate_genome(
                parent, fitness_score=_fitness_score_for(parent_row)
            )
            mutated.archetype = parent.archetype
            mutated.strategy_name = f"{parent.strategy_name}-mut-{created + 1}"
            _upsert_genome(mutated, db)
            log_evolution_action(
                EvolutionAction(
                    action_type="mutation",
                    genome_id=mutated.genome_id,
                    strategy_name=mutated.strategy_name,
                    details={
                        "parent_genome_id": parent.genome_id,
                        "mutations": mutations,
                    },
                    from_stage=parent.stage,
                    to_stage=mutated.stage,
                ),
                db,
            )
            created += 1

        return created


def run_crossover_cycle() -> int:
    """Breed genomes from different archetypes and persist hybrid offspring.

    When EVOLUTION_BACKEND is 'deap', uses the EvolutionHarness for
    NSGA-II multi-objective crossover; otherwise falls back to the
    legacy crossover engine.
    """
    if not settings.EVOLUTION_ENGINE_ENABLED:
        return 0

    with _get_db_session() as db:
        population = (
            db.query(GenomeRegistry)
            .filter(
                GenomeRegistry.stage.in_(
                    ["DRAFT", "SHADOW", "PAPER", "LIVE", "BREEDING"]
                )
            )
            .all()
        )
        if len(population) < 2:
            return 0

        by_archetype: dict[str, list[GenomeRegistry]] = {}
        for row in population:
            by_archetype.setdefault(row.archetype, []).append(row)
        for rows in by_archetype.values():
            rows.sort(key=_fitness_score_for, reverse=True)
        archetypes = sorted(by_archetype.keys())
        if len(archetypes) < 2:
            return 0

        target = max(1, settings.AGI_POPULATION_SIZE // 4)

        # DEAP path: use evolution harness for crossover
        if settings.EVOLUTION_BACKEND == "deap":
            backend = create_evolution_backend("deap", gene_bounds=_DEFAULT_GENE_BOUNDS)
            # Build pairs from top individuals across archetypes
            pairs: list[tuple[GenomeRegistry, GenomeRegistry]] = []
            for left in range(len(archetypes)):
                for right in range(left + 1, len(archetypes)):
                    pairs.append(
                        (
                            by_archetype[archetypes[left]][0],
                            by_archetype[archetypes[right]][0],
                        )
                    )

            created = 0
            for parent_a_row, parent_b_row in pairs:
                if created >= target:
                    break
                parent_a = _to_strategy_genome(parent_a_row)
                parent_b = _to_strategy_genome(parent_b_row)
                ind_a = _genome_to_individual(parent_a)
                ind_b = _genome_to_individual(parent_b)
                child_ind_a, child_ind_b = backend.crossover(ind_a, ind_b)

                child = _individual_to_genome(
                    child_ind_a,
                    parent_a,
                    f"deap-cross-{parent_a.archetype[:8]}-{parent_b.archetype[:8]}-{created + 1}",
                )
                child.archetype = f"hybrid_{parent_a.archetype}_{parent_b.archetype}"
                _upsert_genome(child, db)
                log_evolution_action(
                    EvolutionAction(
                        action_type="crossover",
                        genome_id=child.genome_id,
                        strategy_name=child.strategy_name,
                        details={
                            "parent_a_id": parent_a.genome_id,
                            "parent_b_id": parent_b.genome_id,
                            "backend": "deap",
                        },
                        to_stage=child.stage,
                    ),
                    db,
                )
                created += 1

            return created

        # Legacy path: use existing crossover engine
        created = 0
        for left in range(len(archetypes)):
            for right in range(left + 1, len(archetypes)):
                if created >= target:
                    return created
                parent_a_row = by_archetype[archetypes[left]][0]
                parent_b_row = by_archetype[archetypes[right]][0]
                parent_a = _to_strategy_genome(parent_a_row)
                parent_b = _to_strategy_genome(parent_b_row)
                try:
                    child = crossover_genomes(parent_a, parent_b)
                except ValueError:
                    continue
                child.archetype = f"hybrid_{parent_a.archetype}_{parent_b.archetype}"
                child.strategy_name = f"cross-{parent_a.archetype[:8]}-{parent_b.archetype[:8]}-{created + 1}"
                _upsert_genome(child, db)
                log_evolution_action(
                    EvolutionAction(
                        action_type="crossover",
                        genome_id=child.genome_id,
                        strategy_name=child.strategy_name,
                        details={
                            "parent_a_id": parent_a.genome_id,
                            "parent_b_id": parent_b.genome_id,
                        },
                        to_stage=child.stage,
                    ),
                    db,
                )
                created += 1
        return created


def update_fitness_from_shadow() -> int:
    """Recalculate genome fitness using settled shadow-trade outcomes."""
    if not settings.EVOLUTION_ENGINE_ENABLED:
        return 0

    with _get_db_session() as db:
        genomes = (
            db.query(GenomeRegistry).filter(GenomeRegistry.stage != "GRAVEYARD").all()
        )
        updated = 0
        for genome in genomes:
            trades = (
                db.query(ShadowTrade)
                .filter(
                    ShadowTrade.genome_id == genome.genome_id,
                    ShadowTrade.settled.is_(True),
                    ShadowTrade.pnl.isnot(None),
                )
                .all()
            )
            if not trades:
                continue

            pnl_values = [float(t.pnl or 0.0) for t in trades]
            positive = sum(p for p in pnl_values if p > 0)
            negative = abs(sum(p for p in pnl_values if p < 0))
            wins = sum(1 for p in pnl_values if p > 0)
            avg = sum(pnl_values) / len(pnl_values)
            std = statistics.pstdev(pnl_values) if len(pnl_values) > 1 else 0.0
            sharpe = avg / std if std > 0 else 0.0

            cumulative = 0.0
            peak = 0.0
            max_drawdown = 0.0
            for pnl in pnl_values:
                cumulative += pnl
                peak = max(peak, cumulative)
                if peak > 0:
                    max_drawdown = max(max_drawdown, (peak - cumulative) / peak)

            brier_inputs = [
                (float(t.predicted_outcome), float(t.actual_outcome))
                for t in trades
                if t.predicted_outcome is not None and t.actual_outcome is not None
            ]
            brier = (
                sum((pred - actual) ** 2 for pred, actual in brier_inputs)
                / len(brier_inputs)
                if brier_inputs
                else 0.25
            )
            metrics = FitnessMetrics(
                sharpe_ratio=sharpe,
                win_rate=wins / len(trades),
                profit_factor=(
                    positive / negative
                    if negative > 0
                    else (positive if positive > 0 else 0.0)
                ),
                max_drawdown_pct=max_drawdown,
                brier_score=brier,
                alpha_per_trade=avg,
                capital_rotation_efficiency=min(1.0, max(0.0, wins / len(trades))),
                total_trades=len(trades),
                last_evaluated=datetime.now(timezone.utc),
            )
            genome.fitness_json = metrics.model_dump_json()
            genome.updated_at = utcnow()
            updated += 1

        return updated


def rebalance_population() -> int:
    """Ensure minimum archetype diversity inside configured population bounds."""
    if not settings.EVOLUTION_ENGINE_ENABLED:
        return 0

    with _get_db_session() as db:
        active = (
            db.query(GenomeRegistry)
            .filter(
                GenomeRegistry.stage.in_(
                    ["DRAFT", "SHADOW", "PAPER", "LIVE", "BREEDING"]
                )
            )
            .all()
        )
        if not active:
            return 0

        target_population = max(1, settings.AGI_POPULATION_SIZE)
        if len(active) >= target_population:
            return 0

        counts: dict[str, int] = {}
        fitness_by_id: dict[str, float] = {}
        for genome in active:
            counts[genome.archetype] = counts.get(genome.archetype, 0) + 1
            fitness_by_id[genome.genome_id] = _fitness_score_for(genome)

        expected_archetypes = [archetype for _, archetype, _ in FOUNDING_ARCHETYPES]
        missing = [a for a in expected_archetypes if counts.get(a, 0) == 0]
        if not missing:
            return 0

        donor_cycle = cycle(sorted(active, key=_fitness_score_for, reverse=True))
        created = 0
        remaining_capacity = target_population - len(active)
        for archetype in missing[:remaining_capacity]:
            donor_row = next(donor_cycle)
            donor = _to_strategy_genome(donor_row)
            child, _ = mutate_genome(
                donor, fitness_score=fitness_by_id.get(donor.genome_id, 0.0)
            )
            child.archetype = archetype
            child.strategy_name = f"rebalance-{archetype}-{created + 1}"
            _upsert_genome(child, db)
            log_evolution_action(
                EvolutionAction(
                    action_type="rebalance",
                    genome_id=child.genome_id,
                    strategy_name=child.strategy_name,
                    details={
                        "source_genome_id": donor.genome_id,
                        "target_archetype": archetype,
                    },
                    to_stage=child.stage,
                ),
                db,
            )
            created += 1
        return created


def log_evolution_action(action: EvolutionAction, db: Session) -> None:
    """Log evolution action to database and publish as event."""
    # Log to evolution_log table
    evolution_log = EvolutionLog(
        genome_id=action.genome_id,
        event_type=action.action_type,
        from_stage=action.from_stage,
        to_stage=action.to_stage,
        data=action.details,
        timestamp=action.timestamp,
    )
    db.add(evolution_log)
    db.commit()

    # Publish event
    publish_event("evolution_action", action.to_dict())
    logger.info(
        f"Evolution action logged: {action.action_type} for genome {action.genome_id}"
    )


def targeted_mutation(genome_id: str, chrom_name: str, db) -> None:
    """Apply a targeted mutation to a specific chromosome of a genome.

    Invoked reactively when a chromosome is flagged by performance attributor.
    Only mutates the specified chromosome (not the whole genome).

    Args:
        genome_id: ID of the genome to mutate
        chrom_name: Name of the chromosome to target
        db: Database session
    """
    try:
        genome = db.query(GenomeRegistry).filter_by(genome_id=genome_id).first()
        if not genome:
            logger.warning(f"Targeted mutation: genome {genome_id} not found")
            return

        # Only mutate the flagged chromosome
        mutated, _ = mutate_genome(
            genome, market_regime="neutral", targeted_chrom=chrom_name
        )
        if mutated and mutated.genome_id != genome.genome_id:
            mutated.fitness_score = calculate_fitness(mutated.fitness_metrics)
            mutated.total_pnl = mutated.fitness_metrics.total_pnl or 0.0
            mutated.win_rate = mutated.fitness_metrics.win_rate or 0.0
            mutated.sharpe_ratio = mutated.fitness_metrics.sharpe_ratio or 0.0
            mutated.max_drawdown_pct = mutated.fitness_metrics.max_drawdown_pct or 0.0
            mutated.trade_count = mutated.fitness_metrics.total_trades or 0
            mutated.fitness_updated_at = utcnow()
            mutated.last_evaluated_at = utcnow()
            db.add(mutated)

            action = EvolutionAction(
                action_type="targeted_mutation",
                genome_id=mutated.genome_id,
                strategy_name=mutated.strategy_name,
                details={
                    "parent_genome_id": genome.genome_id,
                    "targeted_chrom": chrom_name,
                    "mutation_strategy": "targeted_tweak",
                },
                from_stage=genome.stage,
                to_stage=genome.stage,
            )
            log_evolution_action(action, db)

            logger.info(
                f"Targeted mutation applied: {genome.strategy_name} -> {mutated.strategy_name} (chrom={chrom_name})"
            )
    except Exception as e:
        logger.error(
            f"Targeted mutation failed for genome {genome_id}: {e}", exc_info=True
        )
