"""Genome converter/helper functions extracted from evolution_jobs.py.

Module-level constants and helper functions for genome-to-individual conversion,
individual-to-genome conversion, JSON serialization, fitness evaluation, and
genome persistence.
"""

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.config import settings
from backend.core.evolution_harness import Individual
from backend.db.utils import utcnow
from backend.domain.evolution.fitness import calculate_fitness
from backend.domain.evolution.shadow_metrics import compute_shadow_metrics
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
from backend.models.database import GenomeRegistry
from backend.models.genome_registry import GenomePerformance

from loguru import logger

# ── Promotion gates ──────────────────────────────────────────────────
SHADOW_TO_PAPER_MIN_TRADES = settings.EVOLUTION_SHADOW_PAPER_MIN_TRADES
SHADOW_TO_PAPER_MIN_WIN_RATE = settings.EVOLUTION_SHADOW_PAPER_MIN_WIN_RATE
SHADOW_TO_PAPER_MIN_SHARPE = settings.EVOLUTION_SHADOW_PAPER_MIN_SHARPE

PAPER_TO_LIVE_MIN_TRADES = settings.EVOLUTION_PAPER_LIVE_MIN_TRADES
PAPER_TO_LIVE_MIN_WIN_RATE = settings.EVOLUTION_PAPER_LIVE_MIN_WIN_RATE
PAPER_TO_LIVE_MIN_SHARPE = settings.EVOLUTION_PAPER_LIVE_MIN_SHARPE
PAPER_TO_LIVE_MAX_DRAWDOWN = settings.EVOLUTION_PAPER_LIVE_MAX_DRAWDOWN

# ── Auto-kill thresholds ─────────────────────────────────────────────
AUTO_KILL_MAX_DRAWDOWN = settings.EVOLUTION_AUTO_KILL_MAX_DRAWDOWN
AUTO_KILL_MIN_SHARPE = settings.EVOLUTION_AUTO_KILL_MIN_SHARPE
AUTO_KILL_MIN_WIN_RATE = settings.EVOLUTION_AUTO_KILL_MIN_WIN_RATE

# Gene bounds for DEAP: each gene clamped to [0.0, 1.0] (normalized space)
_DEFAULT_GENE_BOUNDS = [(0.0, 1.0)] * 30


# ── Genome ↔ Individual converters ───────────────────────────────────
def _genome_to_individual(genome: StrategyGenome) -> Individual:
    """Convert a StrategyGenome to an Individual for the evolution harness.

    Extracts numeric parameters from chromosomes into a flat gene vector.
    """
    genes: list[float] = []

    # Extract numeric values from each chromosome
    for chrom_name in ["perception", "cognition", "execution", "risk", "meta"]:
        chrom = genome.chromosomes.get(chrom_name)
        if chrom is None:
            continue
        chrom_dict = chrom.model_dump() if hasattr(chrom, "model_dump") else chrom
        for value in chrom_dict.values():
            if isinstance(value, float):
                genes.append(max(0.0, min(1.0, value)))
            elif isinstance(value, int) and not isinstance(value, bool):
                genes.append(max(0.0, min(1.0, float(value))))

    # Pad to fixed length for DEAP
    while len(genes) < 30:
        genes.append(0.0)
    genes = genes[:30]

    return Individual(
        genome_id=genome.genome_id,
        genes=genes,
        fitness=(),
        metadata={
            "strategy_name": genome.strategy_name,
            "archetype": genome.archetype,
            "stage": genome.stage,
        },
    )


