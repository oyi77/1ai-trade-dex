"""Kalshi provider — fetches markets and places orders via KalshiClient."""

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

_breaker_failures = 0
_BREAKER_THRESHOLD = 5


class KalshiProvider(PMProvider):
    venue_name = "kalshi"

    def __init__(self, kalshi_client=None):
        self._client = kalshi_client

    async def fetch_markets(self, limit: int = 500) -> List[PMMarket]:
        """Fetch Kalshi markets via KalshiClient."""
        if not self._client:
            return []

        markets = []
        try:
            raw_markets = await self._client.get_markets(limit=limit)
            for m in raw_markets:
                if not isinstance(m, dict):
                    m = getattr(m, "__dict__", m)
                ticker = m.get("ticker", "")
                title = m.get("title", "")
                yes_price = float(m.get("yes_price", 0.5) or 0.5)
                no_price = float(m.get("no_price", 0.5) or 0.5)
                markets.append(PMMarket(
                    event_id=m.get("event_ticker", ""),
                    question=title,
                    slug=ticker.lower(),
                    platform="kalshi",
                    yes_price=yes_price,
                    no_price=no_price,
                    token_id_yes=ticker,
                    token_id_no=f"{ticker}_no",
                    condition_id=m.get("event_ticker", ""),
                    fee_pct=0.07,
                    liquidity=float(m.get("open_interest", 0) or 0),
                    volume=float(m.get("volume", 0) or 0),
                ))
        except Exception as e:
            logger.warning(f"[kalshi_provider] fetch failed: {e}")

        return markets[:limit]

    async def place_order(
        self, token_id: str, side: str, price: float, size: float, idempotency_key: str = ""
    ) -> OrderResult:
        global _breaker_failures
        if _breaker_failures >= _BREAKER_THRESHOLD:
            return OrderResult(status="failed", error="circuit_breaker_open")

        if not self._client:
            return OrderResult(status="failed", error="no_kalshi_client")

        for attempt in range(3):
            try:
                contracts = int(size / price) if price > 0 else 0
                if contracts <= 0:
                    return OrderResult(status="failed", error="zero_contracts")
                result = await self._client.place_order(
                    ticker=token_id,
                    side=side,
                    price=price,
                    count=contracts,
                )
                _breaker_failures = 0
                order_id = str(result.get("order_id", "")) if isinstance(result, dict) else str(getattr(result, "order_id", ""))
                return OrderResult(order_id=order_id, status="filled", fill_price=price)
            except Exception as e:
                if attempt < 2:
                    await asyncio.sleep(0.01 * (2 ** attempt))
                else:
                    _breaker_failures += 1
                    logger.warning(f"[kalshi_provider] place_order failed: {e}")
                    return OrderResult(status="failed", error=str(e))
        return OrderResult(status="failed", error="max_retries")

    async def cancel_order(self, order_id: str) -> bool:
        if not self._client:
            return False
        try:
            await self._client.cancel_order(order_id)
            return True
        except Exception as e:
            logger.warning(f"[kalshi_provider] cancel failed: {e}")
            return False

    def get_fee_schedule(self) -> FeeSchedule:
        return FeeSchedule(taker_fee_pct=0.07, maker_fee_pct=0.0, slippage_bps=10)
