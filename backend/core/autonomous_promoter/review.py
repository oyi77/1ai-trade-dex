"""ReviewMixin — promotion review capture and logging for AutonomousPromoter."""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from backend.models.kg_models import ExperimentRecord

from loguru import logger


class ReviewMixin:
    """Mixin providing promotion review capture and structured logging."""

    def _capture_promotion_review(
        self,
        exp: ExperimentRecord,
        db: Session,
        from_stage: str,
        to_stage: str,
        health: dict,
    ) -> None:
        """Capture a structured metrics snapshot on stage transition.

        Stores the review in exp.misc_data as a list of promotion reviews,
        each containing the stage pair, metrics snapshot, and timestamp.
        Previous reviews are preserved for cross-stage comparison.
        """
        import json as _json

        metrics = {
            "trades": health.get("total_trades", 0),
            "win_rate": round(health.get("win_rate", 0.0), 4),
            "sharpe": round(health.get("sharpe", 0.0), 4),
            "pnl": round(health.get("pnl", 0.0), 4),
            "drawdown": round(health.get("max_drawdown", 0.0), 4),
        }

        review = {
            "from_stage": from_stage,
            "to_stage": to_stage,
            "metrics_at_promotion": metrics,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Load existing misc_data, preserving any prior reviews
        existing = exp.misc_data
        if isinstance(existing, str):
            try:
                existing = _json.loads(existing)
            except (_json.JSONDecodeError, TypeError):
                existing = {}
        if not isinstance(existing, dict):
            existing = {}

        reviews = existing.get("promotion_reviews", [])
        reviews.append(review)
        existing["promotion_reviews"] = reviews
        exp.misc_data = existing

        db.add(exp)
        self._log_promotion_review(exp, from_stage, to_stage, metrics, reviews)

    def _log_promotion_review(
        self,
        exp: ExperimentRecord,
        from_stage: str,
        to_stage: str,
        metrics: dict,
        reviews: list[dict],
    ) -> None:
        """Format and log a structured promotion review summary."""
        # Build comparison against previous stage metrics
        comparison = ""
        if len(reviews) >= 2:
            prev = reviews[-2].get("metrics_at_promotion", {})
            deltas = []
            for key in ("win_rate", "sharpe", "pnl"):
                prev_val = prev.get(key, 0)
                curr_val = metrics.get(key, 0)
                delta = curr_val - prev_val
                sign = "+" if delta >= 0 else ""
                deltas.append(f"{key}: {sign}{delta:.4f}")
            comparison = f" | deltas from {reviews[-2].get('from_stage', '?')}→{reviews[-2].get('to_stage', '?')}: {', '.join(deltas)}"

        logger.info(
            f"[PromotionReview] {from_stage}→{to_stage} '{exp.name}': "
            f"trades={metrics['trades']}, wr={metrics['win_rate']:.1%}, "
            f"sharpe={metrics['sharpe']:.2f}, pnl={metrics['pnl']:.4f}, "
            f"dd={metrics['drawdown']:.1%}"
            f"{comparison}"
        )
