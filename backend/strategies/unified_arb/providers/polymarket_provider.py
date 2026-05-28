"""Polymarket provider — fetches markets and places orders via CLOB."""

import asyncio
import logging
from typing import List, Union

from backend.strategies.unified_arb.types import (
    FeeSchedule,
    OrderResult,
    PMMarket,
    PMProvider,
)

logger = logging.getLogger(__name__)

# Module-level circuit breaker singleton
_breaker_failures = 0
_BREAKER_THRESHOLD = 5


class PolymarketProvider(PMProvider):
    venue_name = "polymarket"

    def __init__(self, clob=None, gamma_url: str = ""):
        self._clob = clob
        self._gamma_url = gamma_url or "https://gamma-api.polymarket.com"

    async def fetch_markets(self, limit: int = 500) -> List[PMMarket]:
        """Fetch Polymarket markets via Gamma API with pagination."""
        import httpx

        markets = []
        offset = 0
        page_size = min(limit, 100)

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                while len(markets) < limit:
                    resp = await client.get(
                        f"{self._gamma_url}/markets",
                        params={"limit": page_size, "offset": offset, "active": True},
                    )
                    if resp.status_code != 200:
                        break
                    data = resp.json()
                    if not data:
                        break
                    for m in data:
                        clob_ids = m.get("clobTokenIds", [])
                        if isinstance(clob_ids, str):
                            import json
                            try:
                                clob_ids = json.loads(clob_ids)
                            except (json.JSONDecodeError, TypeError):
                                continue
                        if not clob_ids or len(clob_ids) < 2:
                            continue
                        markets.append(PMMarket(
                            event_id=m.get("conditionId", ""),
                            question=m.get("question", ""),
                            slug=m.get("slug", ""),
                            platform="polymarket",
                            yes_price=float(m.get("outcomePrices", "[0.5,0.5]").strip("[]").split(",")[0]) if m.get("outcomePrices") else 0.5,
                            no_price=float(m.get("outcomePrices", "[0.5,0.5]").strip("[]").split(",")[1]) if m.get("outcomePrices") else 0.5,
                            token_id_yes=clob_ids[0],
                            token_id_no=clob_ids[1],
                            condition_id=m.get("conditionId", ""),
                            fee_pct=0.02,
                            liquidity=float(m.get("liquidity", 0) or 0),
                            volume=float(m.get("volume", 0) or 0),
                        ))
                    offset += page_size
                    if len(data) < page_size:
                        break
        except Exception as e:
            logger.warning(f"[polymarket_provider] fetch failed: {e}")

        return markets[:limit]

    async def place_order(
        self, token_id: str, side: str, price: float, size: float, idempotency_key: str = ""
    ) -> OrderResult:
        global _breaker_failures
        if _breaker_failures >= _BREAKER_THRESHOLD:
            return OrderResult(status="failed", error="circuit_breaker_open")

        if not self._clob:
            return OrderResult(status="failed", error="no_clob_client")

        for attempt in range(3):
            try:
                result = await self._clob.place_limit_order(
                    token_id=token_id,
                    side=side,
                    price=price,
                    size=size,
                    idempotency_key=idempotency_key,
                )
                if hasattr(result, "order_id") and result.order_id:
                    _breaker_failures = 0
                    return OrderResult(order_id=str(result.order_id), status="filled", fill_price=price)
                if hasattr(result, "success") and not result.success:
                    return OrderResult(status="failed", error=str(getattr(result, "error", "unknown")))
                return OrderResult(status="failed", error="no_order_id")
            except Exception as e:
                if attempt < 2:
                    await asyncio.sleep(0.01 * (2 ** attempt))
                else:
                    _breaker_failures += 1
                    logger.warning(f"[polymarket_provider] place_order failed: {e}")
                    return OrderResult(status="failed", error=str(e))
        return OrderResult(status="failed", error="max_retries")

    async def cancel_order(self, order_id: str) -> bool:
        if not self._clob:
            return False
        try:
            await self._clob.cancel_order(order_id)
            return True
        except Exception as e:
            logger.warning(f"[polymarket_provider] cancel failed: {e}")
            return False

    def get_fee_schedule(self) -> FeeSchedule:
        return FeeSchedule(taker_fee_pct=0.02, maker_fee_pct=0.0, slippage_bps=10)
