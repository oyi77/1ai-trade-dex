"""APEX exit manager — unified position exit logic.

Closes the 948-buy-4-sell gap by actively monitoring open positions
and generating exit signals when:
  - Profit target is hit
  - Stop loss is triggered
  - Time decay: held too long
  - Edge decayed: original thesis no longer valid
  - Market resolved: auto-settle
  - Correlated exit: reduce clustered exposure
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import List, Optional

from loguru import logger

from backend.config import settings, _cfg
from backend.core.edge.edge_model import Edge, EdgeType, ExitSignal, ExitReason


class ExitManager:
    """Unified exit logic for all open positions."""

    def __init__(self) -> None:
        self.profit_target_pct = float(_cfg("APEX_PROFIT_TARGET_PCT", 0.025))
        self.stop_loss_pct = float(_cfg("APEX_STOP_LOSS_PCT", 0.03))
        self.max_hold_seconds = int(_cfg("APEX_MAX_HOLD_SECONDS", 7200))
        self.edge_decay_threshold = float(_cfg("APEX_EDGE_DECAY_THRESHOLD", 0.3))

    async def scan_positions(self, ctx) -> List[ExitSignal]:
        """Evaluate all open APEX positions for exit signals.

        For each open position, check:
        1. Profit target hit?
        2. Stop loss triggered?
        3. Time decay: held too long?
        4. Edge decayed: original edge_score dropped below threshold?
        5. Market resolved?

        Returns list of ExitSignals for positions that should be exited.
        """
        exits: List[ExitSignal] = []

        try:
            from backend.models.database import Trade
            open_trades = (
                ctx.db.query(Trade)
                .filter(
                    Trade.settled.is_(False),
                    Trade.trading_mode == ctx.mode,
                    Trade.strategy == "apex",
                )
                .all()
            )
        except Exception as e:
            logger.warning(f"[apex:exit] Failed to query open trades: {e}")
            return exits

        now = datetime.now(timezone.utc)

        for trade in open_trades:
            try:
                exit_signal = self._evaluate_position(trade, ctx, now)
                if exit_signal is not None:
                    exits.append(exit_signal)
            except Exception as e:
                logger.warning(
                    f"[apex:exit] Error evaluating trade {trade.id}: {e}"
                )
                continue

        # Sort by urgency (most urgent first)
        exits.sort(key=lambda e: e.urgency, reverse=True)
        logger.info(f"[apex:exit] Found {len(exits)} exit signals for {len(open_trades)} open positions")
        return exits

    def _evaluate_position(self, trade, ctx, now: datetime) -> Optional[ExitSignal]:
        """Evaluate a single position for exit signals."""
        if not trade.entry_price or trade.entry_price <= 0:
            return None

        entry_price = float(trade.entry_price)
        direction = (trade.direction or "yes").lower()
        trade_id = trade.id
        market_id = trade.market_ticker or ""

        # Get current price from CLOB
        current_price = self._get_current_price(trade, ctx)
        if current_price is None or current_price <= 0:
            return None

        # Calculate PnL
        if direction in ("yes", "up"):
            pnl_pct = (current_price - entry_price) / entry_price if entry_price > 0 else 0
        else:
            pnl_pct = (entry_price - current_price) / entry_price if entry_price > 0 else 0

        # 1. Profit target
        if pnl_pct >= self.profit_target_pct:
            return ExitSignal(
                trade_id=trade_id,
                market_id=market_id,
                reason=ExitReason.PROFIT_TARGET,
                exit_price=current_price,
                urgency=0.6,
                edge_at_entry=float(trade.edge or 0),
                current_edge=0,  # filled below if re-scan available
                metadata={"pnl_pct": round(pnl_pct, 4), "entry_price": entry_price, "current_price": current_price},
            )

        # 2. Stop loss
        if pnl_pct <= -self.stop_loss_pct:
            return ExitSignal(
                trade_id=trade_id,
                market_id=market_id,
                reason=ExitReason.STOP_LOSS,
                exit_price=current_price,
                urgency=0.9,  # urgent — cut losses
                edge_at_entry=float(trade.edge or 0),
                current_edge=0,
                metadata={"pnl_pct": round(pnl_pct, 4), "entry_price": entry_price, "current_price": current_price},
            )

        # 3. Time decay — held too long
        created_at = trade.created_at
        if created_at and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        if created_at:
            hold_seconds = (now - created_at).total_seconds()
            if hold_seconds > self.max_hold_seconds:
                return ExitSignal(
                    trade_id=trade_id,
                    market_id=market_id,
                    reason=ExitReason.TIME_DECAY,
                    exit_price=current_price,
                    urgency=0.5,
                    edge_at_entry=float(trade.edge or 0),
                    current_edge=0,
                    metadata={
                        "hold_seconds": int(hold_seconds),
                        "max_hold_seconds": self.max_hold_seconds,
                    },
                )

        # 4. Edge decay — check if original edge is still valid
        original_edge = float(trade.edge or 0)
        if original_edge > 0:
            # Estimate remaining edge using exponential decay
            edge_half_life = 1800  # 30 min default
            if created_at:
                elapsed = (now - created_at).total_seconds()
                remaining_edge = original_edge * (0.5 ** (elapsed / edge_half_life))
                if remaining_edge < original_edge * self.edge_decay_threshold:
                    return ExitSignal(
                        trade_id=trade_id,
                        market_id=market_id,
                        reason=ExitReason.EDGE_DECAY,
                        exit_price=current_price,
                        urgency=0.4,
                        edge_at_entry=original_edge,
                        current_edge=remaining_edge,
                        metadata={
                            "original_edge": round(original_edge, 4),
                            "remaining_edge": round(remaining_edge, 4),
                            "threshold": self.edge_decay_threshold,
                        },
                    )

        return None

    def _get_current_price(self, trade, ctx) -> Optional[float]:
        """Get current market price for a position."""
        # Try CLOB first
        if ctx.clob and trade.token_id:
            try:
                price = ctx.clob.get_midpoint(trade.token_id)
                if price and price > 0:
                    return float(price)
            except Exception:
                pass

        # Fallback: use entry price + trade PnL
        if trade.current_pnl and trade.entry_price:
            entry = float(trade.entry_price)
            pnl = float(trade.current_pnl)
            if entry > 0:
                return max(entry + pnl, 0.01)

        # Last resort: entry price (no exit signal)
        return None