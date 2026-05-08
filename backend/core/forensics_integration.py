"""TradeForensics to AGI improvement integration — feeds loss patterns into proposals."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from backend.models.database import SessionLocal, StrategyProposal

logger = logging.getLogger("trading_bot.forensics_integration")


def generate_forensics_proposals(
    lookback_hours: int = 168,
    min_losses: int = 5,
    db: Optional[Session] = None,
) -> list[int]:
    _owned = db is None
    db = db or SessionLocal()
    created_ids = []
    try:
        from backend.models.outcome_tables import StrategyOutcome

        cutoff = datetime.now(timezone.utc)
        from datetime import timedelta

        since = cutoff - timedelta(hours=lookback_hours)

        outcomes = (
            db.query(StrategyOutcome)
            .filter(
                StrategyOutcome.result == "loss",
                StrategyOutcome.settled_at >= since,
            )
            .all()
        )

        by_strategy: dict[str, list] = {}
        for o in outcomes:
            by_strategy.setdefault(o.strategy, []).append(o)

        for strategy_name, losses in by_strategy.items():
            if len(losses) < min_losses:
                continue

            total_loss = sum(abs(o.pnl or 0.0) for o in losses)
            existing = db.query(StrategyProposal).filter(
                StrategyProposal.strategy_name == strategy_name,
                StrategyProposal.status == "pending",
            ).first()
            if existing:
                continue

            all_outcomes = db.query(StrategyOutcome).filter(
                StrategyOutcome.strategy == strategy_name
            ).all()
            total_trades = len(all_outcomes)
            wins = sum(1 for o in all_outcomes if o.result == "win")
            win_rate = wins / total_trades if total_trades > 0 else 0.0

            fundamentally_broken = (
                total_trades >= 30 and win_rate == 0.0
            )

            auto_promotable = (
                not fundamentally_broken
                and 0.05 <= win_rate < 0.35
                and total_trades >= 10
            )

            proposal = StrategyProposal(
                strategy_name=strategy_name,
                change_details={
                    "source": "trade_forensics",
                    "loss_count": len(losses),
                    "total_loss": round(total_loss, 2),
                    "lookback_hours": lookback_hours,
                    "total_trades": total_trades,
                    "win_rate": round(win_rate, 4),
                },
                expected_impact=(
                    f"Forensics: {len(losses)} losses (${total_loss:.2f}) in "
                    f"{lookback_hours}h — {'FUNDAMENTALLY BROKEN (staying killed)' if fundamentally_broken else 'parameter tuning needed'}"
                ),
                admin_decision="pending",
                status="pending",
                auto_promotable=auto_promotable,
            )
            db.add(proposal)
            db.flush()
            created_ids.append(proposal.id)

            if auto_promotable and not _has_active_experiment(strategy_name, db):
                try:
                    from backend.models.kg_models import ExperimentRecord
                    from backend.core.agi_types import ExperimentStatus

                    exp = ExperimentRecord(
                        name=f"{strategy_name}_forensics_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}",
                        strategy_name=strategy_name,
                        strategy_composition={
                            "source": "forensics",
                            "loss_count": len(losses),
                            "total_loss": round(total_loss, 2),
                            "win_rate": round(win_rate, 4),
                            "total_trades": total_trades,
                        },
                        status=ExperimentStatus.DRAFT.value,
                        created_at=datetime.now(timezone.utc),
                    )
                    db.add(exp)
                    logger.info(
                        "[ForensicsIntegration] Auto-created DRAFT experiment for '%s' (wr=%.1f%%, %d trades)",
                        strategy_name, win_rate * 100, total_trades,
                    )
                except Exception as exp_err:
                    logger.warning("[ForensicsIntegration] Experiment creation failed for '%s': %s", strategy_name, exp_err)

        if created_ids:
            db.commit()
            logger.info(
                "[ForensicsIntegration] Created %d forensics-based proposals",
                len(created_ids),
            )
        return created_ids
    except Exception as e:
        logger.error("[ForensicsIntegration] Failed: %s", e)
        if _owned:
            try:
                db.rollback()
            except Exception:
                pass
        return created_ids
    finally:
        if _owned:
            db.close()


def _has_active_experiment(strategy_name: str, db: Session) -> bool:
    from backend.models.kg_models import ExperimentRecord
    from backend.core.agi_types import ExperimentStatus
    active = [ExperimentStatus.DRAFT.value, ExperimentStatus.SHADOW.value, ExperimentStatus.PAPER.value]
    return (
        db.query(ExperimentRecord)
        .filter(ExperimentRecord.strategy_name == strategy_name, ExperimentRecord.status.in_(active))
        .first()
        is not None
    )
