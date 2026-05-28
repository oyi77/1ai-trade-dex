"""
Unified Prediction-Market Arbitrage Strategy.

Replaces cross_market_arb.py, arb_scanner.py, and hft_cross_arb.py with a single
strategy that uses the market provider registry for all I/O.

Detection: CrossMarketArbEnhanced (unchanged)
Execution: provider.place_order(NormalizedOrder) via market_registry
Sizing: Kelly criterion (fractional, from hft_cross_arb)
Safety: Per-venue circuit breakers + atomic 2-leg with emergency cancel
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from backend.config import settings
from backend.core.circuit_breaker import CircuitBreaker, CircuitOpenError
from backend.markets.order_types import (
    NormalizedOrder,
    NormalizedOrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
)
from backend.strategies.base import (
    BaseStrategy,
    CycleResult,
    MarketInfo,
    StrategyContext,
)
from backend.strategies.cross_market_arb_enhanced import (
    ArbOpportunityEnhanced,
    CrossMarketArbEnhanced,
)


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def _cfg(name: str, default: Any = None) -> Any:
    return getattr(settings, name, default)


# PM-only venues (no DEX)
_PM_VENUES: List[str] = [
    "polymarket",
    "kalshi",
    "sxbet",
    "limitless",
    "myriad",
    "predict_fun",
    "bookmaker_xyz",
]

# Fee map per venue (fraction)
_FEE_MAP: Dict[str, float] = {
    "polymarket": 0.02,
    "kalshi": 0.07,
    "sxbet": 0.02,
    "myriad": 0.02,
    "predict_fun": 0.02,
    "bookmaker_xyz": 0.02,
    "limitless": 0.02,
}


# ---------------------------------------------------------------------------
# MarketInfo-to-dict bridge for CrossMarketArbEnhanced
# ---------------------------------------------------------------------------

def _normalize_market_info(m: Any, venue: str) -> dict:
    """Convert a MarketInfo dataclass (from provider) to the dict format
    expected by CrossMarketArbEnhanced.scan_all_providers()."""
    raw = m.raw if hasattr(m, "raw") and m.raw else {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = {}

    # Resolve clobTokenIds from raw
    clob_ids = raw.get("clobTokenIds") or []
    if isinstance(clob_ids, str):
        try:
            clob_ids = json.loads(clob_ids)
        except Exception:
            clob_ids = []

    # Extract prices — MarketInfo uses Decimal
    yes_price = None
    no_price = None
    try:
        yp = getattr(m, "yes_price", None)
        if yp is not None:
            yp_f = float(yp)
            if 0 < yp_f < 1:
                yes_price = yp_f
    except (ValueError, TypeError):
        pass
    try:
        np_ = getattr(m, "no_price", None)
        if np_ is not None:
            np_f = float(np_)
            if 0 < np_f < 1:
                no_price = np_f
    except (ValueError, TypeError):
        pass

    title = getattr(m, "title", "") or ""
    market_id = str(getattr(m, "market_id", ""))
    volume_24h = getattr(m, "volume_24h", 0)
    open_interest = getattr(m, "open_interest", 0)

    return {
        "question": title,
        "event_id": market_id,
        "yes_price": yes_price,
        "no_price": no_price,
        "platform": venue,
        "fee_pct": _FEE_MAP.get(venue, 0.02),
        "liquidity": float(open_interest or 0),
        "volume": float(volume_24h or 0),
        "clobTokenIds": clob_ids,
        "_raw": raw,
    }


# ---------------------------------------------------------------------------
# Kelly criterion sizing (identical to hft_cross_arb._kelly_size)
# ---------------------------------------------------------------------------

def _kelly_size(
    edge: float,
    odds: float = 1.0,
    bankroll: float = 1000.0,
    max_size: float = 200.0,
    kelly_fraction: float = 0.25,
) -> float:
    """Calculate Kelly-criterion position size for an arb edge.

    Uses fractional Kelly (default 25%) to reduce variance.
    For arb: edge is the guaranteed net profit per dollar, odds is 1:1.
    """
    if edge <= 0 or bankroll <= 0:
        return 0.0
    # Kelly: f* = (bp - q) / b where b=odds, p=prob of win, q=1-p
    # For arb (guaranteed): p ~= 1, so f* = edge / odds
    kelly = (edge / odds) * kelly_fraction
    size = kelly * bankroll
    return max(0.0, min(size, max_size))


# ---------------------------------------------------------------------------
# Unified PM Arbitrage Strategy
# ---------------------------------------------------------------------------

class UnifiedPMArb(BaseStrategy):
    """Single prediction-market arbitrage strategy.

    Scans all registered PM venues via market_registry, detects arb using
    CrossMarketArbEnhanced, and executes atomically via provider.place_order().
    """

    name = "unified_pm_arb"
    description = "Unified PM arbitrage: multi-venue scan + Kelly sizing + atomic execution"
    category = "arb"

    default_params: dict = {
        "max_exposure": 200.0,
        "min_net_edge": 0.02,
        "kelly_fraction": 0.25,
        "slippage_bps": 5.0,
        "max_opportunities_per_cycle": 10,
        "enabled": True,
        "max_open_positions": 5,
        "max_per_asset": 1,
        "stop_loss_pct": 0.10,
        "profit_target_pct": 0.05,
    }

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._history: List[dict] = []

    # ------------------------------------------------------------------
    # Circuit breaker per venue
    # ------------------------------------------------------------------

    def _get_breaker(self, venue: str) -> CircuitBreaker:
        if venue not in self._breakers:
            self._breakers[venue] = CircuitBreaker(
                f"pm_arb_{venue}",
                failure_threshold=_cfg("ARB_CIRCUIT_BREAKER_THRESHOLD", 5),
                recovery_timeout=_cfg("ARB_CIRCUIT_BREAKER_TIMEOUT", 60.0),
            )
        return self._breakers[venue]

    # ------------------------------------------------------------------
    # Market fetching via providers
    # ------------------------------------------------------------------

    async def _fetch_all_pm_markets(
        self, ctx: StrategyContext
    ) -> Dict[str, List[dict]]:
        """Fetch markets from all PM venues via market_registry providers."""
        all_markets: Dict[str, List[dict]] = {}

        tasks = {}
        for venue in _PM_VENUES:
            provider = ctx.get_market_provider(venue)
            if provider is None:
                all_markets[venue] = []
                continue
            tasks[venue] = self._fetch_venue_markets(provider, venue)

        if tasks:
            results = await asyncio.gather(
                *tasks.values(), return_exceptions=True
            )
            for venue, result in zip(tasks.keys(), results):
                if isinstance(result, Exception):
                    logger.warning(f"[unified_pm_arb] {venue} fetch failed: {result}")
                    all_markets[venue] = []
                else:
                    all_markets[venue] = result
        return all_markets

    async def _fetch_venue_markets(
        self, provider: Any, venue: str
    ) -> List[dict]:
        """Fetch and normalize markets from a single provider."""
        try:
            raw = await asyncio.wait_for(
                provider.search_markets("", limit=500),
                timeout=30.0,
            )
            normalized = [_normalize_market_info(m, venue) for m in (raw or [])]
            logger.debug(f"[unified_pm_arb] {venue}: {len(normalized)} markets")
            return normalized
        except asyncio.TimeoutError:
            logger.warning(f"[unified_pm_arb] {venue} timed out (30s)")
            return []
        except Exception as exc:
            logger.warning(f"[unified_pm_arb] {venue} fetch failed: {exc}")
            return []

    # ------------------------------------------------------------------
    # Detection (delegates to CrossMarketArbEnhanced)
    # ------------------------------------------------------------------

    def _detect_opportunities(
        self, all_markets: Dict[str, List[dict]], min_edge: float
    ) -> List[ArbOpportunityEnhanced]:
        """Run CrossMarketArbEnhanced scan and filter by min_edge."""
        detector = CrossMarketArbEnhanced(
            slippage_bps=self.default_params.get("slippage_bps", 5.0),
        )
        scan_result = detector.scan_all_providers(all_markets)
        opportunities = [
            opp
            for opp in scan_result.opportunities
            if opp.kind in ("cross_platform_arb", "yes_no_sum", "multi_outcome")
            and opp.net_profit >= min_edge
        ]
        return opportunities

    # ------------------------------------------------------------------
    # Kelly sizing
    # ------------------------------------------------------------------

    def _calculate_size(
        self, opp: ArbOpportunityEnhanced, bankroll: float
    ) -> float:
        """Calculate position size using Kelly criterion."""
        max_exposure = self.default_params.get("max_exposure", 200.0)
        kelly_fraction = self.default_params.get("kelly_fraction", 0.25)
        min_order = _cfg("MIN_ORDER_USDC", 5.0)

        size = _kelly_size(
            edge=opp.net_profit,
            bankroll=bankroll,
            max_size=max_exposure,
            kelly_fraction=kelly_fraction,
        )
        if size < min_order:
            return 0.0
        return round(size, 2)

    # ------------------------------------------------------------------
    # Atomic 2-leg execution via providers
    # ------------------------------------------------------------------

    async def _execute_arb(
        self,
        ctx: StrategyContext,
        opp: ArbOpportunityEnhanced,
        bankroll: float,
    ) -> dict:
        """Execute both legs atomically via provider.place_order().

        Returns status dict: {"status": "filled"|"partial"|"failed"|"skipped", ...}
        """
        size = self._calculate_size(opp, bankroll)
        if size <= 0:
            return {"status": "skipped", "reason": "size_below_minimum"}

        # Resolve providers
        provider_a = ctx.get_market_provider(opp.platform_a)
        provider_b = ctx.get_market_provider(opp.platform_b)
        if provider_a is None or provider_b is None:
            return {
                "status": "skipped",
                "reason": f"provider_missing: a={opp.platform_a} b={opp.platform_b}",
            }

        # Build normalized orders
        token_a = opp.details.get("token_id_a") or opp.token_id or opp.market_a_id
        token_b = opp.details.get("token_id_b") or opp.market_b_id

        arb_id = str(uuid.uuid4())[:8]
        order_a = NormalizedOrder(
            market_id=str(token_a),
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            size=Decimal(str(round(size, 2))),
            price=Decimal(str(round(opp.price_a, 4))),
            client_order_id=f"arb-{arb_id}-a",
        )
        order_b = NormalizedOrder(
            market_id=str(token_b),
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            size=Decimal(str(round(size, 2))),
            price=Decimal(str(round(opp.price_b, 4))),
            client_order_id=f"arb-{arb_id}-b",
        )

        # Atomic execution: both legs in parallel
        start = time.monotonic()
        result_a, result_b = await asyncio.gather(
            self._place_with_breaker(provider_a, order_a, opp.platform_a),
            self._place_with_breaker(provider_b, order_b, opp.platform_b),
            return_exceptions=True,
        )

        a_ok = (
            isinstance(result_a, NormalizedOrderResult)
            and result_a.status == OrderStatus.FILLED
        )
        b_ok = (
            isinstance(result_b, NormalizedOrderResult)
            and result_b.status == OrderStatus.FILLED
        )

        elapsed_ms = (time.monotonic() - start) * 1000

        if a_ok and b_ok:
            profit = opp.net_profit * size
            logger.info(
                f"[unified_pm_arb] FILLED arb={arb_id} "
                f"{opp.platform_a}@{opp.price_a:.3f} + "
                f"{opp.platform_b}@{opp.price_b:.3f} "
                f"profit=${profit:.4f} ({elapsed_ms:.0f}ms)"
            )
            return {"status": "filled", "profit": profit, "arb_id": arb_id}

        elif a_ok and not b_ok:
            # Leg A filled, leg B failed — emergency cancel A
            order_id_a = result_a.venue_order_id if isinstance(result_a, NormalizedOrderResult) else str(result_a)
            await self._emergency_cancel(provider_a, order_id_a, arb_id)
            error = f"leg_b_failed: {result_b}"
            logger.warning(f"[unified_pm_arb] PARTIAL arb={arb_id}: {error}")
            return {"status": "partial", "error": error, "arb_id": arb_id}

        elif not a_ok and b_ok:
            # Leg B filled, leg A failed — emergency cancel B
            order_id_b = result_b.venue_order_id if isinstance(result_b, NormalizedOrderResult) else str(result_b)
            await self._emergency_cancel(provider_b, order_id_b, arb_id)
            error = f"leg_a_failed: {result_a}"
            logger.warning(f"[unified_pm_arb] PARTIAL arb={arb_id}: {error}")
            return {"status": "partial", "error": error, "arb_id": arb_id}

        else:
            error_a = str(result_a) if isinstance(result_a, Exception) else str(result_a)
            error_b = str(result_b) if isinstance(result_b, Exception) else str(result_b)
            logger.warning(
                f"[unified_pm_arb] FAILED arb={arb_id}: "
                f"a={error_a} b={error_b}"
            )
            return {"status": "failed", "error": f"both_failed: a={error_a}, b={error_b}"}

    # ------------------------------------------------------------------
    # Order placement with circuit breaker
    # ------------------------------------------------------------------

    async def _place_with_breaker(
        self,
        provider: Any,
        order: NormalizedOrder,
        venue: str,
    ) -> NormalizedOrderResult:
        """Place order wrapped in venue circuit breaker."""
        breaker = self._get_breaker(venue)
        return await breaker.call(provider.place_order, order)

    # ------------------------------------------------------------------
    # Emergency cancel
    # ------------------------------------------------------------------

    async def _emergency_cancel(
        self, provider: Any, order_id: str, arb_id: str
    ) -> None:
        """Cancel an order after the other leg failed."""
        try:
            if hasattr(provider, "cancel_order"):
                await provider.cancel_order(order_id)
                logger.warning(
                    f"[unified_pm_arb] EMERGENCY CANCEL order={order_id} arb={arb_id}"
                )
            else:
                logger.error(
                    f"[unified_pm_arb] Cannot cancel order={order_id}: "
                    f"provider has no cancel_order"
                )
        except Exception as exc:
            logger.error(
                f"[unified_pm_arb] Cancel failed order={order_id} arb={arb_id}: {exc}"
            )

    # ------------------------------------------------------------------
    # Main cycle
    # ------------------------------------------------------------------

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        """Scan all PM venues, detect arbs, execute atomically."""
        start = time.monotonic()
        errors: List[str] = []
        trades_placed = 0

        try:
            # 1. Fetch markets from all PM venues
            all_markets = await self._fetch_all_pm_markets(ctx)
            total_markets = sum(len(v) for v in all_markets.values())
            if total_markets == 0:
                return CycleResult(0, 0, 0, errors=["No markets available"])

            # 2. Detect opportunities
            min_edge = self.default_params.get("min_net_edge", 0.02)
            opportunities = self._detect_opportunities(all_markets, min_edge)
            if not opportunities:
                elapsed = (time.monotonic() - start) * 1000
                return CycleResult(
                    0, 0, 0,
                    cycle_duration_ms=elapsed,
                    markets_scanned=total_markets,
                )

            # 3. Limit per cycle
            max_per_cycle = self.default_params.get("max_opportunities_per_cycle", 10)
            opportunities = opportunities[:max_per_cycle]

            # 4. Execute
            bankroll = ctx.bankroll if ctx.bankroll > 0 else 1000.0
            for opp in opportunities:
                try:
                    result = await self._execute_arb(ctx, opp, bankroll)
                    status = result.get("status", "unknown")
                    if status == "filled":
                        trades_placed += 1
                    elif status in ("partial", "failed"):
                        errors.append(result.get("error", f"arb_{status}"))

                    # Record history
                    self._history.append({
                        "event_id": opp.event_id,
                        "kind": opp.kind,
                        "platform_a": opp.platform_a,
                        "platform_b": opp.platform_b,
                        "price_a": opp.price_a,
                        "price_b": opp.price_b,
                        "net_profit": opp.net_profit,
                        "status": status,
                        "timestamp": time.time(),
                    })
                except CircuitOpenError as exc:
                    logger.warning(f"[unified_pm_arb] Circuit breaker open: {exc}")
                    errors.append(str(exc))
                except Exception as exc:
                    logger.exception(f"[unified_pm_arb] Execution error: {exc}")
                    errors.append(str(exc))

            # Trim history
            if len(self._history) > 500:
                self._history = self._history[-500:]

            elapsed = (time.monotonic() - start) * 1000
            logger.info(
                f"[unified_pm_arb] Cycle: {len(opportunities)} detected, "
                f"{trades_placed} filled, {len(errors)} errors, "
                f"{total_markets} markets, {elapsed:.0f}ms"
            )

            return CycleResult(
                decisions_recorded=len(opportunities),
                trades_attempted=len(opportunities),
                trades_placed=trades_placed,
                errors=errors,
                cycle_duration_ms=elapsed,
                markets_scanned=total_markets,
            )

        except CircuitOpenError as exc:
            logger.warning(f"[unified_pm_arb] Circuit breaker open: {exc}")
            return CycleResult(0, 0, 0, errors=[str(exc)])

        except Exception as exc:
            logger.exception(f"[unified_pm_arb] Cycle failed: {exc}")
            return CycleResult(0, 0, 0, errors=[str(exc)])

    # ------------------------------------------------------------------
    # History access (for tests and diagnostics)
    # ------------------------------------------------------------------

    def get_history(self, limit: int = 100) -> List[dict]:
        """Return recent arb execution history."""
        return self._history[-limit:]
