"""Pair Cost Arbitrage Monitor - Phase F Gap G9

Monitors orderbook updates for arbitrage opportunities between YES/NO markets.
Fires when pair cost allows risk-free profit after fees.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Optional

from backend.config import settings
from backend.core.event_bus import publish_event
from backend.infrastructure.market_stream.orderbook_router import OrderbookUpdate
from backend.models.database import SessionLocal, Trade
from sqlalchemy import and_

logger = logging.getLogger("trading_bot.arbitrage")


@dataclass
class ArbitrageOpportunity:
    market_id: str
    best_ask_yes: float
    best_ask_no: float
    pair_cost: float
    spread_pct: float
    timestamp: datetime


class PairCostMonitor:
    """Monitors orderbook for YES/NO arbitrage opportunities.
    
    Strategy: Buy YES + Buy NO simultaneously when pair_cost < 1.00 - 2*fees.
    This creates a risk-free position that profits if either outcome wins.
    """

    _last_attempt: Dict[str, datetime] = defaultdict(lambda: datetime.min)
    _RATE_LIMIT_SECONDS = 10

    def __init__(self):
        self.circuit_breaker = None  # Will be set by scheduler

    async def on_orderbook_update(self, update: OrderbookUpdate) -> None:
        """Handle orderbook update and check for arbitrage opportunities."""
        
        if not settings.ENABLE_PAIR_COST_ARB:
            return
        
        market_id = update.market_id
        
        # Rate limiting: max 1 attempt per market per 10 seconds
        last_attempt = self._last_attempt.get(market_id, datetime.min)
        if datetime.now() - last_attempt < timedelta(seconds=self._RATE_LIMIT_SECONDS):
            return
        
        # Idempotency check: skip if unsettled trade exists for this market
        if self._has_unsettled_trade(market_id):
            logger.debug(f"Skipping arb check for {market_id}: unsettled trade exists")
            return
        
        self._last_attempt[market_id] = datetime.now()
        
        # Extract best ask prices
        best_ask_yes = self._get_best_ask_price(update.asks_yes)
        best_ask_no = self._get_best_ask_price(update.asks_no)
        
        if best_ask_yes <= 0 or best_ask_no <= 0:
            return
        
        # Calculate pair cost and check for arbitrage
        pair_cost = best_ask_yes + best_ask_no
        taker_fee_rate = getattr(settings, "TAKER_FEE_RATE", 0.02)
        
        spread_pct = 1.00 - pair_cost - (2 * taker_fee_rate)
        
        if spread_pct > settings.MIN_ARB_SPREAD:
            logger.info(
                f"Arbitrage opportunity detected: {market_id} | "
                f"YES={best_ask_yes:.4f} NO={best_ask_no:.4f} | "
                f"PairCost={pair_cost:.4f} Spread={spread_pct:.4f}"
            )
            
            # Publish event for downstream processing
            await self._publish_arbitrage_event(
                market_id=market_id,
                best_ask_yes=best_ask_yes,
                best_ask_no=best_ask_no,
                pair_cost=pair_cost,
                spread_pct=spread_pct
            )
            
            # Fire simultaneous orders (placeholder - just log in this phase)
            await self._fire_simultaneous_maker_orders(
                market_id=market_id,
                best_ask_yes=best_ask_yes,
                best_ask_no=best_ask_no
            )

    def _has_unsettled_trade(self, market_id: str) -> bool:
        """Check if there are unsettled trades for this market."""
        with SessionLocal() as session:
            unsettled_exists = session.query(
                Trade.query.filter(
                    and_(
                        Trade.market_id == market_id,
                        Trade.settled_at.is_(None)
                    )
                ).exists()
            ).scalar()
            return unsettled_exists

    @staticmethod
    def _get_best_ask_price(asks: list) -> float:
        """Extract best (lowest) ask price from orderbook."""
        if not asks:
            return 0.0
        return float(asks[0]['price'])

    async def _publish_arbitrage_event(self, market_id: str, best_ask_yes: float,
                                      best_ask_no: float, pair_cost: float,
                                      spread_pct: float) -> None:
        """Publish arbitrage opportunity event."""
        event_data = {
            "market_id": market_id,
            "best_ask_yes": best_ask_yes,
            "best_ask_no": best_ask_no,
            "pair_cost": pair_cost,
            "spread_pct": spread_pct,
            "timestamp": datetime.now().isoformat()
        }
        await publish_event("arbitrage_opportunity_detected", event_data)

    async def _fire_simultaneous_maker_orders(self, market_id: str,
                                              best_ask_yes: float,
                                              best_ask_no: float) -> None:
        """Placeholder for simultaneous order execution.
        
        In this phase, we only log the opportunity. Actual execution
        will be implemented in a follow-up task.
        """
        logger.warning(
            f"Would execute simultaneous maker orders for {market_id}: "
            f"YES@{best_ask_yes}, NO@{best_ask_no} "
            f"(not executing in this phase)"
        )
        # TODO: Actual order execution will be implemented in Phase G