def _individual_to_genome(
    ind: Individual,
    parent: StrategyGenome,
    strategy_name: str,
) -> StrategyGenome:
    """Convert an Individual back to a StrategyGenome by tweaking the parent.

    Uses the parent genome as a template and applies gene-level modifications
    to numeric fields.
    """
    new_genome = _to_strategy_genome_from_genome(parent)
    new_genome.genome_id = ind.genome_id
    new_genome.strategy_name = strategy_name
    new_genome.lineage.parent_genome_ids = [parent.genome_id]
    new_genome.lineage.generation = parent.lineage.generation + 1
    new_genome.lineage.creator = "mutation"
    new_genome.stage = "DRAFT"
    new_genome.fitness_metrics = FitnessMetrics()

    # Apply gene values back to numeric chromosome fields
    gene_idx = 0
    for chrom_name in ["perception", "cognition", "execution", "risk", "meta"]:
        chrom = new_genome.chromosomes.get(chrom_name)
        if chrom is None or gene_idx >= len(ind.genes):
            continue
        if hasattr(chrom, "__dict__"):
            for field_name, value in chrom.__dict__.items():
                if isinstance(value, float) and gene_idx < len(ind.genes):
                    setattr(chrom, field_name, ind.genes[gene_idx])
                    gene_idx += 1
                elif (
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and gene_idx < len(ind.genes)
                ):
                    setattr(chrom, field_name, int(ind.genes[gene_idx] * 100))
                    gene_idx += 1

    return new_genome


def _to_strategy_genome_from_genome(genome: StrategyGenome) -> StrategyGenome:
    """Create a deep copy of a StrategyGenome."""
    return StrategyGenome(
        genome_id=str(genome.genome_id),
        strategy_name=genome.strategy_name,
        archetype=genome.archetype,
        version=genome.version,
        stage=genome.stage,
        lineage=LineageData(
            parent_genome_ids=list(genome.lineage.parent_genome_ids),
            generation=genome.lineage.generation,
            creator=genome.lineage.creator,
        ),
        chromosomes={k: v for k, v in genome.chromosomes.items()},
        fitness_metrics=FitnessMetrics(**genome.fitness_metrics.model_dump()),
        created_at=genome.created_at,
        updated_at=genome.updated_at,
    )


# ── JSON helpers ─────────────────────────────────────────────────────
def _safe_load_json(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        logger.exception("Failed to parse JSON genome data")
        return {}


# ── Fitness helpers ──────────────────────────────────────────────────
def _fitness_metrics_for(genome_row: GenomeRegistry) -> FitnessMetrics:
    raw = _safe_load_json(genome_row.fitness_json)
    filtered = {k: v for k, v in raw.items() if k in FitnessMetrics.model_fields}
    return FitnessMetrics(**filtered)


def _fitness_score_for(genome_row: GenomeRegistry) -> float:
    return calculate_fitness(_fitness_metrics_for(genome_row))


# ── Chromosome helpers ───────────────────────────────────────────────
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
                        "conditions": [
                            {"indicator": "rsi", "operator": ">", "value": 70.0}
                        ],
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
        else LineageData(
            parent_genome_ids=[genome_row.genome_id], generation=1, creator="human"
        )
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
        serialized[name] = (
            chromosome.model_dump() if hasattr(chromosome, "model_dump") else chromosome
        )
    return json.dumps(serialized)


# ── Persistence ──────────────────────────────────────────────────────
def _upsert_genome(genome: StrategyGenome, db: Session) -> None:
    now = datetime.now(timezone.utc)
    existing = (
        db.query(GenomeRegistry)
        .filter(GenomeRegistry.genome_id == genome.genome_id)
        .first()
    )
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


# ── Shadow trade fitness sync ─────────────────────────────────────────
def _sync_genome_fitness_from_shadow_trades(
    genome, settled_trades, db: Session
) -> dict:
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
    genome.fitness_updated_at = utcnow()
    genome.total_pnl = metrics["total_pnl"]
    genome.win_rate = metrics["win_rate"]
    genome.sharpe_ratio = metrics["sharpe_ratio"]
    genome.max_drawdown_pct = metrics["max_drawdown_pct"]
    genome.trade_count = metrics["total_trades"]
    genome.last_evaluated_at = utcnow()

    perf_row = (
        db.query(GenomePerformance)
        .filter(GenomePerformance.genome_id == genome.genome_id)
        .first()
    )
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
