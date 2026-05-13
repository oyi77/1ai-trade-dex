"""Bankroll Allocator — daily auto-allocation of capital across ranked strategies.

Reads strategy performance rankings from StrategyRanker and distributes
bankroll proportionally to risk-adjusted returns. Caps allocation at 50%
per strategy. Writes allocations into BotState for observability.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from backend.config import settings
from backend.models.database import BotState, for_update
from backend.core.strategy_ranker import StrategyRanker

from loguru import logger
class BankrollAllocator:
    """Daily daemon that rebalances capital across active strategies."""

    def __init__(self, ranker: Optional[StrategyRanker] = None):
        self.ranker = ranker or StrategyRanker()
        self._last_run: Optional[datetime] = None

    async def run_once(self) -> dict[str, float]:
        """Compute and apply fresh bankroll allocation.

        Returns the allocation dict {strategy: amount}.
        """
        from backend.db.utils import get_db_session

        try:
            all_allocations = {}
            for mode in settings.active_modes_set:
                with get_db_session() as db:
                    state = for_update(db, db.query(BotState).filter_by(mode=mode)).first()
                    if not state:
                        continue
                    bankroll = state.bankroll or 0.0
                    if bankroll <= 0:
                        logger.warning(f"[BankrollAllocator] {mode}: Bankroll ${bankroll:.2f} too low, skipping")
                        continue

                    allocations = self.ranker.auto_allocate(db, bankroll, lookback_days=30, trading_mode=mode)

                    # Apply feedback adjustments
                    allocations = self.apply_longshot_feedback(allocations)
                    allocations = self.apply_role_feedback(allocations)
                    allocations = self.apply_calibration_feedback(allocations)

                    try:
                        misc = json.loads(state.misc_data) if state.misc_data else {}
                    except Exception:
                        logger.exception("[BankrollAllocator] Failed to parse BotState.misc_data JSON")
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

    def apply_longshot_feedback(self, allocations: dict[str, float]) -> dict[str, float]:
        """Reduce allocation for strategies with high longshot bias.

        Bias > 0.05 → skip (no_side). Bias > 0.03 → confidence_discount applied.
        """
        from backend.core.longshot_bias import LongshotBiasDetector
        detector = LongshotBiasDetector()
        try:
            category_bias = detector.get_category_bias(days=30)
            if not category_bias:
                return allocations

            adjusted = dict(allocations)
            for strategy, bias in category_bias.items():
                if bias > 0.05:
                    # Strong overconfidence — skip entirely
                    if strategy in adjusted:
                        adjusted[strategy] = 0.0
                    logger.info(f"[BankrollAllocator] Longshot skip {strategy}: bias={bias:.4f}")
                elif bias > 0.03:
                    # Mild overconfidence — reduce by 30%
                    if strategy in adjusted:
                        adjusted[strategy] = adjusted[strategy] * 0.7
                    logger.info(f"[BankrollAllocator] Longshot discount {strategy}: bias={bias:.4f}")

            return adjusted
        except Exception as e:
            logger.warning(f"[BankrollAllocator] Longshot feedback failed: {e}")
            return allocations

    def apply_role_feedback(self, allocations: dict[str, float]) -> dict[str, float]:
        """Boost allocation for strategies where maker trades outperform taker trades."""
        from backend.models.database import Trade
        from datetime import datetime, timezone, timedelta
        from backend.db.utils import get_db_session

        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=30)
            with get_db_session() as db:
                trades = db.query(Trade).filter(
                    Trade.timestamp >= cutoff,
                    Trade.role.isnot(None),
                    Trade.pnl.isnot(None),
                ).all()

                # Group by strategy
                by_strategy: dict[str, list] = {}
                for t in trades:
                    strat = t.strategy or "unknown"
                    if strat not in by_strategy:
                        by_strategy[strat] = []
                    by_strategy[strat].append(t)

                # Compute maker vs taker avg_pnl per strategy
                maker_boost_strategies = set()
                for strat, strat_trades in by_strategy.items():
                    maker_trades = [t for t in strat_trades if t.role == "maker"]
                    taker_trades = [t for t in strat_trades if t.role == "taker"]

                    if maker_trades and taker_trades:
                        maker_avg = sum(t.pnl or 0 for t in maker_trades) / len(maker_trades)
                        taker_avg = sum(t.pnl or 0 for t in taker_trades) / len(taker_trades)
                        if maker_avg > taker_avg * 1.1:
                            maker_boost_strategies.add(strat)
                            logger.info(f"[BankrollAllocator] Maker edge for {strat}: maker={maker_avg:.4f} vs taker={taker_avg:.4f}")

                # Apply +20% boost to maker-edge strategies
                adjusted = dict(allocations)
                for strat in maker_boost_strategies:
                    if strat in adjusted and adjusted[strat] > 0:
                        adjusted[strat] = adjusted[strat] * 1.2
                        logger.info(f"[BankrollAllocator] Role boost {strat}: +20%")

                return adjusted
        except Exception as e:
            logger.warning(f"[BankrollAllocator] Role feedback failed: {e}")
            return allocations

    def apply_calibration_feedback(self, allocations: dict[str, float]) -> dict[str, float]:
        """Reduce signal weight for strategies with poorly calibrated price buckets."""
        from backend.core.calibration_tracker import get_bucket_calibration

        try:
            buckets = get_bucket_calibration(days=60, min_samples=10)
            if not buckets:
                return allocations

            # Find biased buckets (bias_direction == 'overconfident')
            biased_buckets = {b["bucket"] for b in buckets if b.get("bias_direction") == "overconfident"}
            if not biased_buckets:
                return allocations

            # We don't have per-strategy bucket data in the simple version
            # Just apply a small global discount if there are overconfident buckets
            if biased_buckets:
                logger.info(f"[BankrollAllocator] Overconfident buckets detected: {biased_buckets}")
                # For simplicity, discount all by 5% if there's any global overconfidence
                return {s: a * 0.95 for s, a in allocations.items()}

            return allocations
        except Exception as e:
            logger.warning(f"[BankrollAllocator] Calibration feedback failed: {e}")
            return allocations

    def get_wallet_allocation(self, strategy_name: str, total_allocation: float) -> dict[int, float]:
        from backend.db.utils import get_db_session
        from backend.models.trading_wallet import WalletAllocation
        
        try:
            with get_db_session() as db:
                rows = db.query(WalletAllocation).filter(
                    WalletAllocation.strategy_name == strategy_name,
                    WalletAllocation.enabled.is_(True)
                ).all()
                
                if not rows:
                    return {}
                    
                total_weight = sum(r.weight for r in rows)
                if total_weight <= 0:
                    return {}
                    
                result = {}
                for row in rows:
                    raw_allocation = total_allocation * (row.weight / total_weight)
                    if row.max_exposure_usd is not None:
                        result[row.wallet_id] = min(raw_allocation, row.max_exposure_usd)
                    else:
                        result[row.wallet_id] = raw_allocation
                        
                return result
        except Exception as e:
            logger.error(f"[BankrollAllocator] get_wallet_allocation failed for {strategy_name}: {e}")
            return {}

            # Find biased buckets (bias_direction == 'overconfident')
            biased_buckets = {b["bucket"] for b in buckets if b.get("bias_direction") == "overconfident"}
            if not biased_buckets:
                return allocations

            # We don't have per-strategy bucket data in the simple version
            # Just apply a small global discount if there are overconfident buckets
            if biased_buckets:
                logger.info(f"[BankrollAllocator] Overconfident buckets detected: {biased_buckets}")
                adjusted = {k: v * 0.95 for k, v in allocations.items()}
                return adjusted

            return allocations
        except Exception as e:
            logger.warning(f"[BankrollAllocator] Calibration feedback failed: {e}")
            return allocations


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
