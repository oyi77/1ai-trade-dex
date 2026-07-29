"""Strategy-execution helpers — pure utility functions with no module-level state."""

import time
from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from sqlalchemy import func
from sqlalchemy.exc import OperationalError


_MAX_LOCK_RETRY_ATTEMPTS = 4
_LOCK_RETRY_BASE_DELAY_SECONDS = 0.2


class _BotStateLockRetry(RuntimeError):
    """Signal that trade execution should retry after BotState lock contention."""


def _is_lock_timeout_error(exc: OperationalError) -> bool:
    """Return True for PostgreSQL lock-timeout / lock-not-available failures."""
    orig = getattr(exc, "orig", None)
    pgcode = getattr(orig, "pgcode", None)
    if pgcode == "55P03":
        return True
    message = str(exc).lower()
    return (
        "lock timeout" in message
        or "locknotavailable" in message
        or "could not obtain lock" in message
        or "canceling statement due to lock timeout" in message
    )


def _lock_retry_delay(attempt: int) -> float:
    return _LOCK_RETRY_BASE_DELAY_SECONDS * (2 ** attempt)


def _first_numeric_attr(obj, names: tuple[str, ...]) -> Optional[float]:
    """Return the first numeric attribute/key from a venue result object."""
    for name in names:
        value = None
        if isinstance(obj, dict):
            value = obj.get(name)
        else:
            value = getattr(obj, name, None)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


async def _resolve_token_id_from_gamma(identifier: str) -> Optional[str]:
    """Resolve a token_id from a market slug or conditionId via Gamma API."""
    if not identifier:
        return None

    from backend.data.shared_client import get_shared_client
    from backend.config import settings

    client = get_shared_client()
    gamma_base = settings.GAMMA_API_URL
    import json as _json_lib

    def _extract_token_id(market: dict) -> Optional[str]:
        clob_token_ids = market.get("clobTokenIds") or []
        if isinstance(clob_token_ids, str):
            try:
                clob_token_ids = _json_lib.loads(clob_token_ids)
            except Exception:
                clob_token_ids = []
        if clob_token_ids and len(clob_token_ids) > 0:
            return str(clob_token_ids[0])
        return None

    # Attempt 1: look up by slug on /events endpoint
    try:
        resp = await client.get(f"{gamma_base}/events", params={"slug": identifier})
        resp.raise_for_status()
        data = resp.json()
        if data:
            event = data[0] if isinstance(data, list) else data
            for market in event.get("markets", []):
                token_id = _extract_token_id(market)
                if token_id:
                    return token_id
    except Exception:
        pass

    # Attempt 2: look up by conditionId on /markets endpoint
    try:
        resp = await client.get(f"{gamma_base}/markets", params={"conditionId": identifier})
        resp.raise_for_status()
        data = resp.json()
        if data:
            market = data[0] if isinstance(data, list) else data
            token_id = _extract_token_id(market)
            if token_id:
                return token_id
    except Exception:
        pass

    logger.warning(
        f"[strategy_executor] Failed to resolve token_id for '{identifier}' "
        f"via Gamma API (tried slug and conditionId)"
    )
    return None