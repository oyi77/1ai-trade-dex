"""Resolution Timing Scanner — extracts bond_scanner's structural edge.

Detects high-probability outcomes near resolution where the market slightly
underprices near-certain events. The edge comes from liquidity providers
wanting to exit positions before resolution, creating a small but consistent
mispricing that can be captured.

Edge model:
  - Markets with YES price in [min_price, max_price] (default 0.85-0.99)
  - Within [min_days, max_days] of resolution
  - Conservative boost: 3% at 0.92 tapering to 1.5% at 0.98
  - Fee-adjusted edge with 0.1% slippage deduction
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import List

from loguru import logger

from backend.config import settings, _cfg
from backend.core.edge.edge_model import Edge, EdgeType
from backend.core.edge.registry import EdgeScannerABC as EdgeScanner
from backend.data.shared_client import get_shared_client

# Risky market keywords to skip — these are too volatile for resolution timing
RISKY_KEYWORDS = [
    "wti", "oil", "crude", "brent", "solana", "sol ", "bitcoin", "btc",
    "ethereum", "eth ", "crypto", "xrp", "doge", "stock", "earnings",
    "macy", "tesla", "apple", "nvidia", "market cap", "price of",
]


class ResolutionTimingScanner(EdgeScanner):
    """Detect resolution-timing edges: high-probability outcomes near resolution."""

    name = "resolution_timing"
    edge_type = EdgeType.RESOLUTION_TIMING
    scan_interval_seconds = 60

    def __init__(self) -> None:
        self.min_price = float(_cfg("BOND_SCANNER_MIN_PRICE", 0.85))
        self.max_price = float(_cfg("BOND_SCANNER_MAX_PRICE", 0.99))
        self.min_volume = float(_cfg("BOND_SCANNER_MIN_VOLUME", 1000))
        self.min_days = float(_cfg("BOND_SCANNER_MIN_DAYS_TO_RESOLUTION", 0.1))
        self.max_days = float(_cfg("BOND_SCANNER_MAX_DAYS_TO_RESOLUTION", 10))
        self.min_edge_pp = float(_cfg("APEX_MIN_EDGE_PP", 0.005))

    async def scan(self, ctx) -> List[Edge]:
        """Scan Gamma API for near-resolution high-probability markets."""
        edges: List[Edge] = []
        now = datetime.now(timezone.utc)

        # Get existing positions to skip duplicates
        existing_tickers = await self._get_existing_tickers(ctx)

        # Fetch markets from Gamma API
        markets = await self._fetch_markets()
        if not markets:
            return edges

        for market in markets:
            try:
                edge = self._evaluate_market(market, now, existing_tickers)
                if edge is not None:
                    edges.append(edge)
            except Exception as e:
                logger.debug(f"[apex:resolution_timing] Market eval failed: {e}")
                continue

        logger.info(f"[apex:resolution_timing] Found {len(edges)} resolution-timing edges")
        return edges

    def _evaluate_market(
        self, market: dict, now: datetime, existing_tickers: set
    ) -> Edge | None:
        """Evaluate a single market for resolution-timing edge."""
        # Skip risky markets
        q = (market.get("question") or "").lower()
        if any(k in q for k in RISKY_KEYWORDS):
            return None

        # Volume filter
        volume = float(market.get("volume", 0) or 0)
        if volume < self.min_volume:
            return None

        # Resolution date filter
        end_date_str = (
            market.get("endDate")
            or market.get("end_date_iso")
            or market.get("endDateIso")
        )
        if not end_date_str:
            return None

        try:
            end_date_str_clean = end_date_str.replace("Z", "+00:00")
            end_dt = datetime.fromisoformat(end_date_str_clean)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return None

        days_to_resolution = (end_dt - now).total_seconds() / 86400.0
        if days_to_resolution > self.max_days or days_to_resolution < self.min_days:
            return None

        # Skip if we already hold a position
        slug = market.get("slug") or market.get("conditionId") or ""
        if slug in existing_tickers:
            return None

        # Get token ID
        clob_token_id = self._extract_token_id(market)
        if not clob_token_id:
            return None

        # Find qualifying outcome price
        outcome_prices_raw = market.get("outcomePrices") or []
        outcomes = market.get("outcomes") or []

        if isinstance(outcome_prices_raw, str):
            try:
                outcome_prices_raw = json.loads(outcome_prices_raw)
            except Exception:
                return None

        if isinstance(outcomes, str):
            try:
                outcomes = json.loads(outcomes)
            except Exception:
                outcomes = []

        if not outcome_prices_raw:
            return None

        qualifying_price = None
        qualifying_outcome = None
        qualifying_index = None
        for i, price_val in enumerate(outcome_prices_raw):
            try:
                price = float(price_val)
            except (TypeError, ValueError):
                continue
            if self.min_price <= price <= self.max_price:
                qualifying_outcome = outcomes[i] if i < len(outcomes) else "yes"
                qualifying_price = price
                qualifying_index = i
                break

        if qualifying_price is None:
            return None

        # Buy the qualifying outcome's own token — outcomePrices[i] is the
        # price of outcomes[i], so the index-matched token is the right one.
        indexed_token = self._extract_token_id(market, index=qualifying_index)
        if indexed_token:
            clob_token_id = indexed_token

        # Calculate edge using conservative boost model
        taper = max(0.0, (qualifying_price - 0.92) / 0.06)
        proximity_boost = 0.03 * (1.0 - 0.5 * taper)
        win_prob = min(qualifying_price + proximity_boost, 0.995)

        # Fee-adjusted edge in percentage points (Edge.edge_pp contract;
        # APEX_MIN_EDGE_PP and the risk manager are on the pp scale).
        raw_edge = win_prob * (1.0 - qualifying_price) - (1.0 - win_prob) * qualifying_price
        edge_pp = round((raw_edge - 0.001) * 100, 2)  # deduct maker fee + slippage

        if edge_pp < self.min_edge_pp:
            return None

        confidence = win_prob
        edge_score = edge_pp * confidence

        # Direction and entry price: we hold the qualifying outcome's token,
        # bought at its own quoted price.
        direction = str(qualifying_outcome).strip().strip("'\"").lower()
        if direction not in ("yes", "no", "up", "down"):
            direction = "yes"
        entry_price = qualifying_price

        # Edge expires when market resolves
        expires_at = end_dt

        return Edge(
            market_id=slug,
            token_id=clob_token_id,
            edge_type=EdgeType.RESOLUTION_TIMING,
            direction=direction,
            entry_price=entry_price,
            fair_price=win_prob,
            edge_pp=edge_pp,
            confidence=confidence,
            edge_score=edge_score,
            time_horizon_min=int(days_to_resolution * 1440),
            metadata={
                "question": market.get("question", ""),
                "volume": volume,
                "days_to_resolution": round(days_to_resolution, 2),
                "qualifying_price": qualifying_price,
                "win_prob": win_prob,
                "proximity_boost": proximity_boost,
                "half_life_seconds": int(days_to_resolution * 86400 * 0.25),
            },
            detected_at=now,
            expires_at=expires_at,
        )

    async def _fetch_markets(self) -> list[dict]:
        """Fetch active markets from Gamma API."""
        gamma_url = f"{settings.GAMMA_API_URL}/markets"
        params = {
            "active": "true",
            "closed": "false",
            "limit": 200,
            "order": "volume",
            "ascending": "false",
        }
        try:
            client = get_shared_client()
            resp = await client.get(gamma_url, params=params, timeout=15.0)
            resp.raise_for_status()
            markets = resp.json()
            return markets if isinstance(markets, list) else []
        except Exception as e:
            logger.warning(f"[apex:resolution_timing] Gamma API fetch failed: {e}")
            return []

    async def _get_existing_tickers(self, ctx) -> set[str]:
        """Get set of market tickers we already hold positions in."""
        try:
            from backend.models.database import Trade
            open_trades = (
                ctx.db.query(Trade)
                .filter(Trade.settled.is_(False), Trade.trading_mode == ctx.mode)
                .all()
            )
            tickers = {t.market_ticker for t in open_trades if t.market_ticker}
            tickers |= {t.event_slug for t in open_trades if t.event_slug}
            return tickers
        except Exception:
            return set()

    @staticmethod
    def _extract_token_id(market: dict, index: int = 0) -> str | None:
        """Extract the CLOB token ID for the outcome at `index`."""
        clob_token_ids = market.get("clobTokenIds") or []
        if isinstance(clob_token_ids, str):
            try:
                clob_token_ids = json.loads(clob_token_ids)
            except Exception:
                return None
        if clob_token_ids and index is not None and index < len(clob_token_ids):
            return str(clob_token_ids[index])
        return None