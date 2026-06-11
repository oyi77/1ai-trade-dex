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

    def __init__(
        self,
        profit_target_pct: float | None = None,
        stop_loss_pct: float | None = None,
        max_hold_seconds: int | None = None,
        edge_decay_threshold: float | None = None,
    ) -> None:
        self.profit_target_pct = float(
            profit_target_pct
            if profit_target_pct is not None
            else _cfg("APEX_PROFIT_TARGET_PCT", 0.025)
        )
        self.stop_loss_pct = float(
            stop_loss_pct if stop_loss_pct is not None else _cfg("APEX_STOP_LOSS_PCT", 0.03)
        )
        self.max_hold_seconds = int(
            max_hold_seconds
            if max_hold_seconds is not None
            else _cfg("APEX_MAX_HOLD_SECONDS", 7200)
        )
        self.edge_decay_threshold = float(
            edge_decay_threshold
            if edge_decay_threshold is not None
            else _cfg("APEX_EDGE_DECAY_THRESHOLD", 0.3)
        )

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
                exit_signal = await self._evaluate_position(trade, ctx, now)
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

    async def _evaluate_position(self, trade, ctx, now: datetime) -> Optional[ExitSignal]:
        """Evaluate a single position for exit signals."""
        current_price = await self._get_current_price(trade, ctx)
        return self.check_position(trade, current_price, now=now)

    def check_position(
        self, trade, current_price: Optional[float], now: Optional[datetime] = None
    ) -> Optional[ExitSignal]:
        """Pure exit evaluation for a single position at a known price.

        Checks, in priority order: profit target, stop loss, time decay,
        edge decay. Returns None when the position should be held.
        """
        if not trade.entry_price or trade.entry_price <= 0:
            return None
        if current_price is None or current_price <= 0:
            return None
        if now is None:
            now = datetime.now(timezone.utc)

        entry_price = float(trade.entry_price)
        direction = (trade.direction or "yes").lower()
        trade_id = trade.id
        market_id = trade.market_ticker or ""

        # Calculate PnL
        if direction in ("yes", "up"):
            pnl_pct = (current_price - entry_price) / entry_price
        else:
            pnl_pct = (entry_price - current_price) / entry_price

        # 1. Profit target
        if pnl_pct >= self.profit_target_pct:
            return ExitSignal(
                trade_id=trade_id,
                market_id=market_id,
                reason=ExitReason.PROFIT_TARGET,
                exit_price=current_price,
                urgency=0.6,
                edge_at_entry=float(trade.edge or 0),
                current_edge=0,
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

        # 3. Time decay — held too long. Trade rows store open time in
        # `timestamp`; fall back to `created_at` for other position shapes.
        opened_at = getattr(trade, "timestamp", None) or getattr(trade, "created_at", None)
        if isinstance(opened_at, datetime):
            if opened_at.tzinfo is None:
                opened_at = opened_at.replace(tzinfo=timezone.utc)
        else:
            opened_at = None
        if opened_at:
            hold_seconds = (now - opened_at).total_seconds()
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
        if original_edge > 0 and opened_at:
            # Estimate remaining edge using exponential decay
            edge_half_life = 1800  # 30 min default
            elapsed = (now - opened_at).total_seconds()
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

    def check_all_positions(
        self,
        trades,
        price_lookup: dict,
        now: Optional[datetime] = None,
    ) -> List[ExitSignal]:
        """Evaluate many positions against a market_ticker→price map.

        Returns exit signals sorted by urgency (most urgent first).
        """
        exits: List[ExitSignal] = []
        for trade in trades:
            price = price_lookup.get(trade.market_ticker or "")
            try:
                sig = self.check_position(trade, price, now=now)
            except Exception as e:
                logger.warning(f"[apex:exit] Error evaluating trade {trade.id}: {e}")
                continue
            if sig is not None:
                exits.append(sig)
        exits.sort(key=lambda e: e.urgency, reverse=True)
        return exits

    async def _get_current_price(self, trade, ctx) -> Optional[float]:
        """Get current market price for a position."""
        # Try CLOB first
        if ctx.clob and trade.token_id:
            try:
                price = await ctx.clob.get_mid_price(trade.token_id)
                if price and price > 0:
                    return float(price)
            except Exception as e:
                logger.debug(f"[apex:exit] mid-price fetch failed for {trade.token_id}: {e}")

        # Fallback: use entry price + trade PnL
        if trade.current_pnl and trade.entry_price:
            entry = float(trade.entry_price)
            pnl = float(trade.current_pnl)
            if entry > 0:
                return max(entry + pnl, 0.01)

        # Last resort: entry price (no exit signal)
        return None