"""TradeForensics to AGI improvement integration — feeds loss patterns into proposals."""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from backend.models.database import SessionLocal, StrategyProposal

from loguru import logger
def generate_forensics_proposals(
    lookback_hours: int = 168,
    min_losses: int = 5,
    db: Optional[Session] = None,
    strategy_filter: Optional[str] = None,
) -> list[int]:
    _owned = db is None
    db = db or SessionLocal()
    created_ids = []
    try:
        from backend.models.outcome_tables import StrategyOutcome

        cutoff = datetime.now(timezone.utc)
        from datetime import timedelta

        since = cutoff - timedelta(hours=lookback_hours)

        outcome_query = db.query(StrategyOutcome).filter(
            StrategyOutcome.result == "loss",
            StrategyOutcome.settled_at >= since,
        )
        if strategy_filter:
            outcome_query = outcome_query.filter(StrategyOutcome.strategy == strategy_filter)
        outcomes = outcome_query.all()

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

            # Strategies with any win rate (including 0%) are eligible for a new
            # experiment. Fundamentally broken strategies get a full parameter
            # overhaul rather than incremental tuning.
            auto_promotable = total_trades >= 10

            overhaul_needed = fundamentally_broken and getattr(
                __import__("backend.config", fromlist=["settings"]).settings,
                "AGI_BROKEN_STRATEGY_OVERHAUL_ENABLED",
                True,
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
                    "fundamentally_broken": fundamentally_broken,
                    "overhaul": overhaul_needed,
                },
                expected_impact=(
                    f"Forensics: {len(losses)} losses (${total_loss:.2f}) in "
                    f"{lookback_hours}h — "
                    f"{'FULL PARAMETER OVERHAUL (broken strategy)' if overhaul_needed else 'parameter tuning needed'}"
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
                    import random as _random

                    # For broken strategies, randomise all tunable params within
                    # safe bounds (overhaul). For normal strategies, use forensics
                    # context so the evolver can tune incrementally.
                    if overhaul_needed:
                        composition: dict = {
                            "source": "forensics_overhaul",
                            "min_edge": round(_random.uniform(0.03, 0.15), 3),
                            "kelly_fraction": round(_random.uniform(0.05, 0.25), 3),
                            "max_position_usd": round(_random.uniform(5.0, 50.0), 1),
                            "interval_seconds": _random.choice([30, 60, 120, 300]),
                            "total_trades": total_trades,
                            "win_rate": round(win_rate, 4),
                        }
                    else:
                        composition = {
                            "source": "forensics",
                            "loss_count": len(losses),
                            "total_loss": round(total_loss, 2),
                            "win_rate": round(win_rate, 4),
                            "total_trades": total_trades,
                        }

                    exp = ExperimentRecord(
                        name=f"{strategy_name}_forensics_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}",
                        strategy_name=strategy_name,
                        strategy_composition=composition,
                        status=ExperimentStatus.DRAFT.value,
                        created_at=datetime.now(timezone.utc),
                    )
                    db.add(exp)
                    logger.info(
                        "[ForensicsIntegration] Auto-created DRAFT experiment for '%s' "
                        "(wr=%.1f%%, %d trades, overhaul=%s)",
                        strategy_name, win_rate * 100, total_trades, overhaul_needed,
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
                logger.exception("[ForensicsIntegration] Rollback failed after forensics error")
        return created_ids
    finally:
        if _owned:
            db.close()


def _has_active_experiment(strategy_name: str, db: Session) -> bool:
    """Return True only if there is a non-retired, non-live-failed experiment in flight.

    RETIRED and LIVE_FAILED experiments are excluded so that broken strategies
    can re-enter the pipeline via a new DRAFT experiment.
    """
    from backend.models.kg_models import ExperimentRecord
    from backend.core.agi_types import ExperimentStatus
    # Only block if there is an experiment actively running through the pipeline
    active = [
        ExperimentStatus.DRAFT.value,
        ExperimentStatus.BACKTEST.value,
        ExperimentStatus.SHADOW.value,
        ExperimentStatus.PAPER.value,
        ExperimentStatus.LIVE_TRIAL.value,
        ExperimentStatus.LIVE_PROMOTED.value,
        ExperimentStatus.REVIEW.value,
    ]
    return (
        db.query(ExperimentRecord)
        .filter(ExperimentRecord.strategy_name == strategy_name, ExperimentRecord.status.in_(active))
        .first()
        is not None
    )
