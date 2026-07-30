"""CLOB helper functions and module-level state."""

import asyncio

from backend.core.risk.circuit_breaker import CircuitBreaker
from backend.config import settings

from loguru import logger


def ensure_token_id(token_id: str) -> str:
    """Ensure token_id is a decimal string for CLOB API.

    Polymarket CLOB exchange_order_builder expects tokenId to be
    convertible to int via int(tokenId). Gamma/Data APIs return
    token IDs as decimal strings.
    """
    if not token_id:
        return token_id
    if token_id.startswith("0x"):
        try:
            return str(int(token_id, 16))
        except ValueError:
            return token_id
    return token_id


clob_breaker = CircuitBreaker("polymarket_clob")

CLOB_HOST = settings.CLOB_API_URL
GAMMA_HOST = settings.GAMMA_API_URL
DATA_HOST = settings.DATA_API_URL
CHAIN_ID = 137  # Polygon mainnet — Builder Program and all trading run on mainnet


# Keys currently being processed (in-flight guard against concurrent duplicate calls)
_inflight_keys: set[str] = set()
_inflight_lock = asyncio.Lock()


async def _check_and_claim_idempotency(key: str) -> bool:
    """
    Return True (duplicate) if key is already in-flight or in the DB.
    Claims the key in the in-flight set atomically to prevent concurrent duplicates.
    Caller must release via _release_idempotency_key() after the order is recorded.
    """
    async with _inflight_lock:
        if key in _inflight_keys:
            return True
        _inflight_keys.add(key)

    # Check DB for cross-process/restart duplicates
    from backend.models.database import SessionLocal, Trade
    from backend.core.risk.circuit_breaker_pybreaker import db_breaker

    def _db_query():
        db = SessionLocal()
        try:
            existing = db.query(Trade).filter(Trade.clob_idempotency_key == key).first()
            return existing
        finally:
            db.close()

    try:
        existing = db_breaker.call(_db_query)
        if existing is not None:
            async with _inflight_lock:
                _inflight_keys.discard(key)
            return True
        return False
    except Exception as e:
        logger.warning(f"DB circuit breaker open or query failed: {e}")
        return False


def _release_idempotency_key(key: str) -> None:
    """Remove key from in-flight set after order is recorded (or failed)."""
    _inflight_keys.discard(key)
