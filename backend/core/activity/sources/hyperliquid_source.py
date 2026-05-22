"""Hyperliquid activity source — WebSocket fills + balance."""

from __future__ import annotations
import asyncio

from backend.core.activity.models import ActivityEvent
from backend.core.activity.sources.base import BaseActivitySource
from loguru import logger


class HyperliquidActivitySource(BaseActivitySource):
    """Real-time activity from Hyperliquid via WebSocket SDK."""

    def __init__(self, wallet_address: str, client):
        super().__init__(wallet_address, "hyperliquid")
        self._client = client
        self._seen_fills: set[str] = set()

    async def _run(self):
        try:
            # Subscribe to user fills (trade_open events)
            self._client.subscribe_user_fills(self._on_fill)
            # Subscribe to order updates
            self._client.subscribe_order_updates(self._on_order_update)
            # Balance events
            asyncio.create_task(self._balance_loop())

            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[hyperliquid] Activity source error: {e}")

    def _on_fill(self, fill: dict):
        """Called by Hyperliquid SDK WebSocket on fill."""
        fill_id = fill.get("orderId", "") or fill.get("id", "")
        if fill_id in self._seen_fills:
            return
        self._seen_fills.add(fill_id)

        event = ActivityEvent(
            source="hyperliquid",
            event_type="trade_open",
            wallet_address=self.wallet_address,
            platform="hyperliquid",
            amount=float(fill.get("size", fill.get("amount", 0))),
            token="USDC",
            tx_hash=fill.get("hash"),
            order_id=str(fill_id),
            side=fill.get("side", "").lower(),
            price=float(fill.get("price", 0)),
            fee=float(fill.get("fee", 0)),
            raw_data=fill,
        )
        asyncio.create_task(self._emit(event))

    def _on_order_update(self, update: dict):
        """Order fill/close events."""
        pass  # Hyperliquid handles fills via subscribe_user_fills

    async def _balance_loop(self):
        """Poll balance for delta detection."""
        last = None
        while self._running:
            try:
                bal = await self._client.get_balance()
                if last is not None:
                    delta = float(bal.get("total", 0)) - float(last.get("total", 0))
                    if abs(delta) > 0.01:
                        event = ActivityEvent(
                            source="hyperliquid",
                            event_type="deposit" if delta > 0 else "withdrawal",
                            wallet_address=self.wallet_address,
                            platform="hyperliquid",
                            amount=abs(delta),
                            token="USDC",
                            raw_data={"balance": bal},
                        )
                        await self._emit(event)
                last = bal
            except Exception as e:
                logger.warning(f"[hyperliquid] Balance loop error: {e}")
            await asyncio.sleep(5)