"""Paper trading activity source — emits events from paper trade execution."""

from __future__ import annotations
import asyncio

from backend.core.activity.models import ActivityEvent
from backend.core.activity.sources.base import BaseActivitySource
from loguru import logger


class PaperActivitySource(BaseActivitySource):
    """Captures paper trading events from the scheduler/orchestrator.

    Instead of polling an external API, this source subscribes to internal
    paper trade events emitted by the trading engine. Paper trades are
    recorded via ActivityTracker just like live trades.
    """

    def __init__(self, wallet_address: str = "paper"):
        super().__init__(wallet_address, "paper")

    async def _run(self):
        """Paper source is event-driven — no polling loop needed.

        Paper trades are emitted directly by the trading engine via
        tracker.emit() rather than through this source's _run() loop.
        This method just keeps the source alive for lifecycle management.
        """
        logger.info("[paper] Activity source started (event-driven, no polling)")
        while self._running:
            await asyncio.sleep(60)  # Heartbeat — no REST/WS polling needed

    def create_trade_event(
        self,
        event_type: str,
        amount: float,
        side: str,
        price: float,
        market_ticker: str,
        order_id: str = "",
        fee: float = 0.0,
        pnl: float | None = None,
        strategy: str = "",
    ) -> ActivityEvent:
        """Factory method for creating paper trade events.

        Called by the paper trading engine to create ActivityEvent instances
        that are then emitted through the tracker.
        """
        return ActivityEvent(
            source="paper",
            event_type=event_type,
            wallet_address=self.wallet_address,
            platform="paper",
            amount=amount,
            token="USDC",
            order_id=order_id,
            side=side,
            price=price,
            fee=fee,
            pnl=pnl,
            market_ticker=market_ticker,
            raw_data={"strategy": strategy, "mode": "paper"},
        )