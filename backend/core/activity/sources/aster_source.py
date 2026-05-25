"""Aster activity source — WebSocket fills + balance + positions."""

from __future__ import annotations
import asyncio
from datetime import datetime, timezone

from backend.core.activity.models import ActivityEvent
from backend.core.activity.sources.base import BaseActivitySource
from loguru import logger


class AsterActivitySource(BaseActivitySource):
    """Real-time activity from Aster DEX via WebSocket."""

    def __init__(self, wallet_address: str, client):
        super().__init__(wallet_address, "aster")
        self._client = client
        self._seen_orders: set[str] = set()

    async def _run(self):
        """Subscribe to fills + balance updates via Aster WebSocket."""
        try:
            # Balance stream
            self.create_subtask(self._balance_loop())
            # Fills stream
            self.create_subtask(self._fills_loop())
            # Positions stream
            self.create_subtask(self._positions_loop())

            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[aster] Activity source error: {e}")

    async def _balance_loop(self):
        """Balance delta detection → deposit/withdrawal events."""
        last_balance = None
        while self._running:
            try:
                bal = await self._client.watch_balance()
                if last_balance is not None:
                    result = self.detect_balance_delta(float(bal.get("total", 0)), float(last_balance.get("total", 0)))
                    if result:
                        event_type, amount = result
                        event = ActivityEvent(
                            source="aster",
                            event_type=event_type,
                            wallet_address=self.wallet_address,
                            platform="aster",
                            amount=amount,
                            token="USDC",
                            raw_data=bal,
                        )
                        await self._emit(event)
                last_balance = bal
            except Exception as e:
                logger.warning(f"[aster] Balance loop error: {e}")
            await asyncio.sleep(5)

    async def _fills_loop(self):
        """Trade fill events → trade_open / trade_closed."""
        while self._running:
            try:
                fills = await self._client.get_fills()
                for fill in fills:
                    order_id = fill.get("order_id", fill.get("id", ""))
                    if order_id in self._seen_orders:
                        continue
                    self._seen_orders.add(order_id)
                    event = ActivityEvent(
                        source="aster",
                        event_type="trade_open",
                        wallet_address=self.wallet_address,
                        platform="aster",
                        amount=float(fill.get("size", fill.get("amount", 0))),
                        token="USDC",
                        tx_hash=fill.get("tx_hash"),
                        order_id=order_id,
                        side=fill.get("side", "").lower(),
                        price=float(fill.get("price", 0)),
                        fee=float(fill.get("fee", 0)),
                        raw_data=fill,
                    )
                    await self._emit(event)
            except Exception as e:
                logger.warning(f"[aster] Fills loop error: {e}")
            await asyncio.sleep(3)

    async def _positions_loop(self):
        """Position close detection → trade_closed events."""
        last_positions = {}
        while self._running:
            try:
                positions = await self._client.watch_positions()
                for pos in positions:
                    market_id = pos.get("symbol", "")
                    size = float(pos.get("size", 0))
                    prev = last_positions.get(market_id, {}).get("size", 0)
                    if prev != 0 and size == 0:
                        # Position closed
                        pnl = float(pos.get("realized_pnl", pos.get("pnl", 0)))
                        event = ActivityEvent(
                            source="aster",
                            event_type="trade_closed",
                            wallet_address=self.wallet_address,
                            platform="aster",
                            amount=abs(float(prev)),
                            token="USDC",
                            pnl=pnl,
                            raw_data=pos,
                        )
                        await self._emit(event)
                    last_positions[market_id] = pos
            except Exception as e:
                logger.warning(f"[aster] Positions loop error: {e}")
            await asyncio.sleep(5)