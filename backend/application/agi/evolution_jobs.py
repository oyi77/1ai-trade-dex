"""Evolution engine APScheduler jobs.

Wave 10: Evolution Scheduler — Part 7
Contains the job functions for fitness evaluation, mutation cycles, crossover cycles,
necromancy analysis, and regime rebalancing.
"""

import json
import logging
import statistics
from datetime import datetime, timezone
from itertools import cycle

from sqlalchemy.orm import Session

from backend.config import settings
from backend.core.event_bus import publish_event
from backend.db.utils import get_db_session as _get_db_session
from backend.domain.evolution.fitness import calculate_fitness
from backend.domain.genome.models import (
    CognitionChromosome,
    ExecutionChromosome,
    FitnessMetrics,
    LineageData,
    MetaChromosome,
    PerceptionChromosome,
    RiskChromosome,
    StrategyGenome,
)
from backend.domain.evolution.mutation_engine import mutate_genome
from backend.domain.evolution.crossover_engine import crossover_genomes
from backend.domain.evolution.seed import FOUNDING_ARCHETYPES
from backend.application.agi.necromancer import run_necromancy_analysis
from backend.application.agi.regime_population_manager import detect_regime_and_rebalance
from backend.domain.evolution.evolution_action import EvolutionAction
from backend.models.database import GenomeRegistry, EvolutionLog, ShadowTrade

logger = logging.getLogger(__name__)


