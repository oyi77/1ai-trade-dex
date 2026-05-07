"""Lifecycle Manager for Strategy Genome Stage Transitions.

Wave 11: Lifecycle Stage Machine — Part 4
Manages the full lifecycle of strategy genomes through stages:
DRAFT → SHADOW → PAPER → LIVE → BREEDING → LEGEND → GRAVEYARD
"""

from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.orm import Session
from backend.domain.genome.models import StrategyGenome, DeathCertificate
from backend.domain.evolution.evolution_action import EvolutionAction
from backend.domain.evolution.fitness import calculate_fitness
from backend.core.event_bus import publish_event


# Auto-kill conditions from spec lines 227-232
AUTO_KILL_CONDITIONS = [
    lambda m: m.max_drawdown_pct > 0.50,                              # 50% drawdown
    lambda m: m.sharpe_ratio < -2.0 and m.win_rate < 0.05,           # Sharpe + win rate both terminal
    lambda m: m.brier_score > 0.35,                                   # Worse than random guessing
]


class LifecycleManager:
    """Manages strategy genome lifecycle stage transitions."""

    def evaluate_stage_transition(self, genome: StrategyGenome, regime: str, db: Session) -> Optional[str]:
        """Evaluate if a genome should transition to a new stage.

        Args:
            genome: The strategy genome to evaluate
            regime: Current market regime (volatile, trending, sideways, event_dense)
            db: Database session

        Returns:
            Target stage name if transition warranted, else None
        """
        current = genome.stage

        if current == "DRAFT":
            return self._evaluate_draft_to_shadow(genome)
        elif current == "SHADOW":
            return self._evaluate_shadow_to_paper(genome, db)
        elif current == "PAPER":
            return self._evaluate_paper_to_live(genome, regime)
        elif current == "LIVE":
            return self._evaluate_live_transition(genome, db)
        elif current == "BREEDING":
            return self._evaluate_breeding_transition(genome, db)
        elif current == "LEGEND":
            return None  # LEGEND is permanent
        elif current == "GRAVEYARD":
            return self._evaluate_graveyard_rehabilitation(genome, db)

        return None

    def _evaluate_draft_to_shadow(self, genome: StrategyGenome) -> Optional[str]:
        """Evaluate DRAFT → SHADOW transition.

        Criteria: Sharpe > 0.3 AND Max DD < 25% → SHADOW. Else → GRAVEYARD
        """
        m = genome.fitness_metrics

        # Check if meets SHADOW criteria
        if m.sharpe_ratio > 0.3 and m.max_drawdown_pct < 0.25:
            return "SHADOW"
        else:
            # Check auto-kill conditions
            if self._check_auto_kill(genome):
                return "GRAVEYARD"

        return None

    def _evaluate_shadow_to_paper(self, genome: StrategyGenome, db: Session) -> Optional[str]:
        """Evaluate SHADOW → PAPER transition.

        Criteria: 24h+ AND signal accuracy > 60% → PAPER
        """
        m = genome.fitness_metrics

        # Check if genome has been in SHADOW for at least 24 hours
        try:
            stage_entered = self._get_stage_entered_at(genome.genome_id, db, "SHADOW")
            if stage_entered is None:
                return None
            time_in_stage = datetime.now(timezone.utc) - stage_entered
            if time_in_stage < timedelta(hours=24):
                return None
        except (TypeError, AttributeError):
            # If _get_stage_entered_at is mocked or unavailable, skip time check
            return None

        # Check signal accuracy (from shadow trades)
        if m.win_rate > 0.60:  # win_rate serves as signal accuracy proxy
            return "PAPER"

        # Check auto-kill conditions
        if self._check_auto_kill(genome):
            return "GRAVEYARD"

        return None

    def _evaluate_paper_to_live(self, genome: StrategyGenome, regime: str) -> Optional[str]:
        if should_promote_paper_to_live(genome, regime):
            return "LIVE"
        return None

    def _evaluate_live_transition(self, genome: StrategyGenome, db: Session) -> Optional[str]:
        m = genome.fitness_metrics
        fitness = calculate_fitness(m)

        if fitness > 0.75:
            stage_entered = self._get_stage_entered_at(genome.genome_id, db, "LIVE")
            if stage_entered is not None:
                try:
                    time_in_stage = datetime.now(timezone.utc) - stage_entered
                    if time_in_stage >= timedelta(days=14):
                        return "BREEDING"
                except (TypeError, AttributeError):
                    pass

        if self._check_auto_kill(genome):
            return "GRAVEYARD"

        return None

    def _evaluate_breeding_transition(self, genome: StrategyGenome, db: Session) -> Optional[str]:
        m = genome.fitness_metrics
        fitness = calculate_fitness(m)

        # Check if eligible for LEGEND status first (before downgrade check)
        # LEGEND criteria: Live 60d + fitness > 0.85 + total PnL > $500
        stage_entered = self._get_stage_entered_at(genome.genome_id, db, "LIVE")
        if stage_entered is not None:
            time_since_live = datetime.now(timezone.utc) - stage_entered
            if time_since_live >= timedelta(days=60) and fitness > 0.85:
                total_pnl = self._get_total_pnl_for_genome(genome.genome_id, db)
                if total_pnl > 500:
                    return "LEGEND"

        # Check if fitness dropped below BREEDING threshold
        if fitness < 0.75:
            return "LIVE"

        # Check auto-kill conditions
        if self._check_auto_kill(genome):
            return "GRAVEYARD"

        return None

    def _evaluate_graveyard_rehabilitation(self, genome: StrategyGenome, db: Session) -> Optional[str]:
        """Evaluate GRAVEYARD → DRAFT rehabilitation.

        Criteria: 50%+ win rate on last 10 trades AND positive PnL
        """
        if check_rehabilitation_eligibility(genome, db):
            return "DRAFT"

        return None

    def _get_stage_entered_at(self, genome_id: str, db, stage: Optional[str] = None) -> Optional[datetime]:
        try:
            from backend.models.database import GenomeRegistry
            query = db.query(GenomeRegistry).filter(GenomeRegistry.genome_id == genome_id)
            if stage:
                query = query.filter(GenomeRegistry.stage == stage)
            result = query.first()
            if result and isinstance(result.stage_entered_at, datetime):
                return result.stage_entered_at
        except (TypeError, AttributeError, Exception):
            pass
        return None

    def _get_total_pnl_for_genome(self, genome_id: str, db) -> float:
        try:
            from backend.models.database import Trade
            total_pnl = db.query(
                db.func.coalesce(db.func.sum(Trade.pnl), 0)
            ).filter(
                Trade.strategy == genome_id
            ).scalar()
            return float(total_pnl or 0.0)
        except (TypeError, AttributeError, Exception):
            return 0.0

    def _check_auto_kill(self, genome: StrategyGenome) -> bool:
        """Check if genome meets any auto-kill conditions."""
        return self.check_auto_kill(genome) is not None

    def execute_transition(self, genome: StrategyGenome, target_stage: str, db: Session) -> EvolutionAction:
        """Execute a stage transition — update DB, publish event, log evolution.

        Args:
            genome: The strategy genome to transition
            target_stage: The target stage to transition to
            db: Database session

        Returns:
            EvolutionAction representing the transition
        """
        from backend.models.database import GenomeRegistry, EvolutionLog

        current_stage = genome.stage

        # Update genome stage
        genome.stage = target_stage
        genome.updated_at = datetime.now(timezone.utc)

        # Update database
        db_genome = db.query(GenomeRegistry).filter(
            GenomeRegistry.genome_id == genome.genome_id
        ).first()

        if db_genome:
            db_genome.stage = target_stage
            db_genome.stage_entered_at = datetime.now(timezone.utc)
            db_genome.updated_at = datetime.now(timezone.utc)

            # Update fitness metrics
            if genome.fitness_metrics:
                db_genome.fitness_json = genome.fitness_metrics.model_dump_json()

            db.commit()

        # Create evolution action
        action_type = "promotion" if target_stage in ["SHADOW", "PAPER", "LIVE", "BREEDING", "LEGEND"] else "auto_kill"
        if target_stage == "GRAVEYARD":
            action_type = "auto_kill"
        elif target_stage == "DRAFT" and current_stage == "GRAVEYARD":
            action_type = "necromancy"

        action = EvolutionAction(
            action_type=action_type,
            genome_id=genome.genome_id,
            strategy_name=genome.strategy_name,
            details={
                "from_stage": current_stage,
                "to_stage": target_stage,
                "fitness_score": calculate_fitness(genome.fitness_metrics),
                "metrics": genome.fitness_metrics.model_dump()
            },
            timestamp=datetime.now(timezone.utc),
            from_stage=current_stage,
            to_stage=target_stage
        )

        # Log to evolution_log table
        evolution_log = EvolutionLog(
            genome_id=genome.genome_id,
            event_type=action_type,
            from_stage=current_stage,
            to_stage=target_stage,
            data=action.details
        )
        db.add(evolution_log)
        db.commit()

        # Publish event
        publish_event("lifecycle_transition", {
            "genome_id": genome.genome_id,
            "strategy_name": genome.strategy_name,
            "from_stage": current_stage,
            "to_stage": target_stage,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

        return action

    def check_auto_kill(self, genome: StrategyGenome) -> Optional[DeathCertificate]:
        """Check if any auto-kill condition is met. Returns DeathCertificate if killed."""
        m = genome.fitness_metrics

        for condition in AUTO_KILL_CONDITIONS:
            if condition(m):
                return DeathCertificate(
                    genome_id=genome.genome_id,
                    strategy_name=genome.strategy_name,
                    reason="auto_kill",
                    final_metrics=m.model_dump(),
                    kill_timestamp=datetime.now(timezone.utc),
                    total_pnl=0.0,  # Would be populated from DB in real usage
                    total_trades=m.total_trades,
                    regime_at_death="unknown",  # Would be populated from RegimeDetector
                    killer_condition=str(condition),
                    rehabilitation_eligible=True
                )

        return None


def should_promote_paper_to_live(genome: StrategyGenome, regime: str) -> bool:
    """Determine if a PAPER stage genome should be promoted to LIVE using regime-aware thresholds.

    Args:
        genome: The strategy genome to evaluate
        regime: Current market regime (volatile, trending, sideways, event_dense)

    Returns:
        True if promotion criteria met, False otherwise
    """
    m = genome.fitness_metrics

    # Statistical minimum — non-negotiable regardless of regime
    if m.total_trades < 50 or m.max_drawdown_pct > 0.20:
        return False

    # Regime-dynamic thresholds
    thresholds = {
        "volatile":    {"min_sharpe": 0.60, "min_win_rate": 0.50},
        "trending":    {"min_sharpe": 0.40, "min_win_rate": 0.55},
        "sideways":    {"min_sharpe": 0.50, "min_win_rate": 0.48},
        "event_dense": {"min_sharpe": 0.45, "min_win_rate": 0.52},
    }

    t = thresholds.get(regime, {"min_sharpe": 0.50, "min_win_rate": 0.50})

    return m.sharpe_ratio >= t["min_sharpe"] and m.win_rate >= t["min_win_rate"]


def check_rehabilitation_eligibility(genome: StrategyGenome, db: Session) -> bool:
    """Check if a GRAVEYARD genome is eligible for rehabilitation to DRAFT.

    Criteria: 50%+ win rate on last 10 trades AND positive PnL

    Args:
        genome: The strategy genome to evaluate
        db: Database session

    Returns:
        True if rehabilitation criteria met, False otherwise
    """
    if genome.stage != "GRAVEYARD":
        return False

    # Get recent trades for this genome
    from backend.models.database import Trade

    recent_trades = db.query(Trade).filter(
        Trade.strategy == genome.genome_id
    ).order_by(
        Trade.timestamp.desc()
    ).limit(10).all()

    if len(recent_trades) < 5:
        return False

    win_count = sum(1 for t in recent_trades if getattr(t, 'pnl', 0) > 0)
    win_rate = win_count / len(recent_trades)
    total_pnl = sum(getattr(t, 'pnl', 0) for t in recent_trades)

    return win_rate >= 0.50 and total_pnl > 0
