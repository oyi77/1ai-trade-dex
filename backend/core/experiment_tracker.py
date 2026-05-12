"""Experiment tracker — version parameter sets and track which configs produce best results."""

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from loguru import logger
class ExperimentTracker:
    """Track parameter experiments for strategies, compare results, promote winners."""

    def create_experiment(
        self,
        db: Session,
        strategy_name: str,
        params: dict,
        notes: Optional[str] = None,
    ) -> int:
        """Create a new candidate experiment. Returns experiment ID."""
        from backend.models.database import Experiment

        exp = Experiment(
            strategy_name=strategy_name,
            params_json=json.dumps(params) if isinstance(params, dict) else params,
            status="candidate",
            notes=notes,
            created_at=datetime.now(timezone.utc),
        )
        db.add(exp)
        db.commit()
        logger.info(f"Created experiment #{exp.id} for {strategy_name}")
        return exp.id

    def record_metrics(
        self,
        db: Session,
        experiment_id: int,
        metrics: dict,
    ) -> None:
        """Record performance metrics for an experiment."""
        from backend.models.database import Experiment

        exp = db.query(Experiment).filter(Experiment.id == experiment_id).first()
        if not exp:
            logger.warning(f"Experiment #{experiment_id} not found")
            return

        exp.metrics_json = json.dumps(metrics)
        db.commit()
        logger.info(
            f"Recorded metrics for experiment #{experiment_id}: "
            f"sharpe={metrics.get('sharpe', 'N/A')}, win_rate={metrics.get('win_rate', 'N/A')}"
        )

    def compare(
        self,
        db: Session,
        exp_a_id: int,
        exp_b_id: int,
    ) -> dict:
        """Compare two experiments. Returns winner and metrics diff."""
        from backend.models.database import Experiment

        exp_a = db.query(Experiment).filter(Experiment.id == exp_a_id).first()
        exp_b = db.query(Experiment).filter(Experiment.id == exp_b_id).first()

        if not exp_a or not exp_b:
            return {"error": "Experiment not found"}

        metrics_a = json.loads(exp_a.metrics_json) if exp_a.metrics_json else {}
        metrics_b = json.loads(exp_b.metrics_json) if exp_b.metrics_json else {}

        sharpe_a = metrics_a.get("sharpe", 0.0)
        sharpe_b = metrics_b.get("sharpe", 0.0)
        pnl_a = metrics_a.get("total_pnl", 0.0)
        pnl_b = metrics_b.get("total_pnl", 0.0)

        # Winner has higher Sharpe; tie-break on total PnL
        if sharpe_a > sharpe_b:
            winner = exp_a_id
        elif sharpe_b > sharpe_a:
            winner = exp_b_id
        else:
            winner = exp_a_id if pnl_a >= pnl_b else exp_b_id

        return {
            "winner": winner,
            "exp_a": {
                "id": exp_a_id,
                "sharpe": sharpe_a,
                "pnl": pnl_a,
                "metrics": metrics_a,
            },
            "exp_b": {
                "id": exp_b_id,
                "sharpe": sharpe_b,
                "pnl": pnl_b,
                "metrics": metrics_b,
            },
            "sharpe_diff": round(abs(sharpe_a - sharpe_b), 4),
        }

    def promote(self, db: Session, experiment_id: int) -> bool:
        """Promote an experiment's params to active StrategyConfig."""
        from backend.models.database import Experiment, StrategyConfig

        exp = db.query(Experiment).filter(Experiment.id == experiment_id).first()
        if not exp:
            logger.warning(f"Experiment #{experiment_id} not found")
            return False

        # Retire current active experiment for this strategy
        active = (
            db.query(Experiment)
            .filter(
                Experiment.strategy_name == exp.strategy_name,
                Experiment.status == "active",
            )
            .all()
        )
        for a in active:
            a.status = "retired"

        # Promote this experiment
        exp.status = "active"
        exp.promoted_at = datetime.now(timezone.utc)

        # Update StrategyConfig params
        config = (
            db.query(StrategyConfig)
            .filter(StrategyConfig.strategy_name == exp.strategy_name)
            .first()
        )
        if config:
            config.params = exp.params_json

        db.commit()
        logger.info(f"Promoted experiment #{experiment_id} for {exp.strategy_name}")
        return True

    def rollback(self, db: Session, strategy_name: str) -> bool:
        """Rollback to the previous active experiment for a strategy."""
        from backend.models.database import Experiment, StrategyConfig

        # Find the most recently retired experiment
        prev = (
            db.query(Experiment)
            .filter(
                Experiment.strategy_name == strategy_name,
                Experiment.status == "retired",
            )
            .order_by(Experiment.promoted_at.desc())
            .first()
        )

        if not prev:
            logger.warning(f"No previous experiment to rollback to for {strategy_name}")
            return False

        # Retire current active
        current = (
            db.query(Experiment)
            .filter(
                Experiment.strategy_name == strategy_name,
                Experiment.status == "active",
            )
            .all()
        )
        for c in current:
            c.status = "retired"

        # Re-activate previous
        prev.status = "active"
        prev.promoted_at = datetime.now(timezone.utc)

        # Update StrategyConfig
        config = (
            db.query(StrategyConfig)
            .filter(StrategyConfig.strategy_name == strategy_name)
            .first()
        )
        if config:
            config.params = prev.params_json

        db.commit()
        logger.info(f"Rolled back {strategy_name} to experiment #{prev.id}")
        return True

    def auto_promote(
        self,
        db: Session,
        min_trades: int = 30,
        min_sharpe_diff: float = 0.5,
        rollback_window_hours: int = 24,
        rollback_sharpe_floor: float = -0.5,
    ) -> list[int]:
        """Auto-promote candidates that significantly beat the active baseline.

        For each strategy with an active experiment, compare every candidate
        against the baseline.  Promote if:
          1. Candidate has >= ``min_trades`` recorded trades.
          2. Candidate Sharpe exceeds active Sharpe by >= ``min_sharpe_diff``.

        Additionally, check recently promoted experiments: if an experiment was
        promoted within ``rollback_window_hours`` and its Sharpe has dropped
        below ``rollback_sharpe_floor``, automatically roll it back.

        Returns the list of experiment IDs that were promoted.
        """
        from backend.models.database import Experiment

        promoted_ids: list[int] = []

        # --- Phase 1: rollback recently promoted experiments that went bad ---
        cutoff = datetime.now(timezone.utc) - timedelta(hours=rollback_window_hours)
        recent_active = (
            db.query(Experiment)
            .filter(
                Experiment.status == "active",
                Experiment.promoted_at.isnot(None),
                Experiment.promoted_at >= cutoff,
            )
            .all()
        )
        for exp in recent_active:
            metrics = json.loads(exp.metrics_json) if exp.metrics_json else {}
            sharpe = metrics.get("sharpe", 0.0)
            if sharpe < rollback_sharpe_floor:
                logger.warning(
                    f"Auto-rollback experiment #{exp.id} for {exp.strategy_name}: "
                    f"sharpe {sharpe} < floor {rollback_sharpe_floor}"
                )
                self.rollback(db, exp.strategy_name)

        # --- Phase 2: promote qualifying candidates ---
        candidates = db.query(Experiment).filter(Experiment.status == "candidate").all()

        by_strategy: dict[str, list] = {}
        for c in candidates:
            by_strategy.setdefault(c.strategy_name, []).append(c)

        for strategy_name, strategy_candidates in by_strategy.items():
            active = (
                db.query(Experiment)
                .filter(
                    Experiment.strategy_name == strategy_name,
                    Experiment.status == "active",
                )
                .first()
            )

            active_sharpe = 0.0
            if active and active.metrics_json:
                active_metrics = json.loads(active.metrics_json)
                active_sharpe = active_metrics.get("sharpe", 0.0)

            best_candidate = None
            best_sharpe = active_sharpe

            for candidate in strategy_candidates:
                metrics = (
                    json.loads(candidate.metrics_json) if candidate.metrics_json else {}
                )
                num_trades = metrics.get("num_trades", 0)
                candidate_sharpe = metrics.get("sharpe", 0.0)

                if num_trades < min_trades:
                    continue
                if candidate_sharpe - active_sharpe < min_sharpe_diff:
                    continue

                if candidate_sharpe > best_sharpe:
                    best_sharpe = candidate_sharpe
                    best_candidate = candidate

            if best_candidate is not None:
                logger.info(
                    f"Auto-promoting experiment #{best_candidate.id} for "
                    f"{strategy_name}: sharpe {best_sharpe:.4f} vs "
                    f"active {active_sharpe:.4f} (diff {best_sharpe - active_sharpe:.4f})"
                )
                if self.promote(db, best_candidate.id):
                    promoted_ids.append(best_candidate.id)

        return promoted_ids

    def get_history(
        self,
        db: Session,
        strategy_name: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """Get experiment history for a strategy."""
        from backend.models.database import Experiment

        query = db.query(Experiment).order_by(Experiment.created_at.desc())
        if strategy_name:
            query = query.filter(Experiment.strategy_name == strategy_name)

        experiments = query.limit(limit).all()
        return [
            {
                "id": e.id,
                "strategy": e.strategy_name,
                "status": e.status,
                "params": json.loads(e.params_json) if e.params_json else {},
                "metrics": json.loads(e.metrics_json) if e.metrics_json else {},
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "promoted_at": e.promoted_at.isoformat() if e.promoted_at else None,
                "notes": e.notes,
            }
            for e in experiments
        ]


# Module-level singleton
experiment_tracker = ExperimentTracker()
