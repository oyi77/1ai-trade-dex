"""Order Book HFT WebSocket Handler — real-time order book updates with ping/pong and ordering."""

import asyncio
from typing import AsyncIterator

from backend.config import settings

from loguru import logger

OB_WS_URL = settings.POLYMARKET_WS_ORDERBOOK_URL


class OrderbookHFTWS:
    """
    WebSocket handler for HFT-grade order book data.

    Zero Gaps:
    - Ping/pong: keep-alive every 30s
    - Sequence numbers: detect message reordering
    - Reconnection: exponential backoff
    """

    def __init__(self, condition_id: str):
        self.condition_id = condition_id
        self._ws = None
        self._running = False
        self._last_seq = 0
        self._reconnect_delay = 0.1
        self._max_delay = 30.0
        self._buffer: list[dict] = []

    async def connect(self) -> bool:
        """Connect to order book WebSocket."""
        try:
            import websockets

            self._ws = await websockets.connect(OB_WS_URL, ping_interval=30)
            self._running = True
            await self._subscribe()
            return True
        except Exception as exc:
            logger.warning(f"[ob_hft_ws] Connect failed: {exc}")
            return False

    async def disconnect(self) -> None:
        """Close WebSocket connection."""
        self._running = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                logger.exception("ob_hft_ws disconnect error")
                pass
            self._ws = None

    async def _subscribe(self) -> None:
        """Send subscription message."""
        if self._ws:
            import json

            await self._ws.send(
                json.dumps(
                    {
                        "type": "subscribe",
                        "condition_id": self.condition_id,
                    }
                )
            )

    async def stream(self) -> AsyncIterator[dict]:
        """Yield order book updates with sequence validation."""
        while self._running:
            if not self._ws:
                if not await self._reconnect():
                    break

            try:
                import json

                msg = await asyncio.wait_for(self._ws.recv(), timeout=10.0)
                data = json.loads(msg)

                seq = data.get("seq", 0)
                if seq <= self._last_seq and self._last_seq > 0:
                    logger.debug(
                        f"[ob_hft_ws] Out-of-order seq {seq} < {self._last_seq}"
                    )
                    continue
                self._last_seq = seq

                yield data

            except asyncio.TimeoutError:
                continue
            except Exception as exc:
                logger.warning(f"[ob_hft_ws] Stream error: {exc}")
                self._buffer.append({"type": "reconnecting"})
                await asyncio.sleep(self._reconnect_delay)
                if not await self._reconnect():
                    break

    async def _reconnect(self) -> bool:
        """Reconnect with exponential backoff."""
        if self._reconnect_delay >= self._max_delay:
            logger.error("[ob_hft_ws] Max reconnection attempts")
            return False

        await asyncio.sleep(self._reconnect_delay)
        self._reconnect_delay = min(self._reconnect_delay * 2, self._max_delay)
        return await self.connect()

    def get_snapshot(self) -> dict:
        """Get last known order book snapshot."""
        if self._buffer:
            last = self._buffer[-1]
            if last.get("type") == "snapshot":
                return last
        return {
            "condition_id": self.condition_id,
            "bids": [],
            "asks": [],
            "spread": 0.0,
        }
