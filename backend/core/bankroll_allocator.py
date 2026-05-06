"""Bankroll Allocator — daily auto-allocation of capital across ranked strategies.

Reads strategy performance rankings from StrategyRanker and distributes
bankroll proportionally to risk-adjusted returns. Caps allocation at 50%
per strategy. Writes allocations into BotState for observability.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from backend.config import settings
from backend.models.database import SessionLocal, BotState
from backend.core.strategy_ranker import StrategyRanker

logger = logging.getLogger("trading_bot.bankroll_allocator")


class BankrollAllocator:
    """Daily daemon that rebalances capital across active strategies."""

    def __init__(self, ranker: Optional[StrategyRanker] = None):
        self.ranker = ranker or StrategyRanker()
        self._last_run: Optional[datetime] = None

    async def run_once(self) -> dict[str, float]:
        """Compute and apply fresh bankroll allocation.

        Returns the allocation dict {strategy: amount}.
        """
        import json
        db = SessionLocal()
        try:
            all_allocations = {}
            for mode in settings.active_modes_set:
                state = db.query(BotState).filter_by(mode=mode).first()
                if not state:
                    continue
                bankroll = state.bankroll or 0.0
                if bankroll <= 0:
                    logger.warning(f"[BankrollAllocator] {mode}: Bankroll ${bankroll:.2f} too low, skipping")
                    continue

                allocations = self.ranker.auto_allocate(db, bankroll, lookback_days=30, trading_mode=mode)

                try:
                    misc = json.loads(state.misc_data) if state.misc_data else {}
                except Exception:
                    misc = {}
                misc["allocations"] = allocations
                misc["last_allocation_ts"] = datetime.now(timezone.utc).isoformat()
                misc["allocation_bankroll"] = bankroll
                state.misc_data = json.dumps(misc)
                db.commit()
                logger.info(f"[BankrollAllocator] {mode}: Persisted allocations to BotState")
                all_allocations[mode] = allocations

            if not all_allocations:
                logger.warning("[BankrollAllocator] No BotState found for any active mode, skipping allocation")
                return {}
            return all_allocations
        except Exception as e:
            logger.error(f"[BankrollAllocator] Run failed: {e}", exc_info=True)
            return {}
        finally:
            db.close()


# Module-level singleton
bankroll_allocator = BankrollAllocator()


async def bankroll_allocation_job() -> None:
    """Scheduled job entrypoint for APScheduler."""
    try:
        alloc = await bankroll_allocator.run_once()
        if alloc:
            logger.info(f"[bankroll_allocation_job] Allocation complete: {alloc}")
    except Exception as e:
        logger.error(f"[bankroll_allocation_job] Fatal error: {e}", exc_info=True)
