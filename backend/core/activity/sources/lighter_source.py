"""Lighter activity source — WebSocket balance + fills."""

from __future__ import annotations
import asyncio

from backend.core.activity.models import ActivityEvent
from backend.core.activity.sources.base import BaseActivitySource
from loguru import logger


class LighterActivitySource(BaseActivitySource):
    """Real-time activity from Lighter ZK DEX via WebSocket."""

    def __init__(self, wallet_address: str, ws_client):
        super().__init__(wallet_address, "lighter")
        self._ws = ws_client
        self._seen_orders: set[str] = set()

    async def _run(self):
        try:
            # Subscribe to account updates (balance + fills)
            self._ws.subscribe("account", {"address": self.wallet_address})
            asyncio.create_task(self._ws_loop())
            asyncio.create_task(self._balance_loop())

            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[lighter] Activity source error: {e}")

    async def _ws_loop(self):
        """Parse WebSocket account messages for fills."""
        while self._running:
            try:
                msg = await self._ws.recv()
                if msg.get("type") == "fill":
                    fill = msg.get("data", {})
                    order_id = fill.get("id", fill.get("orderId", ""))
                    if order_id in self._seen_orders:
                        continue
                    self._seen_orders.add(order_id)

                    event = ActivityEvent(
                        source="lighter",
                        event_type="trade_open",
                        wallet_address=self.wallet_address,
                        platform="lighter",
                        amount=float(fill.get("size", fill.get("amount", 0))),
                        token="USDC",
                        order_id=order_id,
                        side=fill.get("side", "").lower(),
                        price=float(fill.get("price", 0)),
                        fee=float(fill.get("fee", 0)),
                        raw_data=fill,
                    )
                    await self._emit(event)
            except Exception as e:
                logger.warning(f"[lighter] WS loop error: {e}")
            await asyncio.sleep(0.1)

    async def _balance_loop(self):
        """Poll balance for deposit/withdrawal detection."""
        last = None
        while self._running:
            try:
                bal = await self._ws.get_balance(self.wallet_address)
                if last is not None and abs(float(bal) - float(last)) > 0.01:
                    delta = float(bal) - float(last)
                    await self._emit(ActivityEvent(
                        source="lighter",
                        event_type="deposit" if delta > 0 else "withdrawal",
                        wallet_address=self.wallet_address,
                        platform="lighter",
                        amount=abs(delta),
                        token="USDC",
                    ))
                last = bal
            except Exception as e:
                logger.warning(f"[lighter] Balance loop error: {e}")
            await asyncio.sleep(5)
