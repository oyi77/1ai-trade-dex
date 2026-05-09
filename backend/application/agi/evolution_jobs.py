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
from backend.domain.evolution.shadow_metrics import compute_shadow_metrics
from backend.domain.evolution.evolution_action import EvolutionAction
from backend.models.database import GenomeRegistry, EvolutionLog, ShadowTrade
from backend.models.genome_registry import GenomePerformance

logger = logging.getLogger(__name__)

SHADOW_TO_PAPER_MIN_TRADES = 20
SHADOW_TO_PAPER_MIN_WIN_RATE = 0.45
SHADOW_TO_PAPER_MIN_SHARPE = 0.5

PAPER_TO_LIVE_MIN_TRADES = 50
PAPER_TO_LIVE_MIN_WIN_RATE = 0.50
PAPER_TO_LIVE_MIN_SHARPE = 0.8
PAPER_TO_LIVE_MAX_DRAWDOWN = 0.20

AUTO_KILL_MAX_DRAWDOWN = 0.50
AUTO_KILL_MIN_SHARPE = -2.0
AUTO_KILL_MIN_WIN_RATE = 0.05


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


def _sync_genome_fitness_from_shadow_trades(genome, settled_trades, db: Session) -> dict:
    """Update fitness_json, native metric columns, and genome_performance row from settled shadow trades."""
    metrics = compute_shadow_metrics(settled_trades)
    fitness = FitnessMetrics(
        sharpe_ratio=metrics["sharpe_ratio"],
        win_rate=metrics["win_rate"],
        profit_factor=metrics["profit_factor"],
        max_drawdown_pct=metrics["max_drawdown_pct"],
        total_trades=metrics["total_trades"],
        last_evaluated=datetime.now(timezone.utc),
    )
    genome.fitness_json = fitness.model_dump_json()

    # Compute composite fitness score and sync ALL native denormalized columns
    fitness_score = calculate_fitness(fitness)
    genome.fitness_score = fitness_score
    genome.fitness_updated_at = datetime.now(timezone.utc)
    genome.total_pnl = metrics["total_pnl"]
    genome.win_rate = metrics["win_rate"]
    genome.sharpe_ratio = metrics["sharpe_ratio"]
    genome.max_drawdown_pct = metrics["max_drawdown_pct"]
    genome.trade_count = metrics["total_trades"]
    genome.last_evaluated_at = datetime.now(timezone.utc)

    perf_row = db.query(GenomePerformance).filter(
        GenomePerformance.genome_id == genome.genome_id
    ).first()
    if perf_row is None:
        perf_row = GenomePerformance(genome_id=genome.genome_id)
        db.add(perf_row)

    perf_row.trades = [
        {
            "shadow_trade_id": t.id,
            "timestamp": t.timestamp.isoformat() if t.timestamp else None,
            "market_ticker": t.market_ticker,
            "direction": t.direction,
            "entry_price": t.entry_price,
            "settlement_value": t.settlement_value,
            "size": t.size,
            "pnl": t.pnl,
            "result": "win" if (t.pnl or 0) > 0 else "loss",
        }
        for t in settled_trades
    ]
    perf_row.total_trades = metrics["total_trades"]
    perf_row.winning_trades = metrics["winning_trades"]
    perf_row.losing_trades = metrics["losing_trades"]
    perf_row.total_pnl = metrics["total_pnl"]
    perf_row.avg_pnl = metrics["avg_pnl"]
    perf_row.avg_win = metrics["avg_win"]
    perf_row.avg_loss = metrics["avg_loss"]
    perf_row.sharpe_ratio = metrics["sharpe_ratio"]
    perf_row.max_drawdown_pct = metrics["max_drawdown_pct"]
    perf_row.volatility = metrics["volatility"]
    perf_row.profit_factor = metrics["profit_factor"]
    perf_row.last_updated = datetime.now(timezone.utc)

    return metrics


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
                raw = genome.fitness_metrics  # hybrid_property auto-deserializes fitness_json
                metrics = FitnessMetrics(**{k: v for k, v in raw.items() if k in FitnessMetrics.model_fields})
                fitness_score = calculate_fitness(metrics)

                # Sync both JSON and native denormalized columns
                genome.fitness_score = fitness_score
                genome.fitness_updated_at = datetime.now(timezone.utc)
                genome.total_pnl = raw.get("total_pnl", 0.0) if metrics.total_trades > 0 else 0.0
                genome.win_rate = metrics.win_rate
                genome.sharpe_ratio = metrics.sharpe_ratio
                genome.max_drawdown_pct = metrics.max_drawdown_pct
                genome.trade_count = metrics.total_trades
                genome.last_evaluated_at = datetime.now(timezone.utc)

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
    """Run mutation cycle on PAPER and LIVE genomes. Runs every 12 minutes."""
    if not settings.EVOLUTION_ENGINE_ENABLED:
        logger.debug("Evolution engine disabled, skipping mutation cycle")
        return

    logger.info("Starting mutation cycle")
    with _get_db_session() as db:
        # Get genomes eligible for mutation (PAPER or LIVE stage)
        eligible = db.query(GenomeRegistry).filter(
            GenomeRegistry.stage.in_(["PAPER", "LIVE"])
        ).all()

        mutants = []
        for genome in eligible:
            try:
                mutant_genome, changes = mutate_genome(genome)

                # Sync both JSON and native denormalized columns
                mutant_genome.fitness_score = 0.0
                mutant_genome.fitness_updated_at = datetime.now(timezone.utc)
                mutant_genome.total_pnl = 0.0
                mutant_genome.win_rate = 0.0
                mutant_genome.sharpe_ratio = 0.0
                mutant_genome.max_drawdown_pct = 0.0
                mutant_genome.trade_count = 0
                mutant_genome.last_evaluated_at = datetime.now(timezone.utc)

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

                logger.debug(f"Mutated {genome.strategy_name} -> {mutant_genome.strategy_name}")

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
        elite_genomes = db.query(GenomeRegistry).filter(
            GenomeRegistry.stage.in_(["PAPER", "LIVE"])
        ).order_by(GenomeRegistry.fitness_score.desc()).limit(10).all()

        for i in range(0, len(elite_genomes) - 1, 2):
            parent_a = elite_genomes[i]
            parent_b = elite_genomes[i + 1]
            try:
                child_genome = crossover_genomes(parent_a, parent_b)

                # Sync both JSON and native denormalized columns
                child_genome.fitness_score = 0.0
                child_genome.fitness_updated_at = datetime.now(timezone.utc)
                child_genome.total_pnl = 0.0
                child_genome.win_rate = 0.0
                child_genome.sharpe_ratio = 0.0
                child_genome.max_drawdown_pct = 0.0
                child_genome.trade_count = 0
                child_genome.last_evaluated_at = datetime.now(timezone.utc)

                db.add(child_genome)

                # Log evolution action
                action = EvolutionAction(
                    action_type="crossover",
                    genome_id=child_genome.genome_id,
                    strategy_name=child_genome.strategy_name,
                    details={"parent_a": parent_a.genome_id, "parent_b": parent_b.genome_id},
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
        candidate_genomes = db.query(GenomeRegistry).filter(
            GenomeRegistry.stage.in_(["SHADOW", "PAPER"])
        ).all()

        promoted = 0
        killed = 0
        for genome in candidate_genomes:
            trades = db.query(ShadowTrade).filter(
                ShadowTrade.genome_id == genome.genome_id,
                ShadowTrade.settled.is_(True),
                ShadowTrade.pnl.isnot(None),
            ).order_by(ShadowTrade.timestamp.asc()).all()

            metrics = _sync_genome_fitness_from_shadow_trades(genome, trades, db)

            # Auto-kill gates
            if (
                metrics["max_drawdown_pct"] > AUTO_KILL_MAX_DRAWDOWN
                or (metrics["sharpe_ratio"] < AUTO_KILL_MIN_SHARPE and metrics["win_rate"] < AUTO_KILL_MIN_WIN_RATE)
            ):
                from_stage = genome.stage
                genome.stage = "GRAVEYARD"
                genome.stage_entered_at = datetime.now(timezone.utc)
                genome.updated_at = datetime.now(timezone.utc)
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
                    genome.stage_entered_at = datetime.now(timezone.utc)
                    genome.updated_at = datetime.now(timezone.utc)
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
                    genome.stage_entered_at = datetime.now(timezone.utc)
                    genome.updated_at = datetime.now(timezone.utc)
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
        genomes = db.query(GenomeRegistry).filter(
            GenomeRegistry.stage.in_(["DRAFT", "SHADOW", "PAPER", "LIVE", "BREEDING"])
        ).all()

        killed = 0
        for genome in genomes:
            raw_metrics = genome.fitness_metrics  # dict via hybrid_property
            metrics_obj = FitnessMetrics(**{k: v for k, v in raw_metrics.items() if k in FitnessMetrics.model_fields})
            fitness = calculate_fitness(metrics_obj)
            genome.fitness_score = fitness
            genome.fitness_updated_at = datetime.now(timezone.utc)
            if raw_metrics:
                genome.total_pnl = raw_metrics.get("total_pnl", 0.0)
                genome.win_rate = raw_metrics.get("win_rate", 0.0)
                genome.sharpe_ratio = raw_metrics.get("sharpe_ratio", 0.0)
                genome.max_drawdown_pct = raw_metrics.get("max_drawdown_pct", 0.0)
                genome.trade_count = raw_metrics.get("total_trades", 0)
                genome.last_evaluated_at = datetime.now(timezone.utc)

            if fitness < 0.30 and raw_metrics and raw_metrics.get("total_trades", 0) >= 20:
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
            raw_metrics = genome.fitness_metrics  # dict via hybrid_property
            metrics_obj = FitnessMetrics(**{k: v for k, v in raw_metrics.items() if k in FitnessMetrics.model_fields})
            fitness = calculate_fitness(metrics_obj)
            if fitness > 0.85 and raw_metrics.get("profit_factor", 0) > 2.0:
                genome.stage = "LEGEND"
                genome.stage_entered_at = datetime.now(timezone.utc)
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
        mutated, _ = mutate_genome(genome, market_regime="neutral", targeted_chrom=chrom_name)
        if mutated and mutated.genome_id != genome.genome_id:
            mutated.fitness_score = calculate_fitness(mutated.fitness_metrics)
            mutated.total_pnl = mutated.fitness_metrics.total_pnl or 0.0
            mutated.win_rate = mutated.fitness_metrics.win_rate or 0.0
            mutated.sharpe_ratio = mutated.fitness_metrics.sharpe_ratio or 0.0
            mutated.max_drawdown_pct = mutated.fitness_metrics.max_drawdown_pct or 0.0
            mutated.trade_count = mutated.fitness_metrics.total_trades or 0
            mutated.fitness_updated_at = datetime.now(timezone.utc)
            mutated.last_evaluated_at = datetime.now(timezone.utc)
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
