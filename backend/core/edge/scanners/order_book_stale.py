"""Order Book Stale Scanner — detect stale order books where price hasn't updated.

When a significant real-world event has occurred but the prediction market
order book hasn't moved yet, there's a brief window of edge. This scanner
detects that gap by comparing recent trade price with current best bid/ask.

Edge model:
  - Compare last trade price to current mid-price
  - If divergence exceeds threshold, signal an edge
  - Edge decays quickly (seconds to minutes) as market participants update
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import List

from loguru import logger

from backend.config import settings, _cfg
from backend.core.edge.edge_model import Edge, EdgeType
from backend.core.edge.registry import EdgeScannerABC as EdgeScanner


class OrderBookStaleScanner(EdgeScanner):
    """Detect stale order books where price hasn't caught up to reality."""

    name = "order_book_stale"
    edge_type = EdgeType.ORDER_BOOK_STALE
    scan_interval_seconds = 15  # fast — stale edges decay quickly

    def __init__(self) -> None:
        self.min_divergence_pp = float(_cfg("APEX_STALE_MIN_DIVERGENCE_PP", 0.02))
        self.min_volume = float(_cfg("APEX_STALE_MIN_VOLUME", 500))
        self.max_age_seconds = int(_cfg("APEX_STALE_MAX_AGE_SECONDS", 300))

    async def scan(self, ctx) -> List[Edge]:
        """Scan for stale order books via CLOB data."""
        edges: List[Edge] = []
        now = datetime.now(timezone.utc)

        try:
            clob = ctx.clob
            if clob is None:
                return edges

            # Get markets we're tracking
            markets = await self._get_active_markets(ctx)
            if not markets:
                return edges

            for market in markets[:50]:  # limit to avoid API flood
                try:
                    edge = await self._evaluate_market(market, clob, now)
                    if edge is not None:
                        edges.append(edge)
                except Exception as e:
                    logger.debug(f"[apex:order_book_stale] Market eval failed: {e}")
                    continue
        except Exception as e:
            logger.warning(f"[apex:order_book_stale] Scan failed: {e}")

        logger.info(f"[apex:order_book_stale] Found {len(edges)} stale order book edges")
        return edges

    async def _evaluate_market(self, market: dict, clob, now: datetime) -> Edge | None:
        """Check if a market's order book is stale relative to recent trades."""
        token_id = market.get("token_id") or market.get("clob_token_id")
        if not token_id:
            return None

        slug = market.get("slug") or market.get("conditionId") or ""

        try:
            # Get order book snapshot
            book = await clob.get_order_book(token_id)
            if not book or not book.get("bids") or not book.get("asks"):
                return None

            best_bid = float(book["bids"][0].get("price", 0))
            best_ask = float(book["asks"][0].get("price", 999))
            mid_price = (best_bid + best_ask) / 2.0

            if mid_price <= 0.01 or mid_price >= 0.99:
                return None

            # Get last trade price
            last_trade = await clob.get_last_trade_price(token_id)
            if last_trade is None:
                return None

            last_price = float(last_trade)

            # Divergence between last trade and current mid
            divergence = abs(last_price - mid_price)

            if divergence < self.min_divergence_pp:
                return None

            # Direction: if last trade > mid, market is stale-bid (price should go up)
            direction = "yes" if last_price > mid_price else "no"
            fair_price = last_price  # last trade is closer to true value
            entry_price = mid_price

            # Edge is the divergence, discounted for uncertainty
            confidence = min(divergence / 0.10, 0.7)  # low confidence, scales with divergence
            edge_pp = round(abs(fair_price - entry_price) - 0.002, 4)  # deduct fees

            if edge_pp < 0.005:
                return None

            return Edge(
                market_id=slug,
                token_id=str(token_id),
                edge_type=EdgeType.ORDER_BOOK_STALE,
                direction=direction,
                entry_price=entry_price,
                fair_price=fair_price,
                edge_pp=edge_pp,
                confidence=confidence,
                edge_score=edge_pp * confidence,
                time_horizon_min=5,  # stale edges resolve in minutes
                metadata={
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "mid_price": mid_price,
                    "last_trade_price": last_price,
                    "divergence_pp": round(divergence, 4),
                    "half_life_seconds": 60,  # stale edges decay fast
                },
                detected_at=now,
                expires_at=now + timedelta(minutes=5),
            )
        except Exception as e:
            logger.debug(f"[apex:order_book_stale] Error evaluating {slug}: {e}")
            return None

    async def _get_active_markets(self, ctx) -> list[dict]:
        """Get active markets from context or Gamma API."""
        if hasattr(ctx, "markets") and ctx.markets:
            return ctx.markets

        from backend.data.gamma import fetch_markets
        try:
            markets = await fetch_markets(limit=100, active=True, order="volume")
            return markets or []
        except Exception as e:
            logger.warning(f"[apex:order_book_stale] Gamma fetch failed: {e}")
            return []