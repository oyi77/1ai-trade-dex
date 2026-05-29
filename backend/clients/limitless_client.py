"""Limitless Exchange client — raw API for markets, SDK for orders."""

import os
import time as _time

import httpx
from loguru import logger


class LimitlessClient:
    """Limitless Exchange API client.

    Uses raw HTTP for market data (includes prices[]),
    uses official limitless-sdk for order placement (EIP-712 signing).
    5-minute cache on market fetches to avoid Cloudflare rate limits.
    """

    def __init__(self, base_url: str = None):
        self._base_url = (
            base_url or os.getenv("LIMITLESS_API_URL", "https://api.limitless.exchange")
        ).rstrip("/")
        self._api_key = os.getenv("LIMITLESS_API_KEY", "")
        self._private_key = os.getenv("LIMITLESS_PRIVATE_KEY", "")
        self._sdk = None
        self._markets_cache = None
        self._markets_cache_time = 0.0
        self._cache_ttl = 300.0  # 5 min

    def _get_sdk(self):
        """Lazy-init the Limitless SDK client for order operations."""
        if self._sdk is None:
            from limitless_sdk import LimitlessClient as SDKClient
            # Patch missing ensure_authenticated (SDK bug)
            if not hasattr(SDKClient, 'ensure_authenticated'):
                SDKClient.ensure_authenticated = SDKClient.ensure_session
            key = self._private_key
            if key and not key.startswith("0x"):
                key = "0x" + key
            self._sdk = SDKClient(
                private_key=key or ("0x" + "0" * 64),
                api_key=self._api_key or None,
            )
        return self._sdk

    async def get_markets(self, limit: int = 100) -> list:
        """Get active markets using SDK with 5-minute cache."""
        now = _time.monotonic()
        if self._markets_cache and (now - self._markets_cache_time) < self._cache_ttl:
            return self._markets_cache[:limit]
        try:
            sdk = self._get_sdk()
            markets = await sdk.get_all_active_markets()
            if markets:
                self._markets_cache = markets
                self._markets_cache_time = now
            return (markets or [])[:limit]
        except Exception as e:
            logger.warning(f"[limitless] get_markets failed: {e}")
            return self._markets_cache[:limit] if self._markets_cache else []

    def _auth_headers(self) -> dict:
        """Build auth headers for raw API calls."""
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        return headers

    async def get_markets(self, limit: int = 100) -> list:
        """Get active markets with 5-minute cache to avoid Cloudflare rate limits."""
        now = _time.monotonic()
        if self._markets_cache and (now - self._markets_cache_time) < self._cache_ttl:
            return self._markets_cache[:limit]

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                all_markets = []
                for page in range(1, 21):  # max 20 pages = 500 markets
                    resp = await client.get(
                        f"{self._base_url}/markets/active",
                        params={"limit": 25, "page": page},
                        headers=self._auth_headers(),
                    )
                    if resp.status_code == 429:
                        logger.warning(f"[limitless] Rate limited on page {page}, using cached results")
                        break
                    if resp.status_code != 200:
                        break
                    data = resp.json().get("data", [])
                    if not data:
                        break
                    all_markets.extend(data)
                    if len(data) < 25:
                        break
                if all_markets:
                    self._markets_cache = all_markets
                    self._markets_cache_time = now
                return all_markets[:limit]
        except Exception as e:
            logger.warning(f"[limitless] get_markets failed: {e}")
            return self._markets_cache[:limit] if self._markets_cache else []

    async def get_orderbook(self, market_id: str) -> dict:
        """Get orderbook for a specific market."""
        sdk = self._get_sdk()
        try:
            return await sdk.get_orderbook(market_id)
        except Exception as e:
            logger.warning(f"[limitless] get_orderbook failed: {e}")
            return {}

    async def place_order(
        self, market_id: str, side: str, size: float, price: float, private_key: str
    ) -> dict:
        """Place an order using official SDK (handles EIP-712 signing)."""
        sdk = self._get_sdk()
        try:
            logger.info(f"[limitless] Creating session...")
            await sdk.create_session()
            logger.info(f"[limitless] Session created. Creating order for {market_id} side={side} size={size} price={price}")
            outcome_index = 0  # YES
            side_int = 1 if side.upper() == "BUY" else 0
            dto = await sdk.create_order(
                market_id=market_id,
                market_slug=market_id,
                outcome_index=outcome_index,
                side=side_int,
                amount=size,
                price=price,
            )
            logger.info(f"[limitless] Order DTO created: {dto}")
            result = await sdk.place_order(dto)
            logger.info(f"[limitless] Order placed: {result}")
            return result
        except Exception as e:
            logger.warning(f"[limitless] place_order failed: {e}")
            import traceback
            traceback.print_exc()
            return {"error": str(e)}

    async def cancel_order(self, order_id: str, private_key: str) -> bool:
        """Cancel an open order using official SDK."""
        sdk = self._get_sdk()
        try:
            from limitless_sdk.models import CancelOrderDto
            dto = CancelOrderDto(order_id=order_id)
            await sdk.cancel_order(dto)
            return True
        except Exception as e:
            logger.warning(f"[limitless] cancel_order failed: {e}")
            return False

    async def get_fills(self, wallet_address: str, limit: int = 100) -> list:
        """Get recent fills/trades for a wallet address."""
        sdk = self._get_sdk()
        try:
            return await sdk.get_user_history()
        except Exception as e:
            logger.warning(f"[limitless] get_fills failed: {e}")
            return []

    async def health_check(self) -> bool:
        """Check if Limitless Exchange API is available."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self._base_url}/markets/active",
                    params={"limit": 1},
                    headers=self._auth_headers(),
                )
                return resp.status_code == 200
        except Exception:
            return False
