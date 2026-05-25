"""Limitless activity source — REST polling for trade/fill events."""

from __future__ import annotations
import asyncio

from backend.core.activity.models import ActivityEvent
from backend.core.activity.sources.base import BaseActivitySource
from loguru import logger


class LimitlessActivitySource(BaseActivitySource):
    """Poll Limitless Exchange REST API for recent trades."""

    def __init__(self, wallet_address: str, limitless_client=None):
        super().__init__(wallet_address, "limitless")
        self._client = limitless_client
        self._seen_orders: set[str] = set()
        self._poll_interval = 10  # seconds

    async def _run(self):
        if not self._client:
            logger.warning("[limitless] No client provided, skipping activity source")
            return
        while self._running:
            try:
                await self._poll_trades()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[limitless] Activity poll error: {e}")
            await asyncio.sleep(self._poll_interval)

    async def _poll_trades(self):
        """Poll Limitless REST API for recent fills by wallet."""
        try:
            fills = await self._client.get_fills(self.wallet_address)
        except Exception as e:
            logger.warning(f"[limitless] get_fills error: {e}")
            return

        for fill in fills:
            order_id = fill.get("id", fill.get("orderId", ""))
            if order_id in self._seen_orders:
                continue
            self._seen_orders.add(order_id)

            side = fill.get("side", "").lower()
            amount = float(fill.get("size", fill.get("amount", 0)))
            price = float(fill.get("price", 0))
            fee = float(fill.get("fee", 0))
            pnl = float(fill.get("pnl", 0)) if fill.get("pnl") else None
            status = fill.get("status", "").lower()

            event_type = "trade_open"
            if status in ("settled", "closed", "resolved"):
                event_type = "trade_closed"

            event = ActivityEvent(
                source="limitless",
                event_type=event_type,
                wallet_address=self.wallet_address,
                platform="limitless",
                amount=amount,
                token="USDC",
                order_id=order_id,
                side=side,
                price=price,
                fee=fee,
                pnl=pnl,
                market_ticker=fill.get("marketTitle", fill.get("market", "")),
                raw_data=fill,
            )
            await self._emit(event)