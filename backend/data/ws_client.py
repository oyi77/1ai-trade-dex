"""
Polymarket CLOB WebSocket client with auto-reconnect.

Subscribes to real-time price/trade updates for tracked token IDs.
Uses exponential back-off on disconnection, deduplicates subscriptions.

Protocol: wss://ws-subscriptions-clob.polymarket.com/ws/market
Message format: {"assets_ids": [...], "type": "market"}
Requires custom_feature_enabled: true to receive market_resolved events.
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from backend.config import settings

from loguru import logger

WS_URL = settings.POLYMARKET_WS_CLOB_URL
MAX_BACKOFF_S = 60.0
PING_INTERVAL_S = 30.0


@dataclass
class PriceUpdate:
    token_id: str
    best_ask: Optional[float] = None
    best_bid: Optional[float] = None
    mid_price: float = 0.5
    timestamp: float = field(default_factory=time.time)

    @property
    def spread(self) -> float:
        if self.best_ask is not None and self.best_bid is not None:
            return self.best_ask - self.best_bid
        return 1.0


@dataclass
class SettlementEvent:
    token_id: str
    market_address: str
    outcome: str
    timestamp: float = field(default_factory=time.time)


class CLOBWebSocket:
    """
    Auto-reconnecting WebSocket client for Polymarket CLOB price feeds.

    Usage:
        ws = CLOBWebSocket(on_price=handle_price)
        ws.subscribe("token_id_1")
        asyncio.create_task(ws.run())
        ...
        ws.unsubscribe("token_id_1")
        await ws.stop()
    """

    def __init__(
        self,
        on_price: Optional[Callable[[PriceUpdate], None]] = None,
        on_settlement: Optional[Callable[[SettlementEvent], None]] = None,
        max_consecutive_failures: int = 20,
        on_failure: Optional[Callable] = None,
    ):
        self._on_price = on_price
        self._on_settlement = on_settlement
        self.max_consecutive_failures = max_consecutive_failures
        self._on_failure = on_failure
        self._subscribed: set[str] = set()
        self._running = False
        self._ws = None
        self._connected = False
        self._stop_event = asyncio.Event()
        self._consecutive_failures = 0

    # =========================================================================
    # Public API
    # =========================================================================

    async def subscribe(self, token_id: str) -> None:
        """Add a token to the subscription list."""
        self._subscribed.add(token_id)
        if self._connected and self._ws:
            await self._send_subscribe({token_id})

    def unsubscribe(self, token_id: str) -> None:
        """Remove a token from subscriptions."""
        self._subscribed.discard(token_id)

    @property
    def is_connected(self) -> bool:
        return self._connected

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def run(self) -> None:
        """
        Main loop. Connects, re-subscribes, handles messages, auto-reconnects.
        Call as asyncio.create_task(ws.run()). Stop with await ws.stop().
        """
        self._running = True
        backoff = 1.0

        while self._running:
            try:
                await self._connect_and_process()
                backoff = 1.0  # Reset on clean disconnect
                self._consecutive_failures = 0
            except Exception as e:
                self._connected = False
                if not self._running:
                    break
                self._consecutive_failures += 1
                if self._consecutive_failures >= self.max_consecutive_failures:
                    logger.error(
                        f"WebSocket: {self.max_consecutive_failures} consecutive failures, "
                        f"stopping reconnect loop"
                    )
                    if self._on_failure:
                        self._on_failure(e)
                    break
                logger.warning(
                    f"WebSocket disconnected: {e}. Reconnecting in {backoff:.0f}s"
                )
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, MAX_BACKOFF_S)

    async def stop(self) -> None:
        """Signal the run loop to stop."""
        self._running = False
        self._stop_event.set()
        if self._ws:
            try:
                await self._ws.close()
            except Exception as e:
                logger.debug("Error closing WebSocket: %s", e)

    # =========================================================================
    # Internal
    # =========================================================================

    async def _connect_and_process(self) -> None:
        try:
            import websockets
        except ImportError:
            logger.error("websockets not installed — pip install websockets>=12.0")
            raise RuntimeError("websockets not installed")

        logger.info(f"Connecting to Polymarket WebSocket: {WS_URL}")

        async with websockets.connect(
            WS_URL,
            ping_interval=PING_INTERVAL_S,
            ping_timeout=10,
            close_timeout=5,
        ) as ws:
            self._ws = ws
            self._connected = True
            logger.info(
                f"WebSocket connected. Subscribing to {len(self._subscribed)} tokens"
            )

            # Re-subscribe to all tracked tokens on (re)connect
            if self._subscribed:
                await self._send_subscribe(self._subscribed)

            async for raw in ws:
                if not self._running:
                    break
                try:
                    self._handle_message(raw)
                except Exception as e:
                    logger.debug(f"WS message parse error: {e}")

        self._connected = False

    async def _send_subscribe(self, token_ids: set[str]) -> None:
        if not self._ws or not token_ids:
            return
        msg = json.dumps(
            {
                "assets_ids": list(token_ids),
                "type": "market",
                "custom_feature_enabled": True,
            }
        )
        try:
            await self._ws.send(msg)
            logger.debug(
                f"Subscribed to {len(token_ids)} tokens with custom_feature_enabled"
            )
        except Exception as e:
            logger.warning(f"Subscribe send failed: {e}")

    def _handle_message(self, raw: str) -> None:
        """Parse a WebSocket message and dispatch to on_price or on_settlement callback."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return

        # Polymarket sends both single-object and list responses
        events = data if isinstance(data, list) else [data]

        for event in events:
            event_type = event.get("event_type", "")

            # Handle market_resolved events (requires custom_feature_enabled: true)
            if event_type == "market_resolved" and self._on_settlement:
                token_id = event.get("asset_id") or event.get("token_id", "")
                market_address = event.get("market", "")
                outcome = event.get("outcome", "")
                if token_id and outcome:
                    settlement = SettlementEvent(
                        token_id=token_id,
                        market_address=market_address,
                        outcome=outcome,
                    )
                    self._on_settlement(settlement)
                continue

            token_id = event.get("asset_id") or event.get("token_id", "")
            if not token_id:
                continue

            # Extract best bid/ask from the L2 book update
            bids = event.get("bids", [])
            asks = event.get("asks", [])

            best_bid = float(bids[0]["price"]) if bids else None
            best_ask = float(asks[0]["price"]) if asks else None

            mid = 0.5
            if best_bid is not None and best_ask is not None:
                mid = (best_bid + best_ask) / 2
            elif best_bid is not None:
                mid = best_bid
            elif best_ask is not None:
                mid = best_ask
            elif "price" in event:
                mid = float(event["price"])

            update = PriceUpdate(
                token_id=token_id,
                best_bid=best_bid,
                best_ask=best_ask,
                mid_price=mid,
            )

            if self._on_price:
                self._on_price(update)
