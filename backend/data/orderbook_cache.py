"""
In-memory orderbook cache for WebSocket-driven market data.

Maintains real-time orderbook state from WebSocket updates and provides
fast access to current prices without REST API calls.
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Dict, Optional

from loguru import logger
@dataclass
class CachedOrderbook:
    token_id: str
    bids: list
    asks: list
    mid_price: float
    last_update: float

    @property
    def best_bid(self) -> Optional[float]:
        return float(self.bids[0]["price"]) if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        return float(self.asks[0]["price"]) if self.asks else None

    @property
    def spread(self) -> float:
        if self.best_ask and self.best_bid:
            return self.best_ask - self.best_bid
        return 1.0

    @property
    def age_seconds(self) -> float:
        return time.time() - self.last_update


class OrderbookCache:
    """
    Thread-safe in-memory cache for WebSocket orderbook updates.

    Usage:
        cache = OrderbookCache()

        # Update from WebSocket
        cache.update(token_id, bids, asks)

        # Read cached data
        book = cache.get(token_id)
        if book and book.age_seconds < 5.0:
            price = book.mid_price
    """

    def __init__(self, max_age_seconds: float = 30.0):
        self._cache: Dict[str, CachedOrderbook] = {}
        self._lock = asyncio.Lock()
        self._max_age = max_age_seconds

    async def update(self, token_id: str, bids: list, asks: list) -> None:
        """Update orderbook from WebSocket event"""
        mid = 0.5
        if bids and asks:
            mid = (float(bids[0]["price"]) + float(asks[0]["price"])) / 2
        elif bids:
            mid = float(bids[0]["price"])
        elif asks:
            mid = float(asks[0]["price"])

        async with self._lock:
            self._cache[token_id] = CachedOrderbook(
                token_id=token_id,
                bids=bids,
                asks=asks,
                mid_price=mid,
                last_update=time.time(),
            )
            logger.debug(f"Updated orderbook cache for {token_id}: mid={mid:.4f}")

    async def get(self, token_id: str) -> Optional[CachedOrderbook]:
        """Get cached orderbook if fresh"""
        async with self._lock:
            book = self._cache.get(token_id)
            if book and book.age_seconds <= self._max_age:
                return book
            return None

    async def get_mid_price(self, token_id: str) -> Optional[float]:
        """Get cached mid price if fresh"""
        book = await self.get(token_id)
        return book.mid_price if book else None

    async def clear(self) -> None:
        """Clear all cached data"""
        async with self._lock:
            self._cache.clear()

    async def prune_stale(self) -> int:
        """Remove stale entries, return count removed"""
        now = time.time()
        removed = 0

        async with self._lock:
            stale_keys = [
                k
                for k, v in self._cache.items()
                if (now - v.last_update) > self._max_age
            ]
            for key in stale_keys:
                del self._cache[key]
                removed += 1

        if removed:
            logger.info(f"Pruned {removed} stale orderbook entries")

        return removed

    @property
    def size(self) -> int:
        """Number of cached orderbooks"""
        return len(self._cache)


_global_cache: Optional[OrderbookCache] = None


def get_orderbook_cache() -> OrderbookCache:
    """Get singleton orderbook cache instance"""
    global _global_cache
    if _global_cache is None:
        _global_cache = OrderbookCache(max_age_seconds=30.0)
    return _global_cache
