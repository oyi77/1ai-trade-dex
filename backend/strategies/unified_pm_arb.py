"""
Unified PM Arbitrage Strategy — Polymarket + Kalshi cross-platform arb detection.

Uses the proven CrossMarketArbEnhanced detector (same engine as arb_scanner.py,
which has a +$160 / 23-trade track record). Fetches Polymarket + Kalshi markets,
scans for cross-platform arbitrage opportunities, and returns decisions via
CycleResult for the strategy executor pipeline.

Does NOT self-execute — the executor handles order placement, sizing, risk gates,
and position tracking.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, List, Optional

from loguru import logger

from backend.strategies.base import BaseStrategy, CycleResult, StrategyContext
from backend.strategies.cross_market_arb_enhanced import CrossMarketArbEnhanced


class UnifiedPMArb(BaseStrategy):
    """Polymarket + Kalshi cross-platform arbitrage detection.

    Fetches markets from both providers, runs CrossMarketArbEnhanced.scan_all_providers(),
    and returns detected opportunities as decisions for the executor pipeline.
    """

    name = "unified_arb"
    description = (
        "Polymarket + Kalshi cross-platform arb detection via CrossMarketArbEnhanced"
    )
    category = "arb"

    default_params: dict = {
        "min_net_edge": 0.005,
        "max_opportunities_per_cycle": 10,
        "enabled": True,
    }

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._detector: Optional[CrossMarketArbEnhanced] = None
        self._history: List[Dict] = []

    # ------------------------------------------------------------------
    # Market filtering (pass-through — we fetch our own markets)
    # ------------------------------------------------------------------

    @staticmethod
    def market_filter(markets):
        return markets

    # ------------------------------------------------------------------
    # Market fetching
    # ------------------------------------------------------------------

    async def _fetch_polymarket(self) -> List[Dict[str, Any]]:
        """Fetch Polymarket markets via Gamma API."""
        try:
            from backend.data.gamma import fetch_markets

            markets = await fetch_markets(limit=200)
            from backend.data.arb_opportunity_scanner import _normalize_pm_markets

            return _normalize_pm_markets(markets, "polymarket", fee_pct=0.02)
        except Exception:
            logger.warning("[unified_arb] Polymarket fetch failed")
            return []

    async def _fetch_kalshi(self) -> List[Dict[str, Any]]:
        """Fetch Kalshi markets."""
        try:
            from backend.data.arb_opportunity_scanner import _normalize_kalshi_markets
            from backend.data.kalshi_client import KalshiClient

            client = KalshiClient()
            response = await client.get_markets(params={"limit": 200, "status": "open"})
            raw = response.get("markets", []) if isinstance(response, dict) else []
            return _normalize_kalshi_markets(raw)
        except Exception:
            logger.warning("[unified_arb] Kalshi fetch failed")
            return []

    async def _fetch_limitless(self) -> List[Dict[str, Any]]:
        """Fetch Limitless markets."""
        try:
            from backend.data.arb_opportunity_scanner import _normalize_limitless_markets
            from backend.clients.limitless_client import LimitlessClient

            client = LimitlessClient()
            markets = await asyncio.wait_for(client.get_markets(limit=200), timeout=15)
            return _normalize_limitless_markets(markets or [], fee_pct=0.02)
        except Exception:
            logger.warning("[unified_arb] Limitless fetch failed")
            return []

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    async def _get_detector(self) -> CrossMarketArbEnhanced:
        if self._detector is None:
            min_edge = self.default_params.get("min_net_edge", 0.01)
            self._detector = CrossMarketArbEnhanced(min_net_profit_pct=min_edge)
        return self._detector

    # ------------------------------------------------------------------
    # Main cycle
    # ------------------------------------------------------------------

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        start = time.monotonic()
        decisions: List[Dict] = []

        # 1. Fetch markets from Polymarket + Kalshi + Limitless in parallel
        pm_markets, kalshi_markets, limitless_markets = await asyncio.gather(
            self._fetch_polymarket(),
            self._fetch_kalshi(),
            self._fetch_limitless(),
            return_exceptions=True,
        )
        if isinstance(pm_markets, Exception):
            logger.warning(f"[unified_arb] PM fetch exception: {pm_markets}")
            pm_markets = []
        if isinstance(kalshi_markets, Exception):
            logger.warning(f"[unified_arb] Kalshi fetch exception: {kalshi_markets}")
            kalshi_markets = []
        if isinstance(limitless_markets, Exception):
            logger.warning(f"[unified_arb] Limitless fetch exception: {limitless_markets}")
            limitless_markets = []

        all_markets: Dict[str, List[Dict]] = {}
        if pm_markets:
            all_markets["polymarket"] = pm_markets
        if kalshi_markets:
            all_markets["kalshi"] = kalshi_markets
        if limitless_markets:
            all_markets["limitless"] = limitless_markets

        if not all_markets:
            return CycleResult(
                0, 0, 0, errors=["No markets available from Polymarket or Kalshi"]
            )

        # 2. Detect arbitrage opportunities
        detector = await self._get_detector()
        result = detector.scan_all_providers(all_markets)

        # 3. Build decisions from opportunities
        max_per_cycle = self.default_params.get("max_opportunities_per_cycle", 10)
        for idx, opp in enumerate(result.opportunities[:max_per_cycle]):
            size_usd = getattr(opp, "size_usd", None) or 10.0
            _uniq_suffix = (
                f"{opp.platform_a}:{opp.platform_b}:{opp.price_a:.4f}:"
                f"{opp.price_b:.4f}:{opp.kind}:{idx}"
            )
            _cid = opp.event_id or _uniq_suffix
            decision = {
                "kind": opp.kind,
                "decision": "BUY",
                "direction": "YES",
                "condition_id": _cid,
                "market_ticker": _cid,
                "platform_a": opp.platform_a,
                "platform_b": opp.platform_b,
                "price_a": opp.price_a,
                "price_b": opp.price_b,
                "net_profit": opp.net_profit,
                "net_profit_pct": opp.net_profit_pct,
                "confidence": opp.confidence,
                "raw_spread": opp.raw_spread,
                "fees": opp.fees,
                "slippage_cost": opp.slippage_cost,
                "execution_risk": opp.execution_risk,
                "details": opp.details,
                "size": size_usd,
                "market_type": "arb",
                "model_probability": min(1.0, 0.5 + opp.net_profit_pct),
            }
            decisions.append(decision)

            # Record history
            self._history.append(
                {
                    "event_id": opp.event_id,
                    "kind": opp.kind,
                    "platform_a": opp.platform_a,
                    "platform_b": opp.platform_b,
                    "price_a": opp.price_a,
                    "price_b": opp.price_b,
                    "net_profit": opp.net_profit,
                    "status": "detected",
                    "timestamp": time.time(),
                }
            )

            # Log to DecisionLog
            try:
                from backend.models.database import DecisionLog

                log_row = DecisionLog(
                    strategy=self.name,
                    market_ticker=(opp.event_id or _uniq_suffix)[:64],
                    decision="ARB",
                    confidence=opp.confidence,
                    signal_data=json.dumps(decision),
                    reason=(
                        f"{opp.kind}: {opp.platform_a}@{opp.price_a:.3f} vs "
                        f"{opp.platform_b}@{opp.price_b:.3f} | "
                        f"net={opp.net_profit_pct:.2%} edge"
                    ),
                )
                ctx.db.add(log_row)
            except Exception:
                logger.warning("unified_arb: failed to log arbitrage opportunity to DB")

        # 4. Commit DB writes
        try:
            ctx.db.commit()
        except Exception:
            logger.warning("[unified_arb] DB commit failed, rolling back")
            ctx.db.rollback()

        # Trim history
        if len(self._history) > 500:
            self._history = self._history[-500:]

        elapsed = (time.monotonic() - start) * 1000
        logger.info(
            f"[unified_arb] {result.markets_scanned} markets, "
            f"{len(decisions)} opportunities in {elapsed:.0f}ms"
        )

        return CycleResult(
            decisions_recorded=len(decisions),
            trades_attempted=len(decisions),
            trades_placed=0,
            decisions=decisions,
            cycle_duration_ms=elapsed,
            markets_scanned=result.markets_scanned,
        )

    # ------------------------------------------------------------------
    # History access
    # ------------------------------------------------------------------

    def get_history(self, limit: int = 100) -> List[Dict]:
        """Return recent arb detection history."""
        return self._history[-limit:]
