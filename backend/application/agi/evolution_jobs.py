"""Evolution engine APScheduler jobs.

Wave 10: Evolution Scheduler — Part 7
Contains the job functions for fitness evaluation, mutation cycles, crossover cycles,
necromancy analysis, and regime rebalancing.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.utils import get_db_session as _get_db_session
from backend.core.event_bus import publish_event
import json

from backend.domain.evolution.fitness import calculate_fitness
from backend.domain.genome.models import FitnessMetrics
from backend.domain.evolution.mutation_engine import mutate_genome
from backend.domain.evolution.crossover_engine import crossover_genomes
from backend.application.agi.necromancer import run_necromancy_analysis
from backend.application.agi.regime_population_manager import detect_regime_and_rebalance
from backend.domain.evolution.evolution_action import EvolutionAction
from backend.models.database import GenomeRegistry, EvolutionLog

logger = logging.getLogger(__name__)


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
    """Evaluate fitness for all active genomes. Runs every 60 seconds."""
    if not settings.EVOLUTION_ENGINE_ENABLED:
        logger.debug("Evolution engine disabled, skipping fitness evaluation")
        return

    logger.info("Starting fitness evaluation job")
    with _get_db_session() as db:
        # Get all active genomes (not in GRAVEYARD stage)
        genomes = db.query(GenomeRegistry).filter(
            GenomeRegistry.stage != "GRAVEYARD"
        ).all()

        for genome in genomes:
            try:
                raw = json.loads(genome.fitness_json) if genome.fitness_json else {}
                metrics = FitnessMetrics(**{k: v for k, v in raw.items() if k in FitnessMetrics.model_fields})
                fitness_score = calculate_fitness(metrics)

                genome.fitness_score = fitness_score
                genome.fitness_updated_at = datetime.now(timezone.utc)

                # Log evolution action
                action = EvolutionAction(
                    action_type="fitness_eval",
                    genome_id=genome.genome_id,
                    strategy_name=genome.strategy_name,
                    details={"fitness_score": fitness_score},
                )
                log_evolution_action(action, db)

                logger.debug(f"Fitness evaluated for {genome.strategy_name}: {fitness_score}")

            except Exception as e:
                logger.error(f"Error evaluating fitness for {genome.strategy_name}: {e}")

        db.commit()
        logger.info(f"Fitness evaluation completed for {len(genomes)} genomes")


def mutation_cycle_job() -> None:
    """Run mutation cycle for eligible genomes. Runs every 6 hours."""
    if not settings.EVOLUTION_ENGINE_ENABLED:
        logger.debug("Evolution engine disabled, skipping mutation cycle")
        return

    logger.info("Starting mutation cycle job")
    with _get_db_session() as db:
        # Get genomes eligible for mutation (DRAFT stage, fitness > 0.3)
        eligible_genomes = db.query(GenomeRegistry).filter(
            GenomeRegistry.stage == "DRAFT",
            GenomeRegistry.fitness_score > 0.3
        ).order_by(GenomeRegistry.fitness_score.desc()).limit(5).all()

        for genome in eligible_genomes:
            try:
                # Mutate the genome
                mutated_genome = mutate_genome(genome)

                # Save mutated genome to registry
                db.add(mutated_genome)

                # Log evolution action
                action = EvolutionAction(
                    action_type="mutation",
                    genome_id=mutated_genome.genome_id,
                    strategy_name=mutated_genome.strategy_name,
                    details={
                        "parent_genome_id": genome.genome_id,
                        "mutation_strategy": "random_tweak"
                    },
                    from_stage="DRAFT",
                    to_stage="DRAFT",
                )
                log_evolution_action(action, db)

                logger.info(f"Mutated genome {genome.strategy_name} -> {mutated_genome.strategy_name}")

            except Exception as e:
                logger.error(f"Error mutating genome {genome.strategy_name}: {e}")

        db.commit()
        logger.info(f"Mutation cycle completed for {len(eligible_genomes)} genomes")


def crossover_cycle_job() -> None:
    """Run crossover cycle for elite genomes. Runs weekly."""
    if not settings.EVOLUTION_ENGINE_ENABLED:
        logger.debug("Evolution engine disabled, skipping crossover cycle")
        return

    logger.info("Starting crossover cycle job")
    with _get_db_session() as db:
        # Get elite genomes (fitness > 0.75)
        elite_genomes = db.query(GenomeRegistry).filter(
            GenomeRegistry.fitness_score > 0.75
        ).order_by(GenomeRegistry.fitness_score.desc()).limit(10).all()

        # Pair them up for crossover
        for i in range(0, len(elite_genomes) - 1, 2):
            parent_a = elite_genomes[i]
            parent_b = elite_genomes[i + 1]

            try:
                # Perform crossover
                child_genome = crossover_genomes(parent_a, parent_b)

                # Save child genome to registry
                db.add(child_genome)

                # Log evolution action
                action = EvolutionAction(
                    action_type="crossover",
                    genome_id=child_genome.genome_id,
                    strategy_name=child_genome.strategy_name,
                    details={
                        "parent_a_id": parent_a.genome_id,
                        "parent_b_id": parent_b.genome_id,
                        "market_regime": "neutral"
                    },
                    from_stage=None,
                    to_stage="DRAFT",
                )
                log_evolution_action(action, db)

                logger.info(f"Crossover created {child_genome.strategy_name} from {parent_a.strategy_name} x {parent_b.strategy_name}")

            except Exception as e:
                logger.error(f"Error in crossover for {parent_a.strategy_name} x {parent_b.strategy_name}: {e}")

        db.commit()
        logger.info(f"Crossover cycle completed, created {len(elite_genomes) // 2} children")


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
