"""
Whale Monitor WebSocket — real-time whale activity stream from Polymarket.

Streams whale order notifications via WebSocket for the whale front-running strategy.
Auto-reconnects on network partitions, caches and replays on outage recovery.
"""

import asyncio
import json
import logging
from typing import AsyncIterator, Optional

import websockets

from backend.core.circuit_breaker import CircuitBreaker
from backend.config import settings

logger = logging.getLogger("trading_bot.whale_monitor_ws")

WHALE_WS_URL = settings.POLYMARKET_WS_WHALE_URL
RECONNECT_MAX_RETRIES = 5
RECONNECT_BASE_DELAY = 0.1


class WhaleMonitorWS:
    """
    WebSocket client for whale activity streaming.

    Connects to Polymarket's data WebSocket, filters for whale-order events,
    and yields them as dict messages. Auto-reconnects on disconnect.
    """

    def __init__(self):
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._reconnect_count = 0
        self._buffer: list[dict] = []
        self._breaker = CircuitBreaker("whale_ws", failure_threshold=5, recovery_timeout=60.0)

    async def connect(self) -> bool:
        """Establish WebSocket connection."""
        try:
            self._ws = await websockets.connect(WHALE_WS_URL, ping_interval=10)
            self._running = True
            self._reconnect_count = 0
            logger.info("[whale_monitor_ws] Connected")
            return True
        except Exception as exc:
            logger.warning(f"[whale_monitor_ws] Connect failed: {exc}")
            return False

    async def disconnect(self) -> None:
        """Close WebSocket connection."""
        self._running = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def stream(self) -> AsyncIterator[dict]:
        """
        Yield whale activity messages as they arrive.

        Caches messages during reconnection and replays on recovery.
        """
        await self.connect()

        while self._running:
            if self._buffer:
                for msg in self._buffer:
                    yield msg
                self._buffer.clear()

            if not self._ws:
                if not await self._reconnect():
                    break
                continue

            try:
                message = await self._ws.recv()
                data = json.loads(message)

                if self._is_whale_activity(data):
                    yield data

            except websockets.exceptions.ConnectionClosed:
                logger.warning("[whale_monitor_ws] Connection closed")
                self._buffer.append({"type": "reconnecting"})
                if not await self._reconnect():
                    break

            except json.JSONDecodeError:
                continue

            except Exception as exc:
                logger.warning(f"[whale_monitor_ws] Stream error: {exc}")
                await asyncio.sleep(0.1)

    def _is_whale_activity(self, data: dict) -> bool:
        """Filter for whale-related activity messages."""
        msg_type = data.get("type", "")
        size = float(data.get("size", 0) or 0)
        wallet = data.get("wallet", "")

        return (
            msg_type in ("order", "trade", "whale_activity")
            and size >= 10000
            and wallet
            and wallet not in ("", "0x0000000000000000000000000000000000000000")
        )

    async def _reconnect(self) -> bool:
        """Reconnect with exponential backoff, replay buffer on recovery."""
        self._reconnect_count += 1

        if self._reconnect_count > RECONNECT_MAX_RETRIES:
            logger.error("[whale_monitor_ws] Max reconnect attempts")
            return False

        wait = RECONNECT_BASE_DELAY * (2 ** (self._reconnect_count - 1))
        await asyncio.sleep(wait)

        success = await self.connect()
        if success:
            logger.info("[whale_monitor_ws] Reconnected, replaying buffer")
            self._buffer.append({"type": "reconnected"})
        else:
            self._buffer.append({"type": "reconnect_failed"})

        return success
