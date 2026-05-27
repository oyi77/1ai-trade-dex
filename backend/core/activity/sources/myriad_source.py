"""Myriad activity source — REST polling for fills and position changes."""

from __future__ import annotations
import asyncio
from decimal import Decimal

from backend.core.activity.models import ActivityEvent
from backend.core.activity.sources.base import BaseActivitySource
from loguru import logger


class MyriadActivitySource(BaseActivitySource):
    """Poll Myriad Markets API for trade fills and position changes."""

    def __init__(self, wallet_address: str, myriad_client=None):
        super().__init__(wallet_address, "myriad")
        self._client = myriad_client
        self._seen_orders: set[str] = set()
        self._last_position_ids: set[str] = set()
        self._myriad_last_balance: float | None = None

    async def _run(self):
        if not self._client:
            logger.warning("[myriad] No client provided, skipping activity source")
            return
        try:
            self.create_subtask(self.throttled_loop(self._fills_cycle))
            self.create_subtask(self.throttled_loop(self._positions_cycle))
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[myriad] Activity source error: {e}")

    async def _fills_cycle(self):
        """Single iteration of fills polling."""
        fills = await self._client.get_fills(wallet_address=self.wallet_address, limit=100)
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
            market = fill.get("market_id", fill.get("market", fill.get("marketTitle", "")))
            status = fill.get("status", "").lower()
            is_open = status not in ("settled", "closed", "resolved")

            event = ActivityEvent(
                source="myriad",
                event_type="trade_open" if is_open else "trade_closed",
                wallet_address=self.wallet_address,
                platform="myriad",
                amount=amount,
                token="USDC",
                order_id=order_id,
                side=side,
                price=price,
                fee=fee,
                pnl=pnl,
                market_ticker=market,
                raw_data=fill,
            )
            await self._emit(event)

    async def _positions_cycle(self):
        """Single iteration of positions polling + balance delta detection."""
        # Position diff detection
        positions = await self._client.get_positions()
        current_ids = set()
        for pos in (positions or []):
            pid = pos.get("id", pos.get("position_id", ""))
            current_ids.add(pid)
            if pid and pid not in self._last_position_ids:
                # New position opened
                event = ActivityEvent(
                    source="myriad",
                    event_type="trade_open",
                    wallet_address=self.wallet_address,
                    platform="myriad",
                    amount=float(pos.get("size", pos.get("amount", 0))),
                    token="USDC",
                    side=pos.get("side", "").lower(),
                    market_ticker=pos.get("market_id", pos.get("market", "")),
                    raw_data=pos,
                )
                await self._emit(event)

        # Closed: in last but not current
        for pid in self._last_position_ids:
            if pid and pid not in current_ids:
                await self._emit(ActivityEvent(
                    source="myriad",
                    event_type="trade_closed",
                    wallet_address=self.wallet_address,
                    platform="myriad",
                    amount=0.0,  # Size unknown for closed position
                    token="USDC",
                ))

        self._last_position_ids = current_ids

        # Balance delta
        balance = await self._client.get_balance()
        current_balance = float(balance) if isinstance(balance, (int, float, Decimal)) else float(str(balance))
        if self._myriad_last_balance is not None:
            result = self.detect_balance_delta(current_balance, self._myriad_last_balance)
            if not result:
                self._myriad_last_balance = current_balance
                return
            await self._emit(ActivityEvent(
                source="myriad",
                event_type=result[0],
                wallet_address=self.wallet_address,
                platform="myriad",
                amount=result[1],
                token="USDC",
            ))
        self._myriad_last_balance = current_balance
