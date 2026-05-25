"""Kalshi activity source — REST polling for fills and position changes."""

from __future__ import annotations
import asyncio

from backend.core.activity.models import ActivityEvent
from backend.core.activity.sources.base import BaseActivitySource
from loguru import logger


class KalshiActivitySource(BaseActivitySource):
    """Poll Kalshi API for trade fills and position changes."""

    def __init__(self, wallet_address: str, kalshi_client=None):
        super().__init__(wallet_address, "kalshi")
        self._client = kalshi_client
        self._seen_orders: set[str] = set()
        self._last_positions: dict[str, dict] = {}  # market_ticker -> position dict
        self._fills_interval = 10  # seconds
        self._positions_interval = 15  # seconds

    async def _run(self):
        if not self._client:
            logger.warning("[kalshi] No client provided, skipping activity source")
            return
        try:
            self.create_subtask(self._fills_loop())
            self.create_subtask(self._positions_loop())
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("[kalshi] Activity source error: {e}")

    async def _fills_loop(self):
        """Poll Kalshi fills endpoint every 10s."""
        while self._running:
            try:
                fills = await self._client.get_fills(limit=100)
                for fill in fills:
                    order_id = fill.get("order_id", fill.get("id", ""))
                    if order_id in self._seen_orders:
                        continue
                    self._seen_orders.add(order_id)

                    side = fill.get("side", fill.get("action", "")).lower()
                    amount = float(fill.get("count", fill.get("size", 0)))
                    price = float(fill.get("price", fill.get("yes_price", 0)))
                    fee = float(fill.get("fee", 0))
                    market_ticker = fill.get("market_ticker", fill.get("ticker", ""))

                    event = ActivityEvent(
                        source="kalshi",
                        event_type="trade_open",
                        wallet_address=self.wallet_address,
                        platform="kalshi",
                        amount=amount,
                        token="USDC",
                        order_id=order_id,
                        side=side,
                        price=price,
                        fee=fee,
                        market_ticker=market_ticker,
                        raw_data=fill,
                    )
                    await self._emit(event)
            except Exception as e:
                logger.warning("[kalshi] Fills loop error: {e}")
            await asyncio.sleep(self._fills_interval)

    async def _positions_loop(self):
        """Poll positions for open/close detection + deposit/withdrawal via balance delta."""
        last_balance = None
        while self._running:
            try:
                # Position change detection
                positions = await self._client.get_positions()
                current_positions = {}
                for pos in positions:
                    ticker = pos.get("ticker", pos.get("market_ticker", ""))
                    current_positions[ticker] = pos

                # Detect closed positions (were in last snapshot, not in current)
                for ticker in list(self._last_positions.keys()):
                    if ticker not in current_positions:
                        old_pos = self._last_positions[ticker]
                        event = ActivityEvent(
                            source="kalshi",
                            event_type="trade_closed",
                            wallet_address=self.wallet_address,
                            platform="kalshi",
                            amount=float(old_pos.get("count", old_pos.get("size", 0))),
                            token="USDC",
                            market_ticker=ticker,
                            pnl=float(old_pos.get("pnl", 0)),
                            raw_data=old_pos,
                        )
                        await self._emit(event)

                self._last_positions = current_positions

                # Balance delta detection for deposits/withdrawals
                balance_resp = await self._client.get_balance()
                current_balance = float(balance_resp.get("balance", balance_resp.get("value", 0)))
                if last_balance is not None:
                    result = self.detect_balance_delta(current_balance, last_balance)
                    if result:
                        event_type, amount = result
                    await self._emit(ActivityEvent(
                        source="kalshi",
                        event_type=event_type,
                        wallet_address=self.wallet_address,
                        platform="kalshi",
                        amount=amount,
                        token="USDC",
                    ))
                last_balance = current_balance

            except Exception as e:
                logger.warning("[kalshi] Positions loop error: {e}")
            await asyncio.sleep(self._positions_interval)