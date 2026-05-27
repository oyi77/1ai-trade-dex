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
        self._hl_last_balance = None

    async def _run(self):
        try:
            # Subscribe to user fills (trade_open events)
            self._client.subscribe_user_fills(self._on_fill)
            # Subscribe to order updates
            self._client.subscribe_order_updates(self._on_order_update)
            # Balance events — throttled polling
            self.create_subtask(self.throttled_loop(self._balance_cycle))

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
        self.create_subtask(self._emit(event))  # WS callback — create_subtask handles cancel tracking

    def _on_order_update(self, update: dict):
        """Order fill/close events."""
        pass  # Hyperliquid handles fills via subscribe_user_fills

    async def _balance_cycle(self):
        """Single iteration of balance polling for delta detection."""
        bal = await self._client.get_balance()
        if self._hl_last_balance is not None:
            result = self.detect_balance_delta(float(bal.total_equity), float(self._hl_last_balance.total_equity))
            if result:
                event_type, amount = result
                event = ActivityEvent(
                    source="hyperliquid",
                    event_type=event_type,
                    wallet_address=self.wallet_address,
                    platform="hyperliquid",
                    amount=amount,
                    token="USDC",
                    raw_data={"balance": bal},
                )
                await self._emit(event)
        self._hl_last_balance = bal
