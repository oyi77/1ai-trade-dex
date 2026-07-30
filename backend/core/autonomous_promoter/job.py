"""Job entrypoint — module-level singleton and scheduled APScheduler job."""

from __future__ import annotations

from loguru import logger


# Module-level singleton (built after mixin resolution)
from . import AutonomousPromoter

autonomous_promoter = AutonomousPromoter()


async def autonomous_promotion_job() -> None:
    """Scheduled job entrypoint for APScheduler."""
    try:
        stats = await autonomous_promoter.run_once()
        logger.info(f"[autonomous_promotion_job] Completed: {stats}")
    except Exception as e:
        logger.error(f"[autonomous_promotion_job] Fatal error: {e}", exc_info=True)
