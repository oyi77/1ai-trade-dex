"""Genome Repository - DB access layer for genome persistence."""

from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy import func, desc, and_

from backend.models.database import GenomeRegistry
from backend.models.genome_registry import GenomeShadowTrade
from backend.db.utils import utcnow


class GenomeRepository:
    """CRUD operations for StrategyGenome persistence."""

    def __init__(self, db: Optional[Session] = None):
        self.db = db
        self._owns_db = False

    def _get_db(self) -> Session:
        if self.db is None:
            from backend.models.database import SessionLocal

            self.db = SessionLocal()
            self._owns_db = True
        return self.db

    def close(self):
        if self._owns_db and self.db:
            self.db.close()
            self._owns_db = False
            self.db = None

    def save_from_genome(self, genome, stage: str = "DRAFT") -> GenomeRegistry:
        """Save a StrategyGenome (domain model) to the registry."""
        db = self._get_db()
        try:
            existing = (
                db.query(GenomeRegistry)
                .filter(GenomeRegistry.genome_id == genome.genome_id)
                .first()
            )

            if existing:
                existing.chromosomes = (
                    genome.chromosomes.model_dump()
                    if hasattr(genome.chromosomes, "model_dump")
                    else genome.chromosomes
                )
                existing.lineage = (
                    genome.lineage.model_dump()
                    if hasattr(genome.lineage, "model_dump")
                    else genome.lineage
                )
                existing.fitness_metrics = (
                    genome.fitness_metrics.model_dump()
                    if hasattr(genome.fitness_metrics, "model_dump")
                    else genome.fitness_metrics
                )
                existing.stage = stage
                existing.updated_at = utcnow()
                existing.archetype = genome.archetype
                existing.strategy_name = genome.strategy_name
            else:
                registry = GenomeRegistry(
                    genome_id=genome.genome_id,
                    strategy_name=genome.strategy_name,
                    archetype=genome.archetype,
                    stage=stage,
                    chromosomes=(
                        genome.chromosomes.model_dump()
                        if hasattr(genome.chromosomes, "model_dump")
                        else genome.chromosomes
                    ),
                    lineage=(
                        genome.lineage.model_dump()
                        if hasattr(genome.lineage, "model_dump")
                        else genome.lineage
                    ),
                    fitness_metrics=(
                        genome.fitness_metrics.model_dump()
                        if hasattr(genome.fitness_metrics, "model_dump")
                        else genome.fitness_metrics
                    ),
                )
                db.add(registry)
                existing = registry

            db.commit()
            db.refresh(existing)
            return existing
        finally:
            self.close()

    def get_by_id(self, genome_id: str) -> Optional[GenomeRegistry]:
        """Get a genome by its ID."""
        db = self._get_db()
        try:
            return (
                db.query(GenomeRegistry)
                .filter(GenomeRegistry.genome_id == genome_id)
                .first()
            )
        finally:
            self.close()

    def get_by_stage(self, stage: str, limit: int = 100) -> List[GenomeRegistry]:
        """Get all genomes at a specific stage, sorted by fitness_score."""
        db = self._get_db()
        try:
            return (
                db.query(GenomeRegistry)
                .filter(GenomeRegistry.stage == stage)
                .order_by(desc(GenomeRegistry.fitness_score))
                .limit(limit)
                .all()
            )
        finally:
            self.close()

    def get_elite(self, limit: int = 5) -> List[GenomeRegistry]:
        """Get top-performing genomes (LIVE or BREEDING stage with good metrics).

        Uses native columns for efficient index-based filtering.
        """
        db = self._get_db()
        try:
            return (
                db.query(GenomeRegistry)
                .filter(
                    and_(
                        GenomeRegistry.stage.in_(["LIVE", "BREEDING", "PAPER"]),
                        GenomeRegistry.win_rate >= 0.50,
                        GenomeRegistry.sharpe_ratio >= 0.5,
                    )
                )
                .order_by(desc(GenomeRegistry.sharpe_ratio))
                .limit(limit)
                .all()
            )
        finally:
            self.close()

    def get_draft_genomes(self, limit: int = 20) -> List[GenomeRegistry]:
        """Get genomes in DRAFT stage for evolution, sorted by fitness_score."""
        db = self._get_db()
        try:
            return (
                db.query(GenomeRegistry)
                .filter(GenomeRegistry.stage == "DRAFT")
                .order_by(desc(GenomeRegistry.fitness_score))
                .limit(limit)
                .all()
            )
        finally:
            self.close()

    def update_stage(self, genome_id: str, new_stage: str) -> bool:
        """Move genome to a new stage."""
        db = self._get_db()
        try:
            genome = (
                db.query(GenomeRegistry)
                .filter(GenomeRegistry.genome_id == genome_id)
                .first()
            )
            if genome:
                genome.stage = new_stage
                genome.updated_at = utcnow()
                db.commit()
                return True
            return False
        finally:
            self.close()

    def update_fitness(self, genome_id: str, metrics: Dict[str, Any]) -> bool:
        """Update fitness metrics for a genome.

        Syncs both fitness_json (structured) and native denormalized columns
        (indexed for fast queries).
        """
        db = self._get_db()
        try:
            genome = (
                db.query(GenomeRegistry)
                .filter(GenomeRegistry.genome_id == genome_id)
                .first()
            )
            if genome:
                genome.fitness_metrics = metrics
                genome.trade_count = metrics.get("total_trades", 0)
                genome.total_pnl = metrics.get("total_pnl", 0.0)
                genome.win_rate = metrics.get("win_rate", 0.0)
                genome.sharpe_ratio = metrics.get("sharpe_ratio", 0.0)
                genome.max_drawdown_pct = metrics.get("max_drawdown_pct", 0.0)
                genome.last_evaluated_at = utcnow()
                genome.updated_at = utcnow()
                db.commit()
                return True
            return False
        finally:
            self.close()

    def record_shadow_trade(self, trade_data: Dict[str, Any]) -> GenomeShadowTrade:
        """Record a shadow trade for a genome."""
        db = self._get_db()
        try:
            trade = GenomeShadowTrade(**trade_data)
            db.add(trade)
            db.commit()
            db.refresh(trade)
            return trade
        finally:
            self.close()

    def get_shadow_trades(
        self, genome_id: str, settled_only: bool = False
    ) -> List[GenomeShadowTrade]:
        """Get shadow trades for a genome."""
        db = self._get_db()
        try:
            query = db.query(GenomeShadowTrade).filter(
                GenomeShadowTrade.genome_id == genome_id
            )
            if settled_only:
                query = query.filter(GenomeShadowTrade.settled)
            return query.order_by(desc(GenomeShadowTrade.timestamp)).all()
        finally:
            self.close()

    def settle_shadow_trade(
        self, trade_id: int, settlement_price: float, actual_outcome: float
    ) -> Optional[GenomeShadowTrade]:
        """Settle a shadow trade and calculate P&L."""
        db = self._get_db()
        try:
            trade = (
                db.query(GenomeShadowTrade)
                .filter(GenomeShadowTrade.id == trade_id)
                .first()
            )
            if trade:
                trade.settled = True
                trade.settlement_price = settlement_price
                trade.actual_outcome = actual_outcome

                from backend.core.settlement.settlement_helpers import calculate_pnl

                settlement_value = settlement_price
                pnl = calculate_pnl(trade, settlement_value)

                trade.exit_price = (
                    settlement_price
                    if trade.direction == "up"
                    else 1 - settlement_price
                )
                trade.pnl = pnl
                if pnl >= 0:
                    trade.result = "win"
                else:
                    trade.result = "loss"

                trade.accuracy_score = (
                    abs(trade.predicted_outcome - actual_outcome)
                    if trade.predicted_outcome
                    else None
                )
                trade.settled_at = datetime.now(timezone.utc)
                db.commit()
                db.refresh(trade)
            return trade
        finally:
            self.close()

    def calculate_fitness(self, genome_id: str) -> Dict[str, float]:
        """Calculate fitness metrics from shadow trades."""
        db = self._get_db()
        try:
            trades = (
                db.query(GenomeShadowTrade)
                .filter(
                    and_(
                        GenomeShadowTrade.genome_id == genome_id,
                        GenomeShadowTrade.settled,
                    )
                )
                .all()
            )

            if not trades:
                return {
                    "sharpe_ratio": 0.0,
                    "win_rate": 0.0,
                    "profit_factor": 0.0,
                    "max_drawdown_pct": 0.0,
                    "total_trades": 0,
                }

            wins = [t for t in trades if (t.pnl or 0) > 0]
            losses = [t for t in trades if (t.pnl or 0) < 0]

            win_rate = len(wins) / len(trades) if trades else 0.0
            total_pnl = sum(t.pnl or 0 for t in trades)
            gross_profit = sum(t.pnl for t in wins if t.pnl and t.pnl > 0)
            gross_loss = abs(sum(t.pnl for t in losses if t.pnl and t.pnl < 0))
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

            pnl_values = [t.pnl or 0 for t in trades]
            cumulative = 0
            peak = 0
            max_drawdown = 0
            for pnl in pnl_values:
                cumulative += pnl
                if cumulative > peak:
                    peak = cumulative
                drawdown = peak - cumulative
                if drawdown > max_drawdown:
                    max_drawdown = drawdown

            avg_pnl = total_pnl / len(trades) if trades else 0
            std_dev = (
                (sum((p - avg_pnl) ** 2 for p in pnl_values) / len(pnl_values)) ** 0.5
                if len(pnl_values) > 1
                else 0
            )
            sharpe_ratio = (avg_pnl / std_dev * (252**0.5)) if std_dev > 0 else 0.0

            return {
                "sharpe_ratio": sharpe_ratio,
                "win_rate": win_rate,
                "profit_factor": profit_factor,
                "max_drawdown_pct": max_drawdown,
                "total_trades": len(trades),
                "total_pnl": total_pnl,
            }
        finally:
            self.close()

    def count_by_stage(self) -> Dict[str, int]:
        """Count genomes by stage."""
        db = self._get_db()
        try:
            result = (
                db.query(GenomeRegistry.stage, func.count(GenomeRegistry.id))
                .group_by(GenomeRegistry.stage)
                .all()
            )
            return {stage: count for stage, count in result}
        finally:
            self.close()
