"""
Gamma API client for Polymarket market data.

Provides fetch_markets() used by realtime_scanner and other strategies
to retrieve active markets from the Polymarket Gamma API.

Rate limiting: Uses ExternalRateLimiter with RATE_LIMIT_GAMMA config.
"""

from typing import Any, Optional

import httpx

from backend.config import settings
from backend.data.shared_client import get_shared_client
from backend.core.circuit_breaker import CircuitBreaker, CircuitOpenError
from backend.core.errors import ExternalAPIError
from backend.core.external_rate_limiter import ExternalRateLimiter
from backend.core.retry import retry

from loguru import logger

# Circuit breaker for transient failures
gamma_breaker = CircuitBreaker(
    "gamma_api",
    failure_threshold=settings.CB_FAILURE_THRESHOLD,
    recovery_timeout=settings.CB_RECOVERY_TIMEOUT,
)

# Rate limiter for Gamma API (configurable requests per minute)
_gamma_rate_limiter = ExternalRateLimiter(
    name="gamma",
    max_calls_per_minute=settings.RATE_LIMIT_GAMMA,
    circuit_breaker=gamma_breaker,
)

GAMMA_API_URL = f"{settings.GAMMA_API_URL}/markets"
_RATE_LIMIT_MAX_RETRIES = 3


def get_gamma_rate_limiter() -> ExternalRateLimiter:
    """Return the module-level rate limiter instance."""
    return _gamma_rate_limiter


async def fetch_markets(
    limit: int = 100,
    active: bool = True,
    order: str = "volume",
    ascending: bool = False,
) -> list[dict[str, Any]]:
    """Fetch markets from the Polymarket Gamma API with pagination.

    Args:
        limit: Maximum number of markets to return.
        active: True for active markets, False for closed/resolved.
        order: Sort field (e.g. 'volume', 'liquidity', 'created').
        ascending: Sort direction.

    Returns:
        List of market dicts from the Gamma API, or empty list on failure.
    """

    async def _fetch_single_page() -> list[dict[str, Any]]:
        client = get_shared_client()
        resp = await client.get(
            GAMMA_API_URL,
            params={
                "active": str(active).lower(),
                "closed": str(not active).lower(),
                "limit": limit,
                "order": order,
                "ascending": str(ascending).lower(),
            },
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        return []

    if limit <= 100:

        async def _fetch_single_page_limited() -> list[dict[str, Any]]:
            client = get_shared_client()
            resp = await client.get(
                GAMMA_API_URL,
                params={
                    "active": str(active).lower(),
                    "closed": str(not active).lower(),
                    "limit": limit,
                    "order": order,
                    "ascending": str(ascending).lower(),
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
            return []

        try:
            return await _gamma_rate_limiter.call(_fetch_single_page_limited)
        except CircuitOpenError:
            logger.warning("[gamma] Gamma API circuit open, skipping")
            raise
        except httpx.TimeoutException:
            logger.warning("[gamma] Gamma API request timed out")
            raise ExternalAPIError(
                "Gamma API request timed out",
                source="gamma_api",
                status_code=408,
                is_transient=True,
            )
        except httpx.HTTPStatusError as e:
            logger.warning("[gamma] Gamma API HTTP error: %s", e.response.status_code)
            raise ExternalAPIError(
                f"Gamma API HTTP error: {e.response.status_code}",
                source="gamma_api",
                status_code=e.response.status_code,
                is_transient=e.response.status_code >= 500,
            )
        except ExternalAPIError:
            raise
        except Exception as e:
            logger.warning("[gamma] Gamma API fetch failed: %s", e)
            raise ExternalAPIError(
                f"Gamma API fetch failed: {e}",
                source="gamma_api",
                is_transient=True,
            )

    async def _fetch_page(
        client: httpx.AsyncClient, cursor: Optional[str]
    ) -> Optional[list]:
        params = {
            "active": str(active).lower(),
            "closed": str(not active).lower(),
            "limit": page_size,
            "order": order,
            "ascending": str(ascending).lower(),
        }
        if cursor:
            params["after_cursor"] = cursor

        @retry(max_attempts=_RATE_LIMIT_MAX_RETRIES)
        async def _gamma_request() -> list:
            resp = await client.get(GAMMA_API_URL, params=params)
            resp.raise_for_status()
            return resp.json()

        try:
            return await _gamma_request()
        except Exception:
            return None

    all_markets: list[dict[str, Any]] = []
    cursor: Optional[str] = None
    page_size = 100
    try:
        client = get_shared_client()
        while len(all_markets) < limit:
            try:
                page = await _gamma_rate_limiter.call(_fetch_page, client, cursor)
            except CircuitOpenError:
                logger.warning(
                    "[gamma] Gamma API circuit open during pagination at cursor %s",
                    cursor,
                )
                break
            if page is None or not isinstance(page, list) or not page:
                break
            all_markets.extend(page)
            if len(page) < page_size:
                break
            # Extract cursor from last item for next page
            last_item = page[-1] if page else None
            cursor = last_item.get("cursor") if isinstance(last_item, dict) else None
            if not cursor:
                break
        return all_markets[:limit]
    except Exception as e:
        logger.warning("[gamma] Paginated fetch failed: %s", e)
        return all_markets


async def fetch_resolved_markets(
    limit: int = 500,
    tag: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Fetch resolved (settled) markets from Polymarket Gamma API.

    Returns markets with their final outcome prices, suitable for
    historical backtesting. Paginates through all available results.
    """

    async def _fetch_resolved_page(
        client: httpx.AsyncClient, params: dict
    ) -> Optional[list]:
        @retry(max_attempts=_RATE_LIMIT_MAX_RETRIES)
        async def _gamma_request() -> list:
            resp = await client.get(GAMMA_API_URL, params=params)
            resp.raise_for_status()
            return resp.json()

        try:
            return await _gamma_request()
        except Exception:
            return None

    all_markets = []
    cursor: Optional[str] = None
    page_size = min(limit, 100)

    try:
        client = get_shared_client()
        while len(all_markets) < limit:
            params: dict[str, Any] = {
                "active": "false",
                "closed": "true",
                "limit": page_size,
                "order": "endDate",
                "ascending": "false",
            }
            if tag:
                params["tag"] = tag
            if cursor:
                params["after_cursor"] = cursor

            try:
                page = await _gamma_rate_limiter.call(
                    _fetch_resolved_page, client, params
                )
            except CircuitOpenError:
                logger.warning(
                    "[gamma] Gamma API circuit open during resolved markets fetch at cursor %s",
                    cursor,
                )
                break

            if page is None:
                logger.warning(
                    "[gamma] Rate limited after %d retries at cursor %s",
                    _RATE_LIMIT_MAX_RETRIES,
                    cursor,
                )
                break

            if not isinstance(page, list) or not page:
                break

            for m in page:
                if not m.get("resolved"):
                    continue
                all_markets.append(m)

            if len(page) < page_size:
                break
            last_item = page[-1] if page else None
            cursor = last_item.get("cursor") if isinstance(last_item, dict) else None
            if not cursor:
                break

        logger.info(
            "[gamma] Fetched %d resolved markets (limit=%d, tag=%s)",
            len(all_markets),
            limit,
            tag,
        )
        return all_markets[:limit]

    except Exception as e:
        logger.warning("[gamma] Resolved markets fetch failed: %s", e)
        return all_markets
