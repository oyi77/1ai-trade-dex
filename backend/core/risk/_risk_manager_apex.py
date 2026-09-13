"""RiskManager apex mixin — regime multiplier, category breaker, APEX signal."""

from __future__ import annotations

import json
import time
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from sqlalchemy import func, or_

from loguru import logger

from backend.config import settings
from backend.db.utils import get_db_session
from backend.models.database import Trade, BotState, for_update
from backend.monitoring.hft_metrics import record_signal, db_query_duration
from backend.monitoring.metrics import increment_risk_rejection
from backend.core.risk.correlation_monitor import CorrelationMonitor

from backend.core.risk._risk_manager_types import (
    RiskDecision,
    EdgeFilterError,
    DrawdownStatus,
    IMMUTABLE_SAFETY_RULES,
    _not_backfill_settlement_source,
)



class RiskManagerApexMixin:
    """Mixin — method implementations live on RiskManager."""

    def _get_regime_multiplier(self, strategy_name: Optional[str] = None) -> float:
        try:
            from backend.application.meta.regime_router import RegimeConfidenceRouter

            router = RegimeConfidenceRouter()
            return router.get_multiplier(strategy_name or "")
        except ImportError:
            # Fallback to default multiplier if regime router not available
            return 1.0

    def _check_category_circuit_breaker(
        self, category: str, db, mode: str
    ) -> Optional[str]:
        """G-17: Check if a market category has exceeded consecutive loss limit.

        If a category has > N consecutive losses, pause trading in that category
        for CATEGORY_COOLDOWN_MINUTES (default 120).

        Returns a rejection reason string if the category is paused, None otherwise.
        """
        try:
            limit = int(getattr(self.s, "CATEGORY_CONSECUTIVE_LOSS_LIMIT", 3) or 3)
            cooldown_min = int(getattr(self.s, "CATEGORY_COOLDOWN_MINUTES", 120) or 120)

            now = datetime.now(timezone.utc)
            # Look at recent trades in this category
            recent_trades = (
                db.query(Trade)
                .filter(
                    Trade.category == category,
                    Trade.settled.is_(True),
                    Trade.trading_mode == mode,
                    Trade.result.in_(["win", "loss"]),
                )
                .order_by(Trade.settlement_time.desc())
                .limit(limit)
                .all()
            )

            if len(recent_trades) < limit:
                return None

            # Check if all recent trades are losses
            all_losses = all(t.result == "loss" for t in recent_trades)
            if not all_losses:
                return None

            # Check if cooldown has elapsed since the most recent loss
            latest_loss_time = recent_trades[0].settlement_time
            if latest_loss_time and latest_loss_time.tzinfo is None:
                latest_loss_time = latest_loss_time.replace(tzinfo=timezone.utc)

            cooldown_end = latest_loss_time + timedelta(minutes=cooldown_min)
            if now < cooldown_end:
                remaining = (cooldown_end - now).total_seconds() / 60
                logger.info(
                    "[risk_manager] Category circuit breaker: {} has {} consecutive losses, "
                    "paused for {:.0f} more minutes",
                    category,
                    limit,
                    remaining,
                )
                return (
                    f"category '{category}' circuit breaker: "
                    f"{limit} consecutive losses, paused {remaining:.0f}min"
                )

            return None

        except Exception as e:
            logger.opt(exception=True).error(
                "[risk_manager._check_category_circuit_breaker] {}: {}",
                type(e).__name__,
                e,
            )

    def evaluate_apex_signal(self, signal, ctx) -> RiskDecision:
        """APEX-specific pre-trade risk evaluation.

        Checks edge freshness, confidence gate, position limits,
        correlation, drawdown, and bankroll sizing.
        """
        from backend.core.edge.edge_model import Signal

        if not isinstance(signal, Signal):
            return RiskDecision(
                allowed=False,
                reason=f"apex: invalid signal type {type(signal)}",
                adjusted_size=0.0,
            )

        # 1. Edge freshness — reject expired edges
        for edge in signal.source_edges:
            if edge.is_expired:
                return RiskDecision(
                    allowed=False,
                    reason=f"apex: edge expired for {signal.market_id}",
                    adjusted_size=0.0,
                )

        # 2. Confidence gate
        min_confidence = float(getattr(self.s, "APEX_MIN_CONFIDENCE", 0.3))
        if signal.confidence < min_confidence:
            return RiskDecision(
                allowed=False,
                reason=f"apex: confidence {signal.confidence:.2f} < {min_confidence}",
                adjusted_size=0.0,
            )

        # 3. Position limits
        max_concurrent = int(getattr(self.s, "APEX_MAX_CONCURRENT", 5))
        try:
            from backend.models.database import Trade
            open_count = (
                ctx.db.query(Trade)
                .filter(
                    Trade.settled.is_(False),
                    Trade.trading_mode == ctx.mode,
                    Trade.strategy == "apex",
                )
                .count()
            )
            if open_count >= max_concurrent:
                return RiskDecision(
                    allowed=False,
                    reason=f"apex: {open_count} positions >= max {max_concurrent}",
                    adjusted_size=0.0,
                )
        except Exception:
            logger.warning("[apex:risk] Could not check concurrent positions, allowing through")

        # 4. Drawdown check
        mode = ctx.mode or getattr(self.s, "TRADING_MODE", "paper")
        if self._daily_loss_exceeded(db=ctx.db, mode=mode):
            return RiskDecision(
                allowed=False,
                reason="apex: daily loss limit exceeded",
                adjusted_size=0.0,
            )

        # 5. Bankroll sizing — adjust size based on current bankroll
        bankroll = self._get_bankroll(ctx.db, mode)
        max_pct = float(getattr(self.s, "APEX_BANKROLL_PCT", 0.08))
        adjusted_size = min(signal.size_usd, bankroll * max_pct)
        adjusted_size = max(adjusted_size, float(getattr(self.s, "MIN_ORDER_USDC", 1.0)))

        # 6. Correlation check
        try:
            category = signal.metadata.get("category", "unknown")
            check_result = self.check_concentration(
                market_ticker=signal.market_id,
                category=category,
                db=ctx.db,
                mode=mode,
                size=adjusted_size,
                bankroll=bankroll,
            )
            if check_result:
                logger.warning(f"[apex:risk] Concentration check: {check_result}")
                return RiskDecision(
                    allowed=False,
                    reason=f"apex: concentration limit — {check_result}",
                    adjusted_size=0.0,
                )
        except Exception:
            logger.warning("[apex:risk] Could not check concentration limits, allowing through")

        return RiskDecision(
            allowed=True,
            reason="apex: all risk checks passed",
            adjusted_size=adjusted_size,
        )
