"""Fronttest Scheduler — periodic validation of pending proposals for live promotion.

Runs FronttestValidator.validate_all_pending() on a schedule and promotes
approved proposals to live.
"""

from __future__ import annotations

from typing import Any

from loguru import logger


async def fronttest_validation_job() -> dict[str, Any]:
    """Scheduled job: validate all pending fronttest proposals.

    Checks each executed proposal against its trial period, trade count,
    and win rate thresholds. Promotes approved ones to live if auto-promote
    is enabled.

    Returns stats dict.
    """
    stats: dict[str, Any] = {
        "proposals_checked": 0,
        "approved": 0,
        "promoted": 0,
        "rejected": 0,
        "errors": [],
    }

    try:
        from backend.core.fronttest_validator import fronttest_validator
        from backend.config import settings

        results = fronttest_validator.validate_all_pending()
        stats["proposals_checked"] = len(results)

        for result in results:
            if result.get("approved"):
                stats["approved"] += 1
                proposal_id = result.get("proposal_id")
                strategy = result.get("strategy", "unknown")
                logger.info(
                    "[FronttestScheduler] Proposal %d (%s) APPROVED — "
                    "wr=%.1f%%, %d trades, %d days",
                    proposal_id,
                    strategy,
                    result.get("win_rate", 0) * 100,
                    result.get("trade_count", 0),
                    result.get("elapsed_days", 0),
                )
                # Auto-promote if enabled
                if getattr(settings, "AGI_AUTO_PROMOTE", False) and proposal_id:
                    try:
                        from backend.models.database import (
                            StrategyProposal,
                            StrategyConfig,
                        )
                        from backend.db.utils import get_db_session

                        with get_db_session() as db:
                            proposal = (
                                db.query(StrategyProposal)
                                .filter(
                                    StrategyProposal.id == proposal_id,
                                )
                                .first()
                            )
                            if proposal and proposal.admin_decision == "executed":
                                # Apply the change details to strategy config
                                config = (
                                    db.query(StrategyConfig)
                                    .filter(
                                        StrategyConfig.strategy_name == strategy,
                                    )
                                    .first()
                                )
                                if config:
                                    config.enabled = True
                                    proposal.admin_decision = "auto_approved"
                                    stats["promoted"] += 1
                                    logger.info(
                                        "[FronttestScheduler] Auto-promoted '%s' to live",
                                        strategy,
                                    )
                                db.commit()
                    except Exception as e:
                        stats["errors"].append(f"promote_{proposal_id}: {e}")
                        logger.error(
                            "[FronttestScheduler] Auto-promote failed for proposal %d: %s",
                            proposal_id,
                            e,
                        )
            else:
                stats["rejected"] += 1

        logger.info(
            "[FronttestScheduler] Validation complete: checked=%d approved=%d "
            "promoted=%d rejected=%d",
            stats["proposals_checked"],
            stats["approved"],
            stats["promoted"],
            stats["rejected"],
        )
    except Exception as e:
        logger.error("[FronttestScheduler] Validation job failed: %s", e, exc_info=True)
        stats["errors"].append(f"validation: {e}")

    return stats
