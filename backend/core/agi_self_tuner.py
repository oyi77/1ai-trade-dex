"""AGI Self-Tuning Orchestrator — connects learning to parameter adjustment.

Unifies the feedback loop between LearningPipeline (lesson extraction),
CognitiveCore (memory), SafeParamTuner (clamped parameter changes),
and StrategyPerformanceTracker (metrics).

Entry points:
- process_settlement(): called after each trade settlement
- evaluate_and_tune(): evaluate a single strategy and tune if needed
- periodic_review(): called by scheduler every 30 minutes
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from loguru import logger

from backend.config import settings
from backend.core.event_bus import publish_event
from backend.monitoring.agi_metrics import record_pipeline_error

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_TRADES_FOR_TUNING = settings.AGI_TUNER_MIN_TRADES_FOR_TUNING
WIN_RATE_FLOOR = (
    settings.AGI_TUNER_WIN_RATE_FLOOR
)  # below this after 10+ trades -> attempt tuning
WIN_RATE_CEILING = (
    settings.AGI_TUNER_WIN_RATE_CEILING
)  # above this after 20+ trades -> consider loosening
MAX_PARAM_CHANGE_PCT = (
    settings.AGI_TUNER_MAX_PARAM_CHANGE_PCT
)  # hard cap on any single parameter change
ROLLBACK_WINDOW = settings.AGI_TUNER_ROLLBACK_WINDOW  # trades to monitor after a change
ROLLBACK_DEGRADATION = (
    settings.AGI_TUNER_ROLLBACK_DEGRADATION
)  # >15% win rate drop triggers revert


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_agi_self_tuner: Optional["AGISelfTuner"] = None


def get_agi_self_tuner() -> "AGISelfTuner":
    """Get or create the module-level AGISelfTuner singleton."""
    global _agi_self_tuner
    if _agi_self_tuner is None:
        _agi_self_tuner = AGISelfTuner()
    return _agi_self_tuner


# ---------------------------------------------------------------------------
# AGISelfTuner
# ---------------------------------------------------------------------------


class AGISelfTuner:
    """Orchestrates self-tuning across all AGI components.

    Connects:
    - LearningPipeline (lesson extraction after settlement)
    - CognitiveCore (lesson recall and decision storage)
    - SafeParamTuner (clamped, reversible parameter changes)
    - StrategyPerformanceTracker (per-strategy metrics)
    """

    def __init__(self) -> None:
        self._pending_rollbacks: Dict[str, Dict[str, Any]] = {}
        # strategy_name -> {pre_change_win_rate, applied_at, trade_count_at_apply}

    # ------------------------------------------------------------------
    # Entry point 1: post-settlement hook
    # ------------------------------------------------------------------

    async def process_settlement(
        self,
        trade_id: int,
        strategy_name: str,
        market_id: str,
        outcome: str,
        pnl_usd: float,
        asset: Optional[str] = None,
    ) -> None:
        """Called after each trade settlement. Entry point for the feedback loop.

        1. Check rollback state for this strategy
        2. If strategy needs tuning, trigger evaluate_and_tune
        3. Store the tuning decision in CognitiveCore
        """
        if settings.SHADOW_MODE and not settings.AGI_SELF_TUNE_IN_PAPER:
            return  # only collect data in shadow mode (unless paper tuning enabled)

        try:
            # Check if we need to rollback a previous change
            self._check_rollback(strategy_name, outcome)

            # Check if this strategy warrants tuning
            from backend.core.strategy_performance_tracker import (
                get_performance_tracker,
            )

            tracker = get_performance_tracker()

            if not tracker.should_tune(strategy_name):
                return

            # Throttle: only tune after every 10 settlements for a strategy
            perf = tracker.get_performance(strategy_name, limit=50)
            if perf.total_trades < MIN_TRADES_FOR_TUNING:
                return

            # Attempt tuning
            changes = await self.evaluate_and_tune(strategy_name, asset=asset)
            if changes:
                logger.info(
                    f"[AGISelfTuner] Post-settlement tune for {strategy_name}: "
                    f"{list(changes.keys())}"
                )
        except Exception:
            record_pipeline_error("agi_self_tuner")
            logger.exception(
                f"[AGISelfTuner] Error in process_settlement for trade {trade_id}"
            )

    # ------------------------------------------------------------------
    # Entry point 2: evaluate and tune a single strategy
    # ------------------------------------------------------------------

    async def evaluate_and_tune(
        self,
        strategy_name: str,
        asset: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Evaluate strategy performance and tune if needed.

        1. Get recent performance from trade history
        2. Recall relevant lessons from CognitiveCore
        3. Compute optimal parameters using SafeParamTuner
        4. Apply with rollback protection

        Returns:
            Dict of changed parameters, empty if no changes applied.
        """
        from backend.core.strategy_performance_tracker import get_performance_tracker
        from backend.core.safe_param_tuner import SafeParamTuner
        from backend.db.utils import get_db_session

        tracker = get_performance_tracker()
        perf = tracker.get_performance(strategy_name, asset=asset, limit=50)

        if perf.total_trades < MIN_TRADES_FOR_TUNING:
            return {}

        # Decide tuning direction based on performance
        if perf.win_rate >= WIN_RATE_CEILING and perf.total_trades >= 20:
            # Strategy is doing well — consider loosening constraints
            direction = "loosen"
        elif perf.win_rate < WIN_RATE_FLOOR:
            # Strategy is underperforming — tighten or adjust
            direction = "tighten"
        else:
            # Performance is acceptable — skip tuning
            return {}

        logger.info(
            f"[AGISelfTuner] {strategy_name}: win_rate={perf.win_rate:.2f}, "
            f"trades={perf.total_trades}, direction={direction}"
        )

        # Use SafeParamTuner for clamped changes
        try:
            with get_db_session() as db:
                tuner = SafeParamTuner()
                changes = tuner.tune(strategy_name, db)

                if changes:
                    # Record rollback state
                    self._pending_rollbacks[strategy_name] = {
                        "pre_change_win_rate": perf.win_rate,
                        "applied_at": datetime.now(timezone.utc).isoformat(),
                        "trade_count_at_apply": perf.total_trades,
                        "changes": changes,
                    }

                    # Store decision in CognitiveCore
                    self._store_tuning_decision(strategy_name, direction, changes, perf)

                    publish_event(
                        "agi_self_tune",
                        {
                            "strategy_name": strategy_name,
                            "direction": direction,
                            "changes": changes,
                            "win_rate": perf.win_rate,
                            "trade_count": perf.total_trades,
                        },
                    )

                return changes
        except Exception:
            record_pipeline_error("agi_self_tuner")
            logger.exception(f"[AGISelfTuner] Tuning failed for {strategy_name}")
            return {}

    # ------------------------------------------------------------------
    # Entry point 3: periodic review (scheduler job)
    # ------------------------------------------------------------------

    async def periodic_review(self) -> None:
        """Called by scheduler (every 30 min). Reviews all strategies.

        1. For each active strategy, check performance
        2. If win rate < 40% after 10+ trades, attempt tuning
        3. If win rate > 60% after 20+ trades, consider loosening constraints
        4. Store decisions in CognitiveCore for future reference
        """
        if settings.SHADOW_MODE and not settings.AGI_SELF_TUNE_IN_PAPER:
            logger.debug("[AGISelfTuner] Shadow mode — skipping periodic review")
            return

        from backend.core.strategy_performance_tracker import get_performance_tracker
        from backend.db.utils import get_db_session
        from backend.models.database import StrategyConfig

        tracker = get_performance_tracker()
        tuned_count = 0

        try:
            with get_db_session() as db:
                active_strategies = (
                    db.query(StrategyConfig)
                    .filter(StrategyConfig.enabled == True)  # noqa: E712
                    .all()
                )

                for config in active_strategies:
                    strategy_name = config.strategy_name
                    try:
                        perf = tracker.get_performance(strategy_name, limit=50)

                        if perf.total_trades < MIN_TRADES_FOR_TUNING:
                            continue

                        if perf.win_rate < WIN_RATE_FLOOR:
                            changes = await self.evaluate_and_tune(strategy_name)
                            if changes:
                                tuned_count += 1
                        elif perf.win_rate > WIN_RATE_CEILING and perf.total_trades >= 20:
                            changes = await self.evaluate_and_tune(strategy_name)
                            if changes:
                                tuned_count += 1
                    except Exception:
                        logger.exception(f"[AGISelfTuner] Error reviewing {strategy_name}")

            if tuned_count > 0:
                logger.info(
                    f"[AGISelfTuner] Periodic review complete: tuned {tuned_count} strategies"
                )
            else:
                logger.debug(
                    "[AGISelfTuner] Periodic review complete: no tuning needed"
                )

        except Exception:
            record_pipeline_error("agi_self_tuner")
            logger.exception("[AGISelfTuner] Periodic review failed")

    # ------------------------------------------------------------------
    # Internal: rollback check
    # ------------------------------------------------------------------

    def _check_rollback(self, strategy_name: str, outcome: str) -> None:
        """Check if a previous parameter change should be rolled back.

        Monitors post-change performance. If win rate degrades by more than
        ROLLBACK_DEGRADATION over ROLLBACK_WINDOW trades, reverts via
        SafeParamTuner.
        """
        if strategy_name not in self._pending_rollbacks:
            return

        from backend.core.strategy_performance_tracker import get_performance_tracker
        from backend.core.safe_param_tuner import SafeParamTuner
        from backend.db.utils import get_db_session

        tracker = get_performance_tracker()
        state = self._pending_rollbacks[strategy_name]
        pre_win_rate = state["pre_change_win_rate"]
        trade_count_at_apply = state["trade_count_at_apply"]

        perf = tracker.get_performance(strategy_name, limit=50)
        trades_since = perf.total_trades - trade_count_at_apply

        if trades_since < ROLLBACK_WINDOW:
            return  # not enough data yet

        # Check degradation
        if pre_win_rate > 0 and perf.win_rate < pre_win_rate * (
            1.0 - ROLLBACK_DEGRADATION
        ):
            logger.warning(
                f"[AGISelfTuner] Performance degraded for {strategy_name}: "
                f"{pre_win_rate:.2f} -> {perf.win_rate:.2f}. Reverting."
            )
            try:
                with get_db_session() as db:
                    tuner = SafeParamTuner()
                    reverted = tuner.revert_if_degraded(strategy_name, db)
                    if reverted:
                        self._store_rollback_decision(
                            strategy_name, pre_win_rate, perf.win_rate
                        )
                        publish_event(
                            "agi_self_tune_rollback",
                            {
                                "strategy_name": strategy_name,
                                "pre_win_rate": pre_win_rate,
                                "post_win_rate": perf.win_rate,
                            },
                        )
            except Exception:
                logger.exception(f"[AGISelfTuner] Rollback failed for {strategy_name}")

        # Clear pending state regardless
        del self._pending_rollbacks[strategy_name]

    # ------------------------------------------------------------------
    # Internal: CognitiveCore storage
    # ------------------------------------------------------------------

    def _store_tuning_decision(
        self,
        strategy_name: str,
        direction: str,
        changes: Dict[str, Any],
        perf: Any,
    ) -> None:
        """Store tuning decision in CognitiveCore for future recall."""
        try:
            from backend.core.cognitive_core import create_cognitive_core

            core = create_cognitive_core(
                hub_url=getattr(settings, "BRAIN_API_URL", ""),
            )
            key = f"tune_{strategy_name}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}"
            value = {
                "strategy_name": strategy_name,
                "direction": direction,
                "changes": changes,
                "win_rate": perf.win_rate,
                "sharpe": perf.sharpe_ratio,
                "trade_count": perf.total_trades,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            core.remember(
                namespace="tuning_decisions",
                key=key,
                value=value,
                importance=0.7,
            )
        except Exception:
            logger.debug(
                "[AGISelfTuner] Failed to store tuning decision in CognitiveCore"
            )

    def _store_rollback_decision(
        self,
        strategy_name: str,
        pre_win_rate: float,
        post_win_rate: float,
    ) -> None:
        """Store rollback decision in CognitiveCore."""
        try:
            from backend.core.cognitive_core import create_cognitive_core

            core = create_cognitive_core(
                hub_url=getattr(settings, "BRAIN_API_URL", ""),
            )
            key = f"rollback_{strategy_name}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}"
            value = {
                "strategy_name": strategy_name,
                "pre_win_rate": pre_win_rate,
                "post_win_rate": post_win_rate,
                "reason": "performance_degradation",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            core.remember(
                namespace="tuning_decisions",
                key=key,
                value=value,
                importance=0.8,
            )
        except Exception:
            logger.debug(
                "[AGISelfTuner] Failed to store rollback decision in CognitiveCore"
            )
