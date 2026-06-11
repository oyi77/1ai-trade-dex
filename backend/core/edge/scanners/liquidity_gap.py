"""Liquidity Gap Scanner — detect markets with wide spreads and thin order books.

Wide spreads on prediction markets represent a market-making opportunity:
we can place limit orders inside the spread to capture the spread as profit.
The edge is approximately half the spread, adjusted for adverse selection risk.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import List

from loguru import logger

from backend.config import _cfg
from backend.core.edge.edge_model import Edge, EdgeType
from backend.core.edge.registry import EdgeScannerABC as EdgeScanner


class LiquidityGapScanner(EdgeScanner):
    """Detect markets with wide spreads suitable for limit order placement."""

    name = "liquidity_gap"
    edge_type = EdgeType.LIQUIDITY_GAP
    scan_interval_seconds = 30  # spreads change frequently

    def __init__(self) -> None:
        self.min_spread = float(_cfg("APEX_LIQUIDITY_GAP_MIN_SPREAD", 0.03))
        self.min_volume = float(_cfg("APEX_LIQUIDITY_GAP_MIN_VOLUME", 5000))
        self.min_edge_pp = float(_cfg("APEX_MIN_EDGE_PP", 2.0))

    async def scan(self, ctx) -> List[Edge]:
        """Scan for wide-spread markets with sufficient volume."""
        edges: List[Edge] = []
        now = datetime.now(timezone.utc)

        try:
            clob = ctx.clob
            if clob is None or clob.is_paper:
                # In paper mode, use cached/Gamma data
                markets = await self._fetch_markets()
                for m in markets:
                    edge = self._evaluate_from_market_data(m, now)
                    if edge is not None:
                        edges.append(edge)
            else:
                # Live mode: query order books for active markets
                markets = await self._fetch_markets()
                for m in markets[:30]:  # limit API calls
                    try:
                        edge = await self._evaluate_from_orderbook(m, clob, now)
                        if edge is not None:
                            edges.append(edge)
                    except Exception as e:
                        logger.debug(f"[apex:liquidity_gap] Orderbook eval failed: {e}")
                        continue
        except Exception as e:
            logger.warning(f"[apex:liquidity_gap] Scan failed: {e}")

        logger.info(f"[apex:liquidity_gap] Found {len(edges)} liquidity gap edges")
        return edges

    def _evaluate_from_market_data(self, market: dict, now: datetime) -> Edge | None:
        """Evaluate a market from Gamma API data (no live orderbook)."""
        # Parse spread from outcome prices
        outcome_prices = market.get("outcomePrices", [])
        if isinstance(outcome_prices, str):
            import json
            try:
                outcome_prices = json.loads(outcome_prices)
            except Exception:
                return None

        if not outcome_prices or len(outcome_prices) < 2:
            return None

        try:
            yes_price = float(outcome_prices[0])
            no_price = float(outcome_prices[1])
        except (TypeError, ValueError, IndexError):
            return None

        # Volume filter
        volume = float(market.get("volume", 0) or 0)
        if volume < self.min_volume:
            return None

        # Compute spread estimate
        spread = abs(yes_price + no_price - 1.0)
        if spread < self.min_spread:
            return None

        # Edge: approximately half the spread, reduced by adverse selection risk
        edge_pp = spread * 50 * 0.7  # 70% of half-spread (conservative)
        if edge_pp < self.min_edge_pp:
            return None

        mid_price = yes_price
        direction = "YES" if yes_price > 0.5 else "NO"

        # Confidence scales with volume (more volume = more reliable spread)
        confidence = min(0.3 + 0.3 * min(volume / 50000, 1.0), 0.7)

        slug = market.get("slug") or market.get("conditionId") or ""
        token_id = self._extract_token_id(market)
        if not token_id:
            return None

        return Edge(
            market_id=slug,
            token_id=token_id,
            edge_type=EdgeType.LIQUIDITY_GAP,
            direction=direction,
            entry_price=mid_price,
            fair_price=mid_price + spread * 0.35 if direction == "YES" else mid_price - spread * 0.35,
            edge_pp=edge_pp,
            confidence=confidence,
            edge_score=edge_pp * confidence,
            time_horizon_min=30,  # liquidity gaps are short-duration
            metadata={"spread": spread, "volume": volume, "source": "gamma_api"},
            detected_at=now,
            expires_at=now + timedelta(minutes=15),
        )

    async def _evaluate_from_orderbook(
        self, market: dict, clob, now: datetime
    ) -> Edge | None:
        """Evaluate a market using live order book data."""
        token_id = self._extract_token_id(market)
        if not token_id:
            return None

        try:
            book = await clob.get_order_book(token_id)
            if not book or not book.get("bids") or not book.get("asks"):
                return None

            best_bid = float(book["bids"][0].get("price", 0))
            best_ask = float(book["asks"][0].get("price", 1))
            spread = best_ask - best_bid
            mid = (best_bid + best_ask) / 2.0

            bid_depth = sum(float(b.get("size", 0)) for b in book["bids"][:5])
            ask_depth = sum(float(a.get("size", 0)) for a in book["asks"][:5])

            if spread < self.min_spread or mid <= 0.01 or mid >= 0.99:
                return None

            volume = float(market.get("volume", 0) or 0)
            if volume < self.min_volume:
                return None

            # Edge: half-spread minus adverse selection
            adverse_risk = 0.1 if abs(mid - 0.5) > 0.3 else 0.05
            edge_pp = (spread * 50 * 0.5) - adverse_risk
            if edge_pp < self.min_edge_pp:
                return None

            direction = "YES" if mid > 0.5 else "NO"
            confidence = min(0.4 + 0.2 * min(volume / 50000, 1.0), 0.8)

            slug = market.get("slug") or market.get("conditionId") or ""

            return Edge(
                market_id=slug,
                token_id=str(token_id),
                edge_type=EdgeType.LIQUIDITY_GAP,
                direction=direction,
                entry_price=mid,
                fair_price=mid + spread * 0.25 if direction == "YES" else mid - spread * 0.25,
                edge_pp=edge_pp,
                confidence=confidence,
                edge_score=edge_pp * confidence,
                time_horizon_min=15,
                metadata={
                    "spread": spread,
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "bid_depth": bid_depth,
                    "ask_depth": ask_depth,
                    "volume": volume,
                    "source": "clob_orderbook",
                },
                detected_at=now,
                expires_at=now + timedelta(minutes=10),
            )
        except Exception as e:
            logger.debug(f"[apex:liquidity_gap] Orderbook eval error: {e}")
            return None

    async def _fetch_markets(self) -> list[dict]:
        """Fetch active markets from Gamma API."""
        try:
            from backend.data.gamma import fetch_markets
            markets = await fetch_markets(limit=200, active=True, order="volume")
            return markets or []
        except Exception as e:
            logger.warning(f"[apex:liquidity_gap] Gamma fetch failed: {e}")
            return []

    @staticmethod
    def _extract_token_id(market: dict) -> str | None:
        """Extract CLOB token ID from market data."""
        clob_token_ids = market.get("clobTokenIds") or []
        if isinstance(clob_token_ids, str):
            import json
            try:
                clob_token_ids = json.loads(clob_token_ids)
            except Exception:
                return None
        if clob_token_ids and len(clob_token_ids) > 0:
            return str(clob_token_ids[0])
        return None