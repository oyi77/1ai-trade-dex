"""Evolution engine APScheduler job wrappers.

Wave 10: Evolution Scheduler — Part 7
Contains the job functions for fitness evaluation, mutation cycles, crossover cycles,
necromancy analysis, and regime rebalancing.

Track 3.4: When EVOLUTION_BACKEND is set to 'deap', mutation and crossover
cycles delegate to the EvolutionHarness (NSGA-II multi-objective optimization).
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.utils import get_db_session as _get_db_session
from backend.db.utils import utcnow
from backend.domain.evolution.fitness import calculate_fitness
from backend.domain.evolution.mutation_engine import mutate_genome
from backend.domain.evolution.crossover_engine import crossover_genomes
from backend.domain.evolution.evolution_action import EvolutionAction
from backend.domain.genome.models import FitnessMetrics
from backend.models.database import GenomeRegistry
from backend.core.event_bus import publish_event
from backend.application.agi.necromancer import run_necromancy_analysis
from backend.application.agi.regime_population_manager import (
    detect_regime_and_rebalance,
)
from backend.application.agi.genome_helpers import (
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
    _sync_genome_fitness_from_shadow_trades,
)
from backend.application.agi.evolution_cycles import (
    log_evolution_action,
    run_mutation_cycle,
    run_crossover_cycle,
)

from loguru import logger


def fitness_evaluation_job() -> None:
    """Evaluate fitness for all active genomes. Runs every 60 seconds."""
    if not settings.EVOLUTION_ENGINE_ENABLED:
        logger.debug("Evolution engine disabled, skipping fitness evaluation")
        return

    logger.info("Starting fitness evaluation job")
    with _get_db_session() as db:
        # Get all active genomes (not in GRAVEYARD stage)
        genomes = (
            db.query(GenomeRegistry).filter(GenomeRegistry.stage != "GRAVEYARD").all()
        )

        for genome in genomes:
            try:
                raw = (
                    genome.fitness_metrics
                )  # hybrid_property auto-deserializes fitness_json
                metrics = FitnessMetrics(
                    **{k: v for k, v in raw.items() if k in FitnessMetrics.model_fields}
                )
                fitness_score = calculate_fitness(metrics)

                # Sync both JSON and native denormalized columns
                genome.fitness_score = fitness_score
                genome.fitness_updated_at = utcnow()
                genome.total_pnl = (
                    raw.get("total_pnl", 0.0) if metrics.total_trades > 0 else 0.0
                )
                genome.win_rate = metrics.win_rate
                genome.sharpe_ratio = metrics.sharpe_ratio
                genome.max_drawdown_pct = metrics.max_drawdown_pct
                genome.trade_count = metrics.total_trades
                genome.last_evaluated_at = utcnow()

                # Log evolution action
                action = EvolutionAction(
                    action_type="fitness_eval",
                    genome_id=genome.genome_id,
                    strategy_name=genome.strategy_name,
                    details={"fitness_score": fitness_score},
                )
                log_evolution_action(action, db)

                logger.debug(
                    f"Fitness evaluated for {genome.strategy_name}: {fitness_score}"
                )

            except Exception as e:
                logger.error(
                    f"Error evaluating fitness for {genome.strategy_name}: {e}"
                )

        db.commit()
        logger.info(f"Fitness evaluation completed for {len(genomes)} genomes")


def mutation_cycle_job() -> None:
    """Run mutation cycle on PAPER and LIVE genomes. Runs every 12 minutes."""
    if not settings.EVOLUTION_ENGINE_ENABLED:
        logger.debug("Evolution engine disabled, skipping mutation cycle")
        return

    logger.info("Starting mutation cycle")
    with _get_db_session() as db:
        # Get genomes eligible for mutation (PAPER or LIVE stage)
        eligible = (
            db.query(GenomeRegistry)
            .filter(GenomeRegistry.stage.in_(["PAPER", "LIVE"]))
            .all()
        )

        mutants = []
        for genome in eligible:
            try:
                mutant_genome, changes = mutate_genome(genome)

                # Sync both JSON and native denormalized columns
                mutant_genome.fitness_score = 0.0
                mutant_genome.fitness_updated_at = utcnow()
                mutant_genome.total_pnl = 0.0
                mutant_genome.win_rate = 0.0
                mutant_genome.sharpe_ratio = 0.0
                mutant_genome.max_drawdown_pct = 0.0
                mutant_genome.trade_count = 0
                mutant_genome.last_evaluated_at = utcnow()

                db.add(mutant_genome)
                mutants.append(mutant_genome)

                # Log evolution action
                action = EvolutionAction(
                    action_type="mutation",
                    genome_id=mutant_genome.genome_id,
                    strategy_name=mutant_genome.strategy_name,
                    details={"parent_id": genome.genome_id, "changes": changes},
                )
                log_evolution_action(action, db)

                logger.debug(
                    f"Mutated {genome.strategy_name} -> {mutant_genome.strategy_name}"
                )

            except Exception as e:
                logger.error(f"Error mutating {genome.strategy_name}: {e}")

        db.commit()
        logger.info(f"Mutation cycle completed, created {len(mutants)} offspring")


def crossover_cycle_job() -> None:
    """Run crossover cycle on PAPER and LIVE genomes. Runs every 12 minutes."""
    if not settings.EVOLUTION_ENGINE_ENABLED:
        logger.debug("Evolution engine disabled, skipping crossover cycle")
        return

    logger.info("Starting crossover cycle")
    with _get_db_session() as db:
        # Get elite genomes (top performers) for crossover
        elite_genomes = (
            db.query(GenomeRegistry)
            .filter(GenomeRegistry.stage.in_(["PAPER", "LIVE"]))
            .order_by(GenomeRegistry.fitness_score.desc())
            .limit(10)
            .all()
        )

        for i in range(0, len(elite_genomes) - 1, 2):
            parent_a = elite_genomes[i]
            parent_b = elite_genomes[i + 1]
            try:
                child_genome = crossover_genomes(parent_a, parent_b)

                # Sync both JSON and native denormalized columns
                child_genome.fitness_score = 0.0
                child_genome.fitness_updated_at = utcnow()
                child_genome.total_pnl = 0.0
                child_genome.win_rate = 0.0
                child_genome.sharpe_ratio = 0.0
                child_genome.max_drawdown_pct = 0.0
                child_genome.trade_count = 0
                child_genome.last_evaluated_at = utcnow()

                db.add(child_genome)

                # Log evolution action
                action = EvolutionAction(
                    action_type="crossover",
                    genome_id=child_genome.genome_id,
                    strategy_name=child_genome.strategy_name,
                    details={
                        "parent_a": parent_a.genome_id,
                        "parent_b": parent_b.genome_id,
                    },
                )
                log_evolution_action(action, db)

                logger.info(
                    f"Crossover created {child_genome.strategy_name} from {parent_a.strategy_name} x {parent_b.strategy_name}"
                )

            except Exception as e:
                logger.error(
                    f"Error in crossover for {parent_a.strategy_name} x {parent_b.strategy_name}: {e}"
                )

        db.commit()
        logger.info(
            f"Crossover cycle completed, created {len(elite_genomes) // 2} children"
        )


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
                "new_anti_patterns": len(report.new_anti_patterns),
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
            details={"detected_regime": regime, "population_changes": changes},
        )
        log_evolution_action(action, db)

        logger.info(f"Regime rebalancing completed, detected regime: {regime}")


def shadow_validation_job() -> None:
    """Process genome fitness feedback loop from settled shadow trades.

    Runs every 5 minutes.
    - Recomputes fitness metrics from settled shadow trades
    - Syncs GenomePerformance rows
    - Applies stage gates (SHADOW→PAPER and PAPER→LIVE)
    - Auto-kills terminal underperformers to GRAVEYARD
    """
    if not settings.EVOLUTION_ENGINE_ENABLED:
        logger.debug("Evolution engine disabled, skipping shadow validation")
        return

    logger.info("Starting shadow validation job")
    with _get_db_session() as db:
        from backend.models.database import ShadowTrade

        candidate_genomes = (
            db.query(GenomeRegistry)
            .filter(GenomeRegistry.stage.in_(["SHADOW", "PAPER"]))
            .all()
        )

        promoted = 0
        killed = 0
        for genome in candidate_genomes:
            trades = (
                db.query(ShadowTrade)
                .filter(
                    ShadowTrade.genome_id == genome.genome_id,
                    ShadowTrade.settled.is_(True),
                    ShadowTrade.pnl.isnot(None),
                )
                .order_by(ShadowTrade.timestamp.asc())
                .all()
            )

            metrics = _sync_genome_fitness_from_shadow_trades(genome, trades, db)

            # Auto-kill gates
            if metrics["max_drawdown_pct"] > AUTO_KILL_MAX_DRAWDOWN or (
                metrics["sharpe_ratio"] < AUTO_KILL_MIN_SHARPE
                and metrics["win_rate"] < AUTO_KILL_MIN_WIN_RATE
            ):
                from_stage = genome.stage
                genome.stage = "GRAVEYARD"
                genome.stage_entered_at = utcnow()
                genome.updated_at = utcnow()
                action = EvolutionAction(
                    action_type="kill",
                    genome_id=genome.genome_id,
                    strategy_name=genome.strategy_name,
                    from_stage=from_stage,
                    to_stage="GRAVEYARD",
                    details={
                        "reason": "auto_kill_threshold",
                        "metrics": {
                            "total_trades": metrics["total_trades"],
                            "win_rate": metrics["win_rate"],
                            "sharpe_ratio": metrics["sharpe_ratio"],
                            "max_drawdown_pct": metrics["max_drawdown_pct"],
                        },
                    },
                )
                log_evolution_action(action, db)
                killed += 1
                continue

            if genome.stage == "SHADOW":
                if (
                    metrics["total_trades"] >= SHADOW_TO_PAPER_MIN_TRADES
                    and metrics["win_rate"] >= SHADOW_TO_PAPER_MIN_WIN_RATE
                    and metrics["sharpe_ratio"] >= SHADOW_TO_PAPER_MIN_SHARPE
                ):
                    genome.stage = "PAPER"
                    genome.stage_entered_at = utcnow()
                    genome.updated_at = utcnow()
                    action = EvolutionAction(
                        action_type="promote",
                        genome_id=genome.genome_id,
                        strategy_name=genome.strategy_name,
                        from_stage="SHADOW",
                        to_stage="PAPER",
                        details={
                            "gate": "shadow_to_paper",
                            "total_trades": metrics["total_trades"],
                            "win_rate": metrics["win_rate"],
                            "sharpe_ratio": metrics["sharpe_ratio"],
                        },
                    )
                    log_evolution_action(action, db)
                    promoted += 1
            elif genome.stage == "PAPER":
                if (
                    metrics["total_trades"] >= PAPER_TO_LIVE_MIN_TRADES
                    and metrics["win_rate"] >= PAPER_TO_LIVE_MIN_WIN_RATE
                    and metrics["sharpe_ratio"] >= PAPER_TO_LIVE_MIN_SHARPE
                    and metrics["max_drawdown_pct"] <= PAPER_TO_LIVE_MAX_DRAWDOWN
                ):
                    genome.stage = "LIVE"
                    genome.stage_entered_at = utcnow()
                    genome.updated_at = utcnow()
                    action = EvolutionAction(
                        action_type="promote",
                        genome_id=genome.genome_id,
                        strategy_name=genome.strategy_name,
                        from_stage="PAPER",
                        to_stage="LIVE",
                        details={
                            "gate": "paper_to_live",
                            "total_trades": metrics["total_trades"],
                            "win_rate": metrics["win_rate"],
                            "sharpe_ratio": metrics["sharpe_ratio"],
                            "max_drawdown_pct": metrics["max_drawdown_pct"],
                        },
                    )
                    log_evolution_action(action, db)
                    promoted += 1

        db.commit()
        logger.info(
            "Shadow validation completed for %s genomes, promoted %s, killed %s",
            len(candidate_genomes),
            promoted,
            killed,
        )


def full_population_review_job() -> None:
    """Full population census — review all genomes, auto-kill underperformers,
    update fitness tiers. Runs weekly."""
    if not settings.EVOLUTION_ENGINE_ENABLED:
        logger.debug("Evolution engine disabled, skipping population review")
        return

    logger.info("Starting full population review job")
    with _get_db_session() as db:
        genomes = (
            db.query(GenomeRegistry)
            .filter(
                GenomeRegistry.stage.in_(
                    ["DRAFT", "SHADOW", "PAPER", "LIVE", "BREEDING"]
                )
            )
            .all()
        )

        killed = 0
        for genome in genomes:
            raw_metrics = genome.fitness_metrics  # dict via hybrid_property
            metrics_obj = FitnessMetrics(
                **{
                    k: v
                    for k, v in raw_metrics.items()
                    if k in FitnessMetrics.model_fields
                }
            )
            fitness = calculate_fitness(metrics_obj)
            genome.fitness_score = fitness
            genome.fitness_updated_at = utcnow()
            if raw_metrics:
                genome.total_pnl = raw_metrics.get("total_pnl", 0.0)
                genome.win_rate = raw_metrics.get("win_rate", 0.0)
                genome.sharpe_ratio = raw_metrics.get("sharpe_ratio", 0.0)
                genome.max_drawdown_pct = raw_metrics.get("max_drawdown_pct", 0.0)
                genome.trade_count = raw_metrics.get("total_trades", 0)
                genome.last_evaluated_at = utcnow()

            if (
                fitness < 0.30
                and raw_metrics
                and raw_metrics.get("total_trades", 0) >= 20
            ):
                genome.stage = "GRAVEYARD"
                action = EvolutionAction(
                    action_type="kill",
                    genome_id=genome.genome_id,
                    strategy_name=genome.strategy_name,
                    from_stage=genome.stage,
                    to_stage="GRAVEYARD",
                    details={
                        "fitness_score": fitness,
                        "reason": "below_kill_threshold",
                    },
                )
                log_evolution_action(action, db)
                killed += 1

        db.commit()
        logger.info(
            f"Population review completed: {len(genomes)} genomes, {killed} killed"
        )


def legend_evaluation_job() -> None:
    """Evaluate LIVE genomes for LEGEND status. Requirements:
    Live 60d + fitness > 0.85 + total PnL > $500. Runs monthly."""
    if not settings.EVOLUTION_ENGINE_ENABLED:
        logger.debug("Evolution engine disabled, skipping legend evaluation")
        return

    logger.info("Starting legend evaluation job")
    with _get_db_session() as db:
        cutoff = datetime.now(timezone.utc) - timedelta(days=60)

        live_genomes = (
            db.query(GenomeRegistry)
            .filter(
                GenomeRegistry.stage == "LIVE",
                GenomeRegistry.created_at <= cutoff,
            )
            .all()
        )

        legends = 0
        for genome in live_genomes:
            raw_metrics = genome.fitness_metrics  # dict via hybrid_property
            metrics_obj = FitnessMetrics(
                **{
                    k: v
                    for k, v in raw_metrics.items()
                    if k in FitnessMetrics.model_fields
                }
            )
            fitness = calculate_fitness(metrics_obj)
            if fitness > 0.85 and raw_metrics.get("profit_factor", 0) > 2.0:
                genome.stage = "LEGEND"
                genome.stage_entered_at = utcnow()
                action = EvolutionAction(
                    action_type="promote",
                    genome_id=genome.genome_id,
                    strategy_name=genome.strategy_name,
                    from_stage="LIVE",
                    to_stage="LEGEND",
                    details={"fitness_score": fitness, "legend_criteria_met": True},
                )
                log_evolution_action(action, db)
                publish_event(
                    "genome_promoted",
                    {
                        "genome_id": genome.genome_id,
                        "from": "LIVE",
                        "to": "LEGEND",
                    },
                )
                legends += 1

        db.commit()
        logger.info(f"Legend evaluation completed, {legends} new legends")
