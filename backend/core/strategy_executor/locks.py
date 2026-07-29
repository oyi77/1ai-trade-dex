"""Async coordination locks and rate limiter for trade execution."""

import asyncio
import threading
from typing import Optional

from backend.core.external_rate_limiter import TokenBucketRateLimiter

# Per-asset locks allow concurrent execution across different markets while
# serializing same-market orders to prevent bankroll/exposure double-counting.
# A global semaphore caps total concurrent trades.
_trade_locks: dict[str, asyncio.Lock] = {}
_trade_locks_mutex = asyncio.Lock()

_semaphore_max = None
_trade_semaphore = None  # lazy-init via _ensure_semaphore()


def _ensure_semaphore() -> asyncio.Semaphore:
    global _trade_semaphore, _semaphore_max
    if _trade_semaphore is None:
        from backend.config import settings

        _semaphore_max = int(getattr(settings, "MAX_CONCURRENT_TRADES", 3))
        _trade_semaphore = asyncio.Semaphore(_semaphore_max)
    return _trade_semaphore


_rate_limiter: Optional[TokenBucketRateLimiter] = None

# Threading lock for BotState mutations inside thread-offloaded execution.
_botstate_threading_lock = threading.Lock()


async def _get_asset_lock(asset_key: str) -> asyncio.Lock:
    """Get or create a per-asset async lock."""
    async with _trade_locks_mutex:
        if asset_key not in _trade_locks:
            _trade_locks[asset_key] = asyncio.Lock()
        return _trade_locks[asset_key]


def _get_rate_limiter() -> TokenBucketRateLimiter:
    """Lazily instantiate the global rate limiter."""
    from backend.config import settings
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = TokenBucketRateLimiter(
            per_market_limit=int(getattr(settings, "ORDER_RATE_LIMIT_PER_MARKET", 1)),
            per_market_window=10.0,
            global_limit=int(getattr(settings, "ORDER_RATE_LIMIT_GLOBAL", 3)),
            global_window=1.0,
        )
    return _rate_limiter