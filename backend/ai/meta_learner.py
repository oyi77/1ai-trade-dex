"""Meta-Learner: learns from past proposals which changes improve strategies.

Reads ProposalFeedback records, aggregates success patterns by (strategy, param, direction),
and biases future evolution toward historically successful mutations.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from backend.models.database import SessionLocal
from backend.models.outcome_tables import MetaLearningRecord, ProposalFeedback

logger = logging.getLogger("trading_bot.meta_learner")


class MetaLearner:
    def get_biases(self, strategy: str, db: Optional[Session] = None) -> dict[str, dict]:
        """Return learned biases for a strategy's parameters.

        Returns: {param_name: {"direction": "up"|"down"|"neutral", "confidence": 0.0-1.0, "avg_improvement": float}}
        """
        _owned = db is None
        db = db or SessionLocal()
        try:
            rows = db.query(MetaLearningRecord).filter(
                MetaLearningRecord.strategy.in_([strategy, "*"]),
                MetaLearningRecord.sample_size >= 3,
            ).all()

            biases = {}
            for row in rows:
                success_rate = row.success_count / row.sample_size if row.sample_size > 0 else 0.5
                if success_rate > 0.55:
                    biases[row.param_name] = {
                        "direction": row.change_direction,
                        "confidence": min(success_rate, 0.95),
                        "avg_improvement": row.avg_improvement,
                    }
            return biases
        finally:
            if _owned:
                db.close()

    def record_outcome(
        self,
        strategy: str,
        param_name: str,
        change_direction: str,
        wr_delta: float,
        sharpe_delta: float,
        improved: bool,
        db: Optional[Session] = None,
    ) -> None:
        _owned = db is None
        db = db or SessionLocal()
        try:
            existing = db.query(MetaLearningRecord).filter(
                MetaLearningRecord.strategy == strategy,
                MetaLearningRecord.param_name == param_name,
                MetaLearningRecord.change_direction == change_direction,
            ).first()

            if existing:
                n = existing.sample_size
                existing.sample_size = n + 1
                existing.success_count += 1 if improved else 0
                alpha = 1.0 / (n + 1)
                existing.avg_wr_delta = existing.avg_wr_delta * (1 - alpha) + wr_delta * alpha
                existing.avg_sharpe_delta = existing.avg_sharpe_delta * (1 - alpha) + sharpe_delta * alpha
                existing.avg_improvement = existing.avg_improvement * (1 - alpha) + (1.0 if improved else -1.0) * alpha
                existing.last_updated = datetime.now(timezone.utc)
            else:
                db.add(MetaLearningRecord(
                    strategy=strategy,
                    param_name=param_name,
                    change_direction=change_direction,
                    sample_size=1,
                    success_count=1 if improved else 0,
                    avg_improvement=1.0 if improved else -1.0,
                    avg_wr_delta=wr_delta,
                    avg_sharpe_delta=sharpe_delta,
                ))
            db.commit()
        except Exception as e:
            logger.warning("[MetaLearner] Failed to record: %s", e)
            if _owned:
                db.rollback()
        finally:
            if _owned:
                db.close()

    def update_from_feedback(self, db: Optional[Session] = None) -> int:
        """Scan ProposalFeedback records with improved!=None and feed into meta-learning."""
        _owned = db is None
        db = db or SessionLocal()
        count = 0
        try:
            feedbacks = db.query(ProposalFeedback).filter(
                ProposalFeedback.improved.isnot(None),
                ProposalFeedback.measured_at.is_(None),
            ).all()

            for fb in feedbacks:
                params = fb.params_changed or {}
                wr_delta = (fb.post_wr or 0.0) - (fb.pre_wr or 0.0)
                sharpe_delta = (fb.post_sharpe or 0.0) - (fb.pre_sharpe or 0.0)

                for param_name in params:
                    old_val = None
                    new_val = params[param_name]
                    if isinstance(new_val, (int, float)):
                        direction = "up" if new_val > (old_val or 0) else "down"
                        self.record_outcome(
                            strategy=fb.strategy,
                            param_name=param_name,
                            change_direction=direction,
                            wr_delta=wr_delta,
                            sharpe_delta=sharpe_delta,
                            improved=fb.improved or False,
                            db=db,
                        )
                        count += 1

                fb.measured_at = datetime.now(timezone.utc)
                db.commit()

            return count
        except Exception as e:
            logger.warning("[MetaLearner] update_from_feedback failed: %s", e)
            return count
        finally:
            if _owned:
                db.close()