def _safe_load_json(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _fitness_metrics_for(genome_row: GenomeRegistry) -> FitnessMetrics:
    raw = _safe_load_json(genome_row.fitness_json)
    filtered = {k: v for k, v in raw.items() if k in FitnessMetrics.model_fields}
    return FitnessMetrics(**filtered)


def _fitness_score_for(genome_row: GenomeRegistry) -> float:
    return calculate_fitness(_fitness_metrics_for(genome_row))


def _chromosomes_for(genome_row: GenomeRegistry) -> dict:
    raw = _safe_load_json(genome_row.chromosomes_json)
    return {
        "perception": PerceptionChromosome(**raw.get("perception", {})),
        "cognition": CognitionChromosome(
            **raw.get(
                "cognition",
                {
                    "entry_logic": {
                        "trigger_type": "threshold_cross",
                        "conditions": [{"indicator": "rsi", "operator": ">", "value": 70.0}],
                    },
                    "exit_logic": {"trigger_type": "time_based"},
                    "market_selector": {},
                },
            )
        ),
        "execution": ExecutionChromosome(**raw.get("execution", {})),
        "risk": RiskChromosome(**raw.get("risk", {})),
        "meta": MetaChromosome(**raw.get("meta", {})),
    }


def _to_strategy_genome(genome_row: GenomeRegistry) -> StrategyGenome:
    lineage_raw = _safe_load_json(genome_row.lineage_json)
    lineage = (
        LineageData(**lineage_raw)
        if lineage_raw
        else LineageData(parent_genome_ids=[genome_row.genome_id], generation=1, creator="human")
    )
    return StrategyGenome(
        genome_id=genome_row.genome_id,
        strategy_name=genome_row.strategy_name,
        archetype=genome_row.archetype,
        version=genome_row.version,
        stage=genome_row.stage,
        lineage=lineage,
        chromosomes=_chromosomes_for(genome_row),
        fitness_metrics=_fitness_metrics_for(genome_row),
        created_at=genome_row.created_at or datetime.now(timezone.utc),
        updated_at=genome_row.updated_at or datetime.now(timezone.utc),
    )


def _chromosomes_to_json(chromosomes: dict) -> str:
    serialized = {}
    for name, chromosome in chromosomes.items():
        serialized[name] = chromosome.model_dump() if hasattr(chromosome, "model_dump") else chromosome
    return json.dumps(serialized)


def _upsert_genome(genome: StrategyGenome, db: Session) -> None:
    now = datetime.now(timezone.utc)
    existing = db.query(GenomeRegistry).filter(GenomeRegistry.genome_id == genome.genome_id).first()
    if existing:
        existing.strategy_name = genome.strategy_name
        existing.archetype = genome.archetype
        existing.version = genome.version
        existing.stage = genome.stage
        existing.lineage_json = genome.lineage.model_dump_json()
        existing.chromosomes_json = _chromosomes_to_json(genome.chromosomes)
        existing.fitness_json = genome.fitness_metrics.model_dump_json()
        existing.updated_at = now
        return

    db.add(
        GenomeRegistry(
            genome_id=genome.genome_id,
            strategy_name=genome.strategy_name,
            archetype=genome.archetype,
            version=genome.version,
            stage=genome.stage,
            lineage_json=genome.lineage.model_dump_json(),
            chromosomes_json=_chromosomes_to_json(genome.chromosomes),
            fitness_json=genome.fitness_metrics.model_dump_json(),
            created_at=now,
            updated_at=now,
            stage_entered_at=now,
        )
    )


def run_mutation_cycle() -> int:
    """Select elite genomes, mutate them, and persist offspring."""
    if not settings.EVOLUTION_ENGINE_ENABLED:
        return 0

    with _get_db_session() as db:
        population = (
            db.query(GenomeRegistry)
            .filter(GenomeRegistry.stage.in_(["DRAFT", "SHADOW", "PAPER", "LIVE", "BREEDING"]))
            .all()
        )
        if not population:
            return 0

        sorted_population = sorted(population, key=_fitness_score_for, reverse=True)
        elite_count = max(1, min(len(sorted_population), settings.AGI_POPULATION_SIZE // 2))
        elites = sorted_population[:elite_count]

        offspring_target = max(1, int(round(settings.AGI_POPULATION_SIZE * settings.AGI_MUTATION_RATE)))
        created = 0
        for parent_row in cycle(elites):
            if created >= offspring_target:
                break
            parent = _to_strategy_genome(parent_row)
            mutated, mutations = mutate_genome(parent, fitness_score=_fitness_score_for(parent_row))
            mutated.archetype = parent.archetype
            mutated.strategy_name = f"{parent.strategy_name}-mut-{created + 1}"
            _upsert_genome(mutated, db)
            log_evolution_action(
                EvolutionAction(
                    action_type="mutation",
                    genome_id=mutated.genome_id,
                    strategy_name=mutated.strategy_name,
                    details={"parent_genome_id": parent.genome_id, "mutations": mutations},
                    from_stage=parent.stage,
                    to_stage=mutated.stage,
                ),
                db,
            )
            created += 1

        return created


def run_crossover_cycle() -> int:
    """Breed genomes from different archetypes and persist hybrid offspring."""
    if not settings.EVOLUTION_ENGINE_ENABLED:
        return 0

    with _get_db_session() as db:
        population = (
            db.query(GenomeRegistry)
            .filter(GenomeRegistry.stage.in_(["DRAFT", "SHADOW", "PAPER", "LIVE", "BREEDING"]))
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
                        details={"parent_a_id": parent_a.genome_id, "parent_b_id": parent_b.genome_id},
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
        genomes = db.query(GenomeRegistry).filter(GenomeRegistry.stage != "GRAVEYARD").all()
        updated = 0
        for genome in genomes:
            trades = (
                db.query(ShadowTrade)
                .filter(ShadowTrade.genome_id == genome.genome_id, ShadowTrade.actual_outcome.isnot(None))
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
                sum((pred - actual) ** 2 for pred, actual in brier_inputs) / len(brier_inputs)
                if brier_inputs
                else 0.25
            )
            metrics = FitnessMetrics(
                sharpe_ratio=sharpe,
                win_rate=wins / len(trades),
                profit_factor=positive / negative if negative > 0 else (positive if positive > 0 else 0.0),
                max_drawdown_pct=max_drawdown,
                brier_score=brier,
                alpha_per_trade=avg,
                capital_rotation_efficiency=min(1.0, max(0.0, wins / len(trades))),
                total_trades=len(trades),
                last_evaluated=datetime.now(timezone.utc),
            )
            genome.fitness_json = metrics.model_dump_json()
            genome.updated_at = datetime.now(timezone.utc)
            updated += 1

        return updated


def rebalance_population() -> int:
    """Ensure minimum archetype diversity inside configured population bounds."""
    if not settings.EVOLUTION_ENGINE_ENABLED:
        return 0

    with _get_db_session() as db:
        active = (
            db.query(GenomeRegistry)
            .filter(GenomeRegistry.stage.in_(["DRAFT", "SHADOW", "PAPER", "LIVE", "BREEDING"]))
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
            child, _ = mutate_genome(donor, fitness_score=fitness_by_id.get(donor.genome_id, 0.0))
            child.archetype = archetype
            child.strategy_name = f"rebalance-{archetype}-{created + 1}"
            _upsert_genome(child, db)
            log_evolution_action(
                EvolutionAction(
                    action_type="rebalance",
                    genome_id=child.genome_id,
                    strategy_name=child.strategy_name,
                    details={"source_genome_id": donor.genome_id, "target_archetype": archetype},
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
    logger.info(f"Evolution action logged: {action.action_type} for genome {action.genome_id}")


def fitness_evaluation_job() -> None:
    """Backward-compatible wrapper for shadow fitness updates."""
    updated = update_fitness_from_shadow()
    logger.info("Fitness evaluation completed for %s genomes", updated)


def mutation_cycle_job() -> None:
    """Backward-compatible wrapper for the evolution mutation cycle."""
    created = run_mutation_cycle()
    logger.info("Mutation cycle completed, created %s offspring", created)


def crossover_cycle_job() -> None:
    """Backward-compatible wrapper for the evolution crossover cycle."""
    created = run_crossover_cycle()
    logger.info("Crossover cycle completed, created %s offspring", created)


def necromancy_analysis_job() -> None:
    """Run necromancy analysis on graveyard genomes. Runs weekly."""
    if not settings.EVOLUTION_ENGINE_ENABLED:
        logger.debug("Evolution engine disabled, skipping necromancy analysis")
        return

    logger.info("Starting necromancy analysis job")
    with _get_db_session() as db:
        # Run necromancy analysis
        report = run_necromancy_analysis(db)

        # Log evolution action
        action = EvolutionAction(
            action_type="necromancy",
            genome_id="system",
            strategy_name="necromancer",
            details={
                "death_causes": report.death_causes,
                "high_risk_genes": len(report.high_risk_genes),
                "legend_genes": len(report.legend_genes),
                "new_anti_patterns": len(report.new_anti_patterns)
            },
        )
        log_evolution_action(action, db)

        logger.info("Necromancy analysis completed")


def regime_rebalancing_job() -> None:
    """Detect market regime and rebalance strategy population. Runs every 4 hours."""
    if not settings.EVOLUTION_ENGINE_ENABLED:
        logger.debug("Evolution engine disabled, skipping regime rebalancing")
        return

    logger.info("Starting regime rebalancing job")
    with _get_db_session() as db:
        # Detect regime and rebalance
        regime, changes = detect_regime_and_rebalance(db)

        # Log evolution action
        action = EvolutionAction(
            action_type="regime_rebalance",
            genome_id="system",
            strategy_name="regime_detector",
            details={
                "detected_regime": regime,
                "population_changes": changes
            },
        )
        log_evolution_action(action, db)

        logger.info(f"Regime rebalancing completed, detected regime: {regime}")


def shadow_validation_job() -> None:
    """Score shadow predictions — evaluate accuracy of SHADOW stage genomes.
    Runs every 5 minutes. Promotes accurate SHADOW genomes to PAPER."""
    if not settings.EVOLUTION_ENGINE_ENABLED:
        logger.debug("Evolution engine disabled, skipping shadow validation")
        return

    logger.info("Starting shadow validation job")
    with _get_db_session() as db:
        from backend.models.database import ShadowTrade
        shadow_genomes = db.query(GenomeRegistry).filter(
            GenomeRegistry.stage == "SHADOW"
        ).all()

        promoted = 0
        for genome in shadow_genomes:
            trades = db.query(ShadowTrade).filter(
                ShadowTrade.genome_id == genome.genome_id,
                ShadowTrade.actual_outcome.isnot(None)
            ).all()

            if len(trades) < 10:
                continue

            correct = sum(1 for t in trades if t.accuracy_score is not None and t.accuracy_score < 0.2)
            accuracy = correct / len(trades) if trades else 0.0

            if accuracy >= 0.60:
                genome.stage = "PAPER"
                action = EvolutionAction(
                    action_type="promote",
                    genome_id=genome.genome_id,
                    strategy_name=genome.strategy_name,
                    from_stage="SHADOW",
                    to_stage="PAPER",
                    details={"accuracy": accuracy, "total_trades": len(trades)},
                )
                log_evolution_action(action, db)
                promoted += 1

        db.commit()
        logger.info(f"Shadow validation completed, promoted {promoted} genomes")


def full_population_review_job() -> None:
    """Full population census — review all genomes, auto-kill underperformers,
    update fitness tiers. Runs weekly."""
    if not settings.EVOLUTION_ENGINE_ENABLED:
        logger.debug("Evolution engine disabled, skipping population review")
        return

    logger.info("Starting full population review job")
    with _get_db_session() as db:
        genomes = db.query(GenomeRegistry).filter(
            GenomeRegistry.stage.in_(["DRAFT", "SHADOW", "PAPER", "LIVE", "BREEDING"])
        ).all()

        killed = 0
        for genome in genomes:
            fitness = calculate_fitness(genome.fitness_metrics) if genome.fitness_metrics else 0.0
            genome.fitness_score = fitness

            if fitness < 0.30 and genome.fitness_metrics and genome.fitness_metrics.total_trades >= 20:
                genome.stage = "GRAVEYARD"
                action = EvolutionAction(
                    action_type="kill",
                    genome_id=genome.genome_id,
                    strategy_name=genome.strategy_name,
                    from_stage=genome.stage,
                    to_stage="GRAVEYARD",
                    details={"fitness_score": fitness, "reason": "below_kill_threshold"},
                )
                log_evolution_action(action, db)
                killed += 1

        db.commit()
        logger.info(f"Population review completed: {len(genomes)} genomes, {killed} killed")


def legend_evaluation_job() -> None:
    """Evaluate LIVE genomes for LEGEND status. Requirements:
    Live 60d + fitness > 0.85 + total PnL > $500. Runs monthly."""
    if not settings.EVOLUTION_ENGINE_ENABLED:
        logger.debug("Evolution engine disabled, skipping legend evaluation")
        return

    logger.info("Starting legend evaluation job")
    with _get_db_session() as db:
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=60)

        live_genomes = db.query(GenomeRegistry).filter(
            GenomeRegistry.stage == "LIVE",
            GenomeRegistry.created_at <= cutoff,
        ).all()

        legends = 0
        for genome in live_genomes:
            fitness = calculate_fitness(genome.fitness_metrics) if genome.fitness_metrics else 0.0
            if fitness > 0.85 and genome.fitness_metrics and genome.fitness_metrics.profit_factor > 2.0:
                genome.stage = "LEGEND"
                action = EvolutionAction(
                    action_type="promote",
                    genome_id=genome.genome_id,
                    strategy_name=genome.strategy_name,
                    from_stage="LIVE",
                    to_stage="LEGEND",
                    details={"fitness_score": fitness, "legend_criteria_met": True},
                )
                log_evolution_action(action, db)
                publish_event("genome_promoted", {
                    "genome_id": genome.genome_id,
                    "from": "LIVE",
                    "to": "LEGEND",
                })
                legends += 1

        db.commit()
        logger.info(f"Legend evaluation completed, {legends} new legends")


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
        mutated = mutate_genome(genome, market_regime="neutral", targeted_chrom=chrom_name)
        if mutated and mutated.genome_id != genome.genome_id:
            db.add(mutated)

            action = EvolutionAction(
                action_type="targeted_mutation",
                genome_id=mutated.genome_id,
                strategy_name=mutated.strategy_name,
                details={
                    "parent_genome_id": genome.genome_id,
                    "targeted_chrom": chrom_name,
                    "mutation_strategy": "targeted_tweak"
                },
                from_stage=genome.stage,
                to_stage=genome.stage,
            )
            log_evolution_action(action, db)

            logger.info(f"Targeted mutation applied: {genome.strategy_name} -> {mutated.strategy_name} (chrom={chrom_name})")
    except Exception as e:
        logger.error(f"Targeted mutation failed for genome {genome_id}: {e}", exc_info=True)
