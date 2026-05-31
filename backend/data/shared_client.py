"""Shared httpx.AsyncClient for all data fetches.

Eliminates ephemeral client creation (53 found in backend/data/) that
causes connection pool exhaustion, PoolTimeout, and circuit breaker trips.

Usage:
    from backend.data.shared_client import get_shared_client
    client = get_shared_client()
    resp = await client.get(url, params=params)
"""

import asyncio
import httpx
from loguru import logger

# Shared client with generous pool — one client for all data fetches
_shared_client: httpx.AsyncClient | None = None

# Semaphore to limit concurrent requests and prevent PoolTimeout
_semaphore = asyncio.Semaphore(10)


def get_shared_client() -> httpx.AsyncClient:
    """Get or create the shared httpx.AsyncClient. Thread-safe via module-level singleton."""
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(
                max_connections=100,
                max_keepalive_connections=30,
            ),
            follow_redirects=True,
            headers={
                "User-Agent": "PolyEdge/1.0",
                "Accept": "application/json",
            },
        )
        logger.info("[shared_client] Created shared httpx.AsyncClient (max_connections=100)")
    return _shared_client


async def close_shared_client() -> None:
    """Close the shared client. Call on shutdown."""
    global _shared_client
    if _shared_client is not None and not _shared_client.is_closed:
        await _shared_client.aclose()
        logger.info("[shared_client] Closed shared httpx.AsyncClient")
    _shared_client = None


def get_semaphore() -> asyncio.Semaphore:
    """Get the concurrency semaphore for rate-limited fetches."""
    return _semaphore
