"""Auto-trader: routes high-confidence signals to immediate execution,
low-confidence signals to a manual approval queue."""
import asyncio

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from backend.config import settings
from backend.models.database import PendingApproval
from backend.monitoring.hft_metrics import record_signal
from backend.monitoring.metrics import increment_trade_execution

from loguru import logger
@dataclass
class ExecutionResult:
    executed: bool
    pending_approval: bool
    reason: str
    order_id: Optional[str] = None
    pending_id: Optional[int] = None


class AutoTrader:
    def __init__(self, risk_manager, clob_factory=None, wallet_router=None):
        self.risk = risk_manager
        self.clob_factory = clob_factory
        self.wallet_router = wallet_router

    async def execute_signal(
        self, signal: Dict[str, Any], bankroll: float, current_exposure: float, mode: str
    ) -> ExecutionResult:
        confidence = float(signal.get("confidence", 0.0))
        size = float(signal.get("size", 0.0))

        decision = self.risk.validate_trade(
            size=size,
            current_exposure=current_exposure,
            bankroll=bankroll,
            confidence=confidence,
            market_ticker=signal.get("market_ticker"),
            direction=signal.get("direction"),
        )
        if not decision.allowed:
            strategy = signal.get("strategy", "unknown")
            from backend.core.event_bus import publish_event
            publish_event(
                "trade_rejected",
                {
                    "strategy_name": strategy,
                    "market_ticker": signal.get("market_ticker"),
                    "reason": decision.reason,
                    "confidence": confidence,
                    "size": size,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
            record_signal(strategy=strategy, signal_type="rejected")
            return ExecutionResult(False, False, decision.reason)

        if confidence < settings.AUTO_APPROVE_MIN_CONFIDENCE:
            if settings.SIGNAL_APPROVAL_MODE != "manual":
                # In auto_approve or auto_deny mode, skip low-confidence signals instead of queuing
                strategy = signal.get("strategy", "unknown")
                record_signal(strategy=strategy, signal_type="rejected_low_confidence")
                return ExecutionResult(
                    False,
                    False,
                    f"skipped low-confidence signal (conf {confidence:.2f})",
                )
            pending_id = self._create_pending(signal, decision.adjusted_size)
            strategy = signal.get("strategy", "unknown")
            record_signal(strategy=strategy, signal_type="pending_approval")
            return ExecutionResult(
                False,
                True,
                f"queued for manual approval (conf {confidence:.2f})",
                pending_id=pending_id,
            )

        # High-confidence path
        strategy = signal.get("strategy", "unknown")
        if mode == "paper" or self.clob_factory is None:
            record_signal(strategy=strategy, signal_type="auto_approved")
            increment_trade_execution(strategy=strategy, result="paper")
            return ExecutionResult(
                True,
                False,
                "paper-mode auto-execute",
                order_id=f"paper-{datetime.now(timezone.utc).timestamp()}",
            )

        if self.wallet_router:
            try:
                child_orders = await asyncio.wait_for(
                    self.wallet_router.fan_out(
                        signal_size=decision.adjusted_size,
                        condition_id=signal.get("token_id"),
                        side=signal.get("side", "BUY"),
                        strategy_name=strategy,
                        bankroll=bankroll,
                    ),
                    timeout=30.0,
                )
                if not child_orders:
                    return ExecutionResult(False, False, "no active wallets for strategy")
                
                record_signal(strategy=strategy, signal_type="auto_approved_fanout")
                increment_trade_execution(strategy=strategy, result="live_fanout")
                return ExecutionResult(
                    True, False, f"live auto-execute fan-out to {len(child_orders)} wallets", order_id=f"fanout-{datetime.now(timezone.utc).timestamp()}"
                )
            except Exception as e:
                logger.exception("auto_trader live fan-out error")
                record_signal(strategy=strategy, signal_type="rejected_error")
                return ExecutionResult(False, False, f"fan-out error: {e}")

        try:
            async with self.clob_factory() as clob:
                result = await asyncio.wait_for(
                    clob.place_limit_order(
                        token_id=signal.get("token_id"),
                        side=signal.get("side", "BUY"),
                        price=float(signal.get("price", 0.0)),
                        size=decision.adjusted_size,
                    ),
                    timeout=30.0,
                )
            if result.success:
                record_signal(strategy=strategy, signal_type="auto_approved")
                increment_trade_execution(strategy=strategy, result="live")
                return ExecutionResult(
                    True, False, "live auto-execute", order_id=result.order_id
                )
            record_signal(strategy=strategy, signal_type="rejected_clob")
            return ExecutionResult(False, False, f"clob rejected: {result.error}")
        except Exception as e:
            logger.exception("auto_trader live execute error")
            record_signal(strategy=strategy, signal_type="rejected_error")
            return ExecutionResult(False, False, f"clob error: {e}")

    def _create_pending(self, signal: Dict[str, Any], size: float) -> Optional[int]:
        from backend.db.utils import get_db_session
        with get_db_session() as db:
            row = PendingApproval(
                market_id=str(signal.get("market_id", "unknown")),
                direction=str(signal.get("side", "BUY")),
                size=size,
                confidence=float(signal.get("confidence", 0.0)),
                signal_data=signal,
                status="pending",
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return row.id
