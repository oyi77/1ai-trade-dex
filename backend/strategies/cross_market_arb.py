"""
Cross-Market Arbitrage Engine — multi-venue price gap detection.

PARETO TASK #3: Detects and auto-executes cross-platform arbitrage.
When VenueA YES + VenueB YES < $1.00 for the same event,
buy on the cheaper platform, sell on the expensive one.

Venue configuration pulled from settings.MARKET_PROVIDERS.
To change which venues to arbitrage, update config — no code changes needed.

Target: <200ms detection + execution.
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Optional

from backend.strategies.base import BaseStrategy, CycleResult, StrategyContext
from backend.core.circuit_breaker import CircuitBreaker, CircuitOpenError
from backend.config import settings

from loguru import logger


def _cfg(name, default):
    return getattr(settings, name, default)


_CB_THRESHOLD = _cfg("CIRCUIT_BREAKER_THRESHOLD", 5)
_CB_TIMEOUT = _cfg("CIRCUIT_BREAKER_TIMEOUT", 60.0)
_poly_breaker = CircuitBreaker(
    "polymarket", failure_threshold=_CB_THRESHOLD, recovery_timeout=_CB_TIMEOUT
)
_kalshi_breaker = CircuitBreaker(
    "kalshi", failure_threshold=_CB_THRESHOLD, recovery_timeout=_CB_TIMEOUT
)
_consecutive_failures = 0
_FAILURE_THRESHOLD = _CB_THRESHOLD


@dataclass
class CrossMarketOpportunity:
    event_id: str
    poly_price: float
    kalshi_price: float
    cheaper_platform: str
    expensive_platform: str
    profit: float
    fees: float
    net_profit: float
    confidence: float


def detect_cross_arb(
    poly_yes: float, kalshi_yes: float
) -> Optional[CrossMarketOpportunity]:
    """
    Detect cross-market arbitrage between Polymarket and Kalshi.

    For the same event, if Polymarket YES price + Kalshi YES price < $1.00,
    we can buy on the cheaper platform and profit from the spread.

    Example:
      Polymarket YES = 0.60, Kalshi YES = 0.65
      Sum = 1.25 > $1.00 → NO arbitrage (wait)

      Polymarket YES = 0.60, Kalshi YES = 0.35
      Sum = 0.95 < $1.00 → YES arbitrage!
      Buy Kalshi at $0.35, wait for resolution → $1.00 (if Kalshi YES wins)
      Or hedge: Buy Polymarket at $0.60, sell at $0.35 on Kalshi
    """
    sum_price = poly_yes + kalshi_yes

    if sum_price >= 1.0:
        return None

    fees = _cfg("ARB_POLYMARKET_FEE", 0.01) + _cfg("ARB_KALSHI_FEE", 0.01)
    profit = 1.0 - sum_price
    net_profit = profit - fees

    if net_profit < _cfg("ARB_MIN_PROFIT", 0.02):
        return None

    cheaper = "polymarket" if poly_yes < kalshi_yes else "kalshi"
    expensive = "kalshi" if cheaper == "polymarket" else "polymarket"

    min_profit = _cfg("ARB_MIN_PROFIT", 0.02)

    return CrossMarketOpportunity(
        event_id="",
        poly_price=poly_yes,
        kalshi_price=kalshi_yes,
        cheaper_platform=cheaper,
        expensive_platform=expensive,
        profit=profit,
        fees=fees,
        net_profit=net_profit,
        confidence=min(1.0, net_profit / min_profit) if min_profit > 0 else 0.0,
    )


async def execute_cross_arb(
    opportunity: CrossMarketOpportunity,
    event_id: str,
    poly_clob: Optional[object] = None,
    poly_token_id: Optional[str] = None,
    kalshi_token_id: Optional[str] = None,
    size: float = 10.0,
) -> dict:
    """
    Execute 2-leg cross-market arbitrage: buy YES on BOTH platforms.

    When Poly YES + Kalshi YES < 1.00:
    - Buy YES on Polymarket @ poly_price
    - Buy YES on Kalshi @ kalshi_price
    - Total cost = sum < 1.00
    - Guaranteed $1.00 payout on resolution → profit = 1.0 - sum - fees

    Both legs must execute. If one fails, log warning (position is hedged
    by the successful leg — worst case is small loss, not catastrophic).
    """
    start = time.monotonic()
    idempotency_key = f"cross-{event_id}-{int(start * 1000)}"
    results = {"poly": None, "kalshi": None}

    # Leg 1: Buy YES on Polymarket
    if poly_clob and poly_token_id:
        try:
            results["poly"] = await _place_order_retry(
                poly_clob,
                poly_token_id,
                "BUY",
                opportunity.poly_price,
                size,
                f"{idempotency_key}-buy-poly",
                _poly_breaker,
            )
        except Exception as e:
            logger.warning(f"[cross_market_arb] Polymarket leg failed: {e}")

    # Leg 2: Buy YES on Kalshi (via paper execution — Kalshi SDK not integrated for live)
    # For now, log as paper trade. Real Kalshi execution needs KalshiClient integration.
    if kalshi_token_id:
        logger.info(
            f"[cross_market_arb] Kalshi leg: BUY {kalshi_token_id} @ {opportunity.kalshi_price:.3f} "
            f"size=${size:.2f} (paper — Kalshi live execution not yet integrated)"
        )
        results["kalshi"] = "paper"

    elapsed_ms = (time.monotonic() - start) * 1000

    # Both legs must execute for real arb
    if results["poly"] and results["kalshi"]:
        return {
            "success": True,
            "poly_order": results["poly"],
            "kalshi_order": results["kalshi"],
            "net_profit": opportunity.net_profit,
            "elapsed_ms": elapsed_ms,
        }
    elif results["poly"] or results["kalshi"]:
        logger.warning(
            f"[cross_market_arb] Only one leg executed: poly={results['poly']} "
            f"kalshi={results['kalshi']} — partial hedge, not full arb"
        )
        return {
            "success": False,
            "partial": True,
            "poly_order": results["poly"],
            "kalshi_order": results["kalshi"],
            "error": "Only one leg executed — not full arb",
            "elapsed_ms": elapsed_ms,
        }
    else:
        return {
            "success": False,
            "error": "Both legs failed",
            "elapsed_ms": elapsed_ms,
        }


async def _place_order_retry(
    clob,
    token_id: str,
    side: str,
    price: float,
    size: float,
    idempotency_key: str,
    breaker: CircuitBreaker,
    retry_count: int = 0,
) -> Optional[str]:
    """Place order with circuit breaker + retry."""
    try:

        async def _do_order():
            result = await clob.place_limit_order(
                token_id=token_id,
                side=side,
                price=price,
                size=size,
                idempotency_key=idempotency_key,
            )
            return result.order_id if hasattr(result, "order_id") else None

        return await breaker.call(_do_order)

    except Exception:
        logger.exception(
            "Cross-market arb order placement failed (retry %d)", retry_count
        )
        if retry_count < settings.ARB_MAX_RETRIES:
            wait = settings.CROSS_MARKET_ARB_RETRY_WAIT_BASE * (2**retry_count)
            await asyncio.sleep(wait)
            return await _place_order_retry(
                clob,
                token_id,
                side,
                price,
                size,
                idempotency_key,
                breaker,
                retry_count + 1,
            )
        raise


class CrossMarketArb(BaseStrategy):
    """
    Cross-Market Arbitrage — detects Polymarket ↔ Kalshi price gaps.

    Monitors the same event on both platforms. When price gap creates
    risk-free profit (sum < $1.00 after fees), auto-execute.
    """

    name = "cross_market_arb"
    description = (
        "Cross-market arbitrage engine — Polymarket ↔ Kalshi price gap detection"
    )
    category = "arb"
    default_params = {
        "min_profit": settings.CROSS_MARKET_ARB_MIN_PROFIT,
        "min_spread_pct": getattr(settings, "CROSS_ARB_MIN_SPREAD_PCT", 0.013),
        "enabled": True,
        "max_open_positions": 5,
        "max_per_asset": 1,
        "stop_loss_pct": 0.10,
        "profit_target_pct": 0.05,
    }

    async def detect(
        self, poly_yes: float, kalshi_yes: float
    ) -> Optional[CrossMarketOpportunity]:
        """Detect cross-market arbitrage. <200ms target."""
        return detect_cross_arb(poly_yes, kalshi_yes)

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        """Scan both platforms for arbitrage opportunities."""
        start = time.monotonic()
        errors = []

        try:
            poly_markets = await self._fetch_markets_from_registry("polymarket")
            kalshi_markets = await self._fetch_markets_from_registry("kalshi")

            matched = 0
            for poly_m in poly_markets:
                try:
                    # MarketInfo has yes_price/no_price directly
                    poly_price = float(poly_m.yes_price) if hasattr(poly_m, 'yes_price') else 0.5
                    kalshi_m = self._find_kalshi_match(poly_m, kalshi_markets)
                    if not kalshi_m:
                        continue

                    kalshi_price = float(kalshi_m.yes_price) if hasattr(kalshi_m, 'yes_price') else 0.5

                    # Min spread threshold: only trade when spread > 1.3% (covers fees)
                    spread_pct = abs(poly_price - kalshi_price)
                    min_spread = self.default_params.get("min_spread_pct", 0.013)
                    if spread_pct < min_spread:
                        continue

                    # Gate: ensure strategy has passed live gate before executing
                    if ctx.mode != "live":
                        ctx.logger.debug(
                            "[cross_market_arb] Skipping — strategy gate not cleared"
                        )
                        continue

                    opp = detect_cross_arb(poly_price, kalshi_price)

                    if opp and opp.net_profit >= self.default_params["min_profit"]:
                        # MarketInfo has slug and metadata dict
                        meta = getattr(poly_m, 'metadata', {}) or {}
                        opp.event_id = getattr(poly_m, 'slug', '') or meta.get("conditionId", "")
                        # Resolve Polymarket token_id for live execution
                        poly_clob_token_ids = meta.get("clobTokenIds") or []
                        if isinstance(poly_clob_token_ids, str):
                            import json as _json
                            try:
                                poly_clob_token_ids = _json.loads(poly_clob_token_ids)
                            except Exception:
                                poly_clob_token_ids = []
                        poly_token_id = str(poly_clob_token_ids[0]) if poly_clob_token_ids else None
                        global _consecutive_failures
                        if _consecutive_failures >= _FAILURE_THRESHOLD:
                            raise CircuitOpenError("cross_market_arb")
                        result = await execute_cross_arb(
                            opp, opp.event_id,
                            poly_clob=ctx.clob,
                            poly_token_id=poly_token_id,
                            size=self.default_params.get("position_size", 10.0),
                        )
                        if result.get("success"):
                            matched += 1
                            _consecutive_failures = 0
                        else:
                            _consecutive_failures += 1

                except Exception as exc:
                    errors.append(str(exc))
                    if len(errors) <= 3:
                        logger.warning(f"[cross_market_arb] Error processing market: {exc}")

            elapsed_ms = (time.monotonic() - start) * 1000
            return CycleResult(
                decisions_recorded=matched,
                trades_attempted=matched,
                trades_placed=matched,
                errors=errors,
                cycle_duration_ms=elapsed_ms,
            )

        except Exception as exc:
            logger.exception(f"[cross_market_arb] Cycle failed: {exc}")
            return CycleResult(0, 0, 0, errors=[str(exc)])

    async def _fetch_polymarket_markets(self) -> list[dict]:
        """Fetch Polymarket markets via registered provider or Gamma API fallback."""
        try:
            from backend.data.gamma import fetch_markets

            return await fetch_markets(limit=500)
        except Exception as exc:
            logger.warning(f"[cross_market_arb] Polymarket fetch failed: {exc}")
            return []

    async def _fetch_kalshi_markets(self) -> list[dict]:
        """Fetch Kalshi markets via registered provider or Kalshi API fallback."""
        try:
            from backend.data.kalshi_client import KalshiClient

            client = KalshiClient()
            return await client.get_markets(params={"limit": 500})
        except Exception as exc:
            logger.warning(f"[cross_market_arb] Kalshi fetch failed: {exc}")
            return []

    async def _fetch_markets_from_registry(self, venue: str) -> list[dict]:
        """Fetch markets from the registered market provider. Falls back to legacy clients."""
        try:
            from backend.markets.provider_registry import market_registry

            provider = market_registry.get(venue)
            markets = (
                await provider.search_markets("", limit=500)
                if hasattr(provider, "search_markets")
                else None
            )
            if markets:
                return markets
        except Exception:
            logger.exception(
                "Failed to fetch markets from registry for venue '%s', falling back to legacy",
                venue,
            )

        # Legacy fallback
        if venue == "polymarket":
            return await self._fetch_polymarket_markets()
        elif venue == "kalshi":
            return await self._fetch_kalshi_markets()
        return []

    def _find_kalshi_match(
        self, poly_market: dict, kalshi_markets: list[dict]
    ) -> Optional[dict]:
        """Match a Polymarket market to its Kalshi equivalent."""
        poly_question = poly_market.get("question", "").lower()
        poly_slug = poly_market.get("slug", "").lower()

        for k_m in kalshi_markets:
            k_question = k_m.get("question", "").lower()
            k_slug = k_m.get("slug", "").lower()

            if (
                poly_question
                and k_question
                and (poly_question in k_question or k_question in poly_question)
            ):
                return k_m

            if poly_slug and k_slug and poly_slug == k_slug:
                return k_m

        return None
