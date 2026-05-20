"""
Real-time order book engine for Polymarket CLOB WebSocket.

Connects to wss://ws-live-data.polymarket.com and maintains live L2 order books
for subscribed token IDs. Supports snapshot (book) and delta (price_change) updates.
Auto-reconnects with exponential backoff on disconnection.
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Optional

from backend.config import settings

from loguru import logger

WS_URL = settings.POLYMARKET_WS_RTDS_URL
MAX_BACKOFF_S = 30.0
PING_INTERVAL_S = 30.0


@dataclass
class LiveOrderBook:
    """Live L2 order book for a single token."""

    token_id: str
    bids: list = field(default_factory=list)  # [[price, size], ...] sorted desc
    asks: list = field(default_factory=list)  # [[price, size], ...] sorted asc
    last_update: float = field(default_factory=time.time)
    last_trade_price: Optional[float] = None

    # ------------------------------------------------------------------
    # Computed properties
    # ------------------------------------------------------------------

    @property
    def mid_price(self) -> float:
        if self.bids and self.asks:
            return (self.bids[0][0] + self.asks[0][0]) / 2.0
        if self.bids:
            return self.bids[0][0]
        if self.asks:
            return self.asks[0][0]
        return 0.0

    @property
    def spread(self) -> float:
        if self.bids and self.asks:
            return self.asks[0][0] - self.bids[0][0]
        return 0.0

    @property
    def spread_pct(self) -> float:
        mid = self.mid_price
        if mid > 0:
            return self.spread / mid
        return 0.0

    @property
    def bid_depth(self) -> float:
        return sum(level[1] for level in self.bids)

    @property
    def ask_depth(self) -> float:
        return sum(level[1] for level in self.asks)

    @property
    def imbalance(self) -> float:
        """Order book imbalance in range [-1, 1]. Positive = more bids."""
        total = self.bid_depth + self.ask_depth
        if total == 0:
            return 0.0
        return (self.bid_depth - self.ask_depth) / total

    # ------------------------------------------------------------------
    # Mutation methods
    # ------------------------------------------------------------------

    def apply_delta(self, side: str, price: float, size: float) -> None:
        """Update a single price level. size=0 removes the level."""
        if side == "BID":
            levels = self.bids
        else:
            levels = self.asks

        # Find existing level
        for i, (p, _s) in enumerate(levels):
            if p == price:
                if size == 0:
                    levels.pop(i)
                else:
                    levels[i] = [price, size]
                break
        else:
            # Not found — insert if size > 0
            if size > 0:
                levels.append([price, size])

        # Re-sort: bids desc, asks asc
        if side == "BID":
            self.bids.sort(key=lambda x: x[0], reverse=True)
        else:
            self.asks.sort(key=lambda x: x[0])

        self.last_update = time.time()

    def apply_snapshot(self, bids: list, asks: list) -> None:
        """Replace the entire book with a snapshot."""
        self.bids = [[float(p), float(s)] for p, s in bids]
        self.asks = [[float(p), float(s)] for p, s in asks]
        self.bids.sort(key=lambda x: x[0], reverse=True)
        self.asks.sort(key=lambda x: x[0])
        self.last_update = time.time()


class OrderBookManager:
    """
    Manages live order books for multiple token IDs via Polymarket WebSocket.

    Usage:
        mgr = OrderBookManager()
        await mgr.subscribe("token_id_1")
        await mgr.connect()
        book = mgr.get_book("token_id_1")
        await mgr.disconnect()
    """

    def __init__(self) -> None:
        self.books: dict[str, LiveOrderBook] = {}
        self._subscriptions: set[str] = set()
        self._ws = None
        self._lock = asyncio.Lock()
        self._running = False
        self._stop_event: asyncio.Event = asyncio.Event()
        self._connected = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def subscribe(self, token_id: str) -> None:
        """Add token to subscriptions, send subscribe message if connected."""
        async with self._lock:
            self._subscriptions.add(token_id)
            if token_id not in self.books:
                self.books[token_id] = LiveOrderBook(token_id=token_id)

        if self._connected and self._ws:
            await self._send_subscribe({token_id})

    async def unsubscribe(self, token_id: str) -> None:
        """Remove token from subscriptions."""
        async with self._lock:
            self._subscriptions.discard(token_id)

    def get_book(self, token_id: str) -> Optional[LiveOrderBook]:
        """Return the current order book for a token, or None if not subscribed."""
        return self.books.get(token_id)

    async def connect(self) -> None:
        """Connect to WS and handle messages. Auto-reconnects with backoff."""
        self._running = True
        backoff = 1.0

        while self._running:
            try:
                await self._connect_and_process()
                backoff = 1.0
            except Exception as e:
                self._connected = False
                if not self._running:
                    break
                logger.warning(
                    f"OrderBook WS disconnected: {e}. Reconnecting in {backoff:.0f}s"
                )
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, MAX_BACKOFF_S)

    async def disconnect(self) -> None:
        """Close the WebSocket connection and stop reconnecting."""
        self._running = False
        self._stop_event.set()
        if self._ws:
            try:
                await self._ws.close()
            except Exception as e:
                logger.debug("Error closing WebSocket: %s", e)
        self._connected = False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _connect_and_process(self) -> None:
        try:
            import websockets
        except ImportError:
            logger.error("websockets not installed — pip install websockets>=12.0")
            raise RuntimeError("websockets not installed")

        logger.info(f"Connecting to Polymarket order book WS: {WS_URL}")

        import ssl as _ssl

        _ssl_ctx = _ssl.create_default_context()

        async with websockets.connect(
            WS_URL,
            ssl=_ssl_ctx,
            ping_interval=PING_INTERVAL_S,
            ping_timeout=10,
            close_timeout=5,
            max_size=4 * 1024 * 1024,  # 4 MiB bound
        ) as ws:
            self._ws = ws
            self._connected = True
            logger.info(
                f"Order book WS connected. Subscribing to {len(self._subscriptions)} tokens"
            )

            if self._subscriptions:
                await self._send_subscribe(self._subscriptions)

            async for raw in ws:
                if not self._running:
                    break
                try:
                    data = json.loads(raw)
                    await self._handle_message(data)
                except Exception as e:
                    logger.debug(f"Order book WS message parse error: {e}")

        self._connected = False

    async def _send_subscribe(self, token_ids: set) -> None:
        if not self._ws or not token_ids:
            return
        msg = json.dumps({"assets_ids": list(token_ids), "type": "market"})
        try:
            await self._ws.send(msg)
            logger.debug(f"Order book: subscribed to {len(token_ids)} tokens")
        except Exception as e:
            logger.warning(f"Order book subscribe send failed: {e}")

    async def _handle_message(self, data: dict) -> None:
        """Parse and apply WS message to the appropriate order book."""
        # Messages may arrive as a list or single object
        events = data if isinstance(data, list) else [data]

        for event in events:
            msg_type = event.get("event_type") or event.get("type", "")
            token_id = event.get("asset_id") or event.get("token_id", "")

            if not token_id:
                continue

            async with self._lock:
                book = self.books.get(token_id)
                if book is None:
                    if token_id not in self._subscriptions:
                        continue
                    if len(self.books) >= 500:
                        logger.warning(
                            "OrderBookManager: max tracked books reached, ignoring %s",
                            token_id,
                        )
                        continue
                    book = LiveOrderBook(token_id=token_id)
                    self.books[token_id] = book

            if msg_type == "book":
                # Full snapshot
                raw_bids = event.get("bids", [])
                raw_asks = event.get("asks", [])
                bids = [[float(b["price"]), float(b["size"])] for b in raw_bids]
                asks = [[float(a["price"]), float(a["size"])] for a in raw_asks]
                book.apply_snapshot(bids, asks)
                logger.debug(
                    f"Order book snapshot: {token_id} bids={len(bids)} asks={len(asks)}"
                )

            elif msg_type == "price_change":
                # Delta update — event may contain lists of changes
                changes = event.get("changes", [])
                for change in changes:
                    side = change.get("side", "").upper()
                    price = float(change.get("price", 0))
                    size = float(change.get("size", 0))
                    if side in ("BID", "ASK"):
                        book.apply_delta(side, price, size)
                logger.debug(f"Order book delta: {token_id} {len(changes)} changes")

            elif msg_type == "last_trade_price":
                price = float(event.get("price", 0))
                if price > 0:
                    book.last_trade_price = price
                    book.last_update = time.time()
