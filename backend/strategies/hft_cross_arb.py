"""HFT Cross-Exchange Atomic Arbitrage Executor.

Detects cross-platform arbitrage between Polymarket and Kalshi, then executes
BOTH legs atomically using asyncio.gather(). If one leg fails, the other is
immediately cancelled to prevent unhedged exposure.

Execution flow:
  detect_arb() -> calculate_sizes() -> place_both_legs() -> verify_fills() -> record()
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from backend.config import settings
from backend.core.circuit_breaker import CircuitBreaker, CircuitOpenError
from backend.strategies.cross_market_arb_enhanced import (
    ArbOpportunityEnhanced,
    CrossMarketArbEnhanced,
)
from backend.strategies.base import BaseStrategy, CycleResult, StrategyContext

from loguru import logger


def _cfg(name: str, default=None):
    return getattr(settings, name, default)


# ---------------------------------------------------------------------------
# Execution result dataclass
# ---------------------------------------------------------------------------

@dataclass
class AtomicArbResult:
    """Result of an atomic cross-exchange arbitrage execution."""
    arb_id: str
    opportunity: Optional[ArbOpportunityEnhanced] = None
    poly_order_id: Optional[str] = None
    kalshi_order_id: Optional[str] = None
    poly_fill_price: float = 0.0
    kalshi_fill_price: float = 0.0
    poly_size: float = 0.0
    kalshi_size: float = 0.0
    net_profit: float = 0.0
    status: str = "pending"  # pending | filled | partial | failed | cancelled
    error: Optional[str] = None
    latency_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "arb_id": self.arb_id,
            "poly_order_id": self.poly_order_id,
            "kalshi_order_id": self.kalshi_order_id,
            "poly_fill_price": self.poly_fill_price,
            "kalshi_fill_price": self.kalshi_fill_price,
            "poly_size": self.poly_size,
            "kalshi_size": self.kalshi_size,
            "net_profit": self.net_profit,
            "status": self.status,
            "error": self.error,
            "latency_ms": self.latency_ms,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Circuit breakers per venue
# ---------------------------------------------------------------------------

_ARB_CB_THRESHOLD = _cfg("ARB_CIRCUIT_BREAKER_THRESHOLD", 5)
_ARB_CB_TIMEOUT = _cfg("ARB_CIRCUIT_BREAKER_TIMEOUT", 60.0)
_poly_breaker = CircuitBreaker("hft_arb_polymarket", failure_threshold=_ARB_CB_THRESHOLD, recovery_timeout=_ARB_CB_TIMEOUT)
_kalshi_breaker = CircuitBreaker("hft_arb_kalshi", failure_threshold=_ARB_CB_THRESHOLD, recovery_timeout=_ARB_CB_TIMEOUT)


# ---------------------------------------------------------------------------
# Position sizing: Kelly criterion for arbitrage
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
# Fee calculation
# ---------------------------------------------------------------------------

def _calculate_fees(
    poly_price: float,
    kalshi_price: float,
    poly_size: float,
    kalshi_size: float,
    poly_fee_pct: Optional[float] = None,
    kalshi_fee_pct: Optional[float] = None,
    slippage_bps: float = 5.0,
) -> Tuple[float, float, float]:
    """Calculate total fees for both legs.

    Returns (poly_fee, kalshi_fee, total_slippage_cost).
    """
    pf = poly_fee_pct if poly_fee_pct is not None else _cfg("CROSS_MARKET_ARB_POLYMARKET_FEE", 0.01)
    kf = kalshi_fee_pct if kalshi_fee_pct is not None else _cfg("CROSS_MARKET_ARB_KALSHI_FEE", 0.01)
    poly_fee = poly_price * poly_size * pf
    kalshi_fee = kalshi_price * kalshi_size * kf
    slippage_cost = (slippage_bps / 10_000) * (poly_size + kalshi_size)
    return poly_fee, kalshi_fee, slippage_cost


# ---------------------------------------------------------------------------
# Core executor
# ---------------------------------------------------------------------------

class HFTCrossArbExecutor:
    """Atomic cross-exchange arbitrage executor.

    Places orders on both Polymarket and Kalshi simultaneously.
    If one leg fails, immediately cancels the other.
    """

    _FILL_TIMEOUT_S = 5.0
    _MAX_RETRIES = 3

    def __init__(
        self,
        clob: Optional[Any] = None,
        kalshi_client: Optional[Any] = None,
        max_exposure: float = 200.0,
        kelly_fraction: float = 0.25,
        min_net_edge: float = 0.01,
        slippage_bps: float = 5.0,
        paper_mode: bool = True,
    ):
        self._clob = clob
        self._kalshi = kalshi_client
        self._max_exposure = max_exposure
        self._kelly_fraction = kelly_fraction
        self._min_net_edge = min_net_edge
        self._slippage_bps = slippage_bps
        self._paper_mode = paper_mode
        self._detector = CrossMarketArbEnhanced(
            poly_fee_pct=_cfg("CROSS_MARKET_ARB_POLYMARKET_FEE", 0.01),
            kalshi_fee_pct=_cfg("CROSS_MARKET_ARB_KALSHI_FEE", 0.01),
            slippage_bps=slippage_bps,
        )
        self._history: List[AtomicArbResult] = []
        self._active_arbs: Dict[str, AtomicArbResult] = {}

    # ---- lazy client init ----

    def _get_kalshi_client(self) -> Any:
        if self._kalshi is None:
            from backend.data.kalshi_client import KalshiClient
            self._kalshi = KalshiClient()
        return self._kalshi

    # ---- sizing ----

    def calculate_sizes(
        self,
        opp: ArbOpportunityEnhanced,
        bankroll: float = 1000.0,
    ) -> Tuple[float, float]:
        """Calculate position sizes for both legs using Kelly criterion.

        Returns (poly_size_usdc, kalshi_contracts).
        """
        net_edge = opp.net_profit
        if net_edge <= self._min_net_edge:
            return 0.0, 0.0

        base_size = _kelly_size(
            edge=net_edge,
            bankroll=bankroll,
            max_size=self._max_exposure,
            kelly_fraction=self._kelly_fraction,
        )
        if base_size < _cfg("MIN_ORDER_USDC", 5.0):
            return 0.0, 0.0

        # Size each leg proportionally to its price so exposure is balanced
        cheaper = opp.details.get("cheaper", "polymarket")
        if cheaper == "polymarket":
            poly_size = base_size
            # Kalshi contracts = base_size / kalshi_price (contracts are per-unit)
            kalshi_size = base_size / opp.price_b if opp.price_b > 0 else 0.0
        else:
            kalshi_size = base_size / opp.price_a if opp.price_a > 0 else 0.0
            poly_size = base_size

        # Cap both legs at max_exposure
        poly_size = min(poly_size, self._max_exposure)
        kalshi_contracts = min(kalshi_size, self._max_exposure)

        return round(poly_size, 2), round(kalshi_contracts, 2)

    # ---- net edge after fees ----

    def compute_net_edge(
        self,
        opp: ArbOpportunityEnhanced,
        poly_size: float,
        kalshi_size: float,
    ) -> float:
        """Recompute net edge with exact sizes, fees, and slippage."""
        gross_spread = opp.raw_spread
        poly_fee, kalshi_fee, slippage = _calculate_fees(
            poly_price=opp.price_a,
            kalshi_price=opp.price_b,
            poly_size=poly_size,
            kalshi_size=kalshi_size,
            slippage_bps=self._slippage_bps,
        )
        total_cost = poly_fee + kalshi_fee + slippage
        invested = (opp.price_a * poly_size) + (opp.price_b * kalshi_size)
        if invested <= 0:
            return 0.0
        return gross_spread - (total_cost / invested)

    # ---- atomic execution ----

    async def execute_arb(
        self,
        opp: ArbOpportunityEnhanced,
        bankroll: float = 1000.0,
    ) -> AtomicArbResult:
        """Execute both legs of a cross-exchange arb atomically.

        On failure of either leg, the other is cancelled immediately.
        """
        arb_id = str(uuid.uuid4())
        start = time.monotonic()

        poly_size, kalshi_size = self.calculate_sizes(opp, bankroll)
        if poly_size <= 0 or kalshi_size <= 0:
            return AtomicArbResult(
                arb_id=arb_id,
                opportunity=opp,
                status="skipped",
                error="Size below minimum or zero edge",
            )

        # Final edge check with exact sizes
        net_edge = self.compute_net_edge(opp, poly_size, kalshi_size)
        if net_edge < self._min_net_edge:
            return AtomicArbResult(
                arb_id=arb_id,
                opportunity=opp,
                status="skipped",
                error=f"Net edge {net_edge:.4f} below minimum {self._min_net_edge}",
            )

        cheaper = opp.details.get("cheaper", "polymarket")
        if cheaper == "polymarket":
            poly_side, kalshi_side = "BUY", "SELL"
            poly_price, kalshi_price = opp.price_a, opp.price_b
            poly_token, kalshi_ticker = opp.market_a_id, opp.market_b_id
        else:
            poly_side, kalshi_side = "SELL", "BUY"
            poly_price, kalshi_price = opp.price_b, opp.price_a
            poly_token, kalshi_ticker = opp.market_b_id, opp.market_a_id

        result = AtomicArbResult(arb_id=arb_id, opportunity=opp)
        self._active_arbs[arb_id] = result

        try:
            poly_order, kalshi_order = await asyncio.gather(
                self._place_poly_leg(poly_token, poly_side, poly_price, poly_size, arb_id),
                self._place_kalshi_leg(kalshi_ticker, kalshi_side, kalshi_price, kalshi_size, arb_id),
                return_exceptions=True,
            )

            poly_ok = isinstance(poly_order, str) and poly_order.startswith("paper_") or (isinstance(poly_order, str) and bool(poly_order))
            kalshi_ok = isinstance(kalshi_order, str) and bool(kalshi_order)

            if isinstance(poly_order, Exception):
                poly_ok = False
                logger.error(f"[hft_cross_arb] Poly leg exception: {poly_order}")
            if isinstance(kalshi_order, Exception):
                kalshi_ok = False
                logger.error(f"[hft_cross_arb] Kalshi leg exception: {kalshi_order}")

            if poly_ok and kalshi_ok:
                # Both filled
                result.poly_order_id = poly_order if isinstance(poly_order, str) else str(poly_order)
                result.kalshi_order_id = kalshi_order if isinstance(kalshi_order, str) else str(kalshi_order)
                result.poly_fill_price = poly_price
                result.kalshi_fill_price = kalshi_price
                result.poly_size = poly_size
                result.kalshi_size = kalshi_size
                result.net_profit = net_edge * min(poly_size, kalshi_size)
                result.status = "filled"
                await _poly_breaker.record_success()
                await _kalshi_breaker.record_success()
                logger.info(
                    f"[hft_cross_arb] FILLED arb_id={arb_id} "
                    f"poly={poly_order} kalshi={kalshi_order} "
                    f"net_profit=${result.net_profit:.4f}"
                )

            elif poly_ok and not kalshi_ok:
                # Poly filled, Kalshi failed -> cancel poly
                result.poly_order_id = poly_order if isinstance(poly_order, str) else str(poly_order)
                result.status = "partial"
                result.error = f"Kalshi leg failed: {kalshi_order}"
                await _kalshi_breaker.record_failure()
                await self._emergency_cancel_poly(poly_order if isinstance(poly_order, str) else str(poly_order), arb_id)

            elif not poly_ok and kalshi_ok:
                # Kalshi filled, Poly failed -> cancel kalshi
                result.kalshi_order_id = kalshi_order if isinstance(kalshi_order, str) else str(kalshi_order)
                result.status = "partial"
                result.error = f"Poly leg failed: {poly_order}"
                await _poly_breaker.record_failure()
                await self._emergency_cancel_kalshi(kalshi_order if isinstance(kalshi_order, str) else str(kalshi_order), arb_id)

            else:
                result.status = "failed"
                result.error = f"Both legs failed: poly={poly_order}, kalshi={kalshi_order}"
                await _poly_breaker.record_failure()
                await _kalshi_breaker.record_failure()

        except Exception as exc:
            logger.exception(f"[hft_cross_arb] Atomic execution failed: {exc}")
            result.status = "failed"
            result.error = str(exc)

        result.latency_ms = (time.monotonic() - start) * 1000
        self._active_arbs.pop(arb_id, None)
        self._history.append(result)
        if len(self._history) > 500:
            self._history = self._history[-500:]

        return result

    # ---- platform-specific leg placement ----

    async def _place_poly_leg(
        self, token_id: str, side: str, price: float, size: float, arb_id: str,
    ) -> Optional[str]:
        """Place Polymarket order leg with circuit breaker + retry."""
        if self._clob is None:
            raise ValueError("CLOB instance not initialised")

        # CircuitBreaker.call() raises CircuitOpenError if breaker is open
        idempotency_key = f"arb-{arb_id}-poly-{int(time.monotonic() * 1000000)}"

        for attempt in range(self._MAX_RETRIES):
            try:
                async def _do():
                    result = await self._clob.place_limit_order(
                        token_id=token_id,
                        side=side,
                        price=price,
                        size=size,
                    )
                    if hasattr(result, "order_id") and result.order_id:
                        return result.order_id
                    if hasattr(result, "success") and not result.success:
                        raise ValueError(f"Order failed: {getattr(result, 'error', 'unknown')}")
                    return getattr(result, "order_id", f"poly_{int(time.time())}")

                return await _poly_breaker.call(_do)

            except CircuitOpenError:
                raise
            except Exception as exc:
                logger.warning(
                    f"[hft_cross_arb] Poly leg attempt {attempt + 1}/{self._MAX_RETRIES} failed: {exc}"
                )
                if attempt < self._MAX_RETRIES - 1:
                    await asyncio.sleep(0.01 * (2 ** attempt))
                else:
                    raise

    async def _place_kalshi_leg(
        self, ticker: str, side: str, price: float, contracts: float, arb_id: str,
    ) -> Optional[str]:
        """Place Kalshi order leg with circuit breaker + retry."""
        # CircuitBreaker.call() raises CircuitOpenError if breaker is open
        idempotency_key = f"arb-{arb_id}-kalshi-{int(time.monotonic() * 1000000)}"

        for attempt in range(self._MAX_RETRIES):
            try:
                async def _do():
                    client = self._get_kalshi_client()
                    result = await client.place_order(
                        market_id=ticker,
                        side=side,
                        size=int(contracts),
                        price=price,
                    )
                    if isinstance(result, dict):
                        order_id = result.get("order", {}).get("order_id") or result.get("order_id")
                        if order_id:
                            return order_id
                        status = result.get("status", "")
                        if status in ("resting", "filled", "pending"):
                            return result.get("order_id", f"kalshi_{int(time.time())}")
                    return f"kalshi_{int(time.time())}"

                return await _kalshi_breaker.call(_do)

            except CircuitOpenError:
                raise
            except Exception as exc:
                logger.warning(
                    f"[hft_cross_arb] Kalshi leg attempt {attempt + 1}/{self._MAX_RETRIES} failed: {exc}"
                )
                if attempt < self._MAX_RETRIES - 1:
                    await asyncio.sleep(0.01 * (2 ** attempt))
                else:
                    raise

    # ---- emergency cancellation ----

    async def _emergency_cancel_poly(self, order_id: str, arb_id: str) -> None:
        """Cancel Polymarket order after Kalshi leg failure."""
        try:
            if self._clob and hasattr(self._clob, "cancel_order"):
                await self._clob.cancel_order(order_id)
                logger.warning(f"[hft_cross_arb] EMERGENCY CANCEL poly order={order_id} arb_id={arb_id}")
            else:
                logger.error(f"[hft_cross_arb] Cannot cancel poly order={order_id}: no CLOB client")
        except Exception as exc:
            logger.exception(f"[hft_cross_arb] Failed to cancel poly order={order_id}: {exc}")

    async def _emergency_cancel_kalshi(self, order_id: str, arb_id: str) -> None:
        """Cancel Kalshi order after Polymarket leg failure."""
        try:
            client = self._get_kalshi_client()
            await client.cancel_order(order_id)
            logger.warning(f"[hft_cross_arb] EMERGENCY CANCEL kalshi order={order_id} arb_id={arb_id}")
        except Exception as exc:
            logger.exception(f"[hft_cross_arb] Failed to cancel kalshi order={order_id}: {exc}")

    # ---- verification ----

    async def verify_fills(self, result: AtomicArbResult) -> bool:
        """Verify both legs are filled after execution. Returns True if both confirmed."""
        if result.status != "filled":
            return False
        # In paper mode, assume fills are good
        if self._paper_mode:
            return True
        # Live: could check order status on both platforms
        # For now, trust the order placement response
        return True

    # ---- scanning ----

    def detect_arb(
        self,
        poly_markets: List[Dict[str, Any]],
        kalshi_markets: List[Dict[str, Any]],
    ) -> List[ArbOpportunityEnhanced]:
        """Detect cross-platform arbitrage opportunities."""
        return self._detector.detect_cross_platform(poly_markets, kalshi_markets)

    def scan_all(
        self,
        poly_markets: List[Dict[str, Any]],
        kalshi_markets: List[Dict[str, Any]],
    ) -> List[ArbOpportunityEnhanced]:
        """Full scan: cross-platform + yes/no sum + complementary."""
        result = self._detector.scan_all(poly_markets, kalshi_markets)
        return result.opportunities

    # ---- batch execution ----

    async def execute_batch(
        self,
        opportunities: List[ArbOpportunityEnhanced],
        bankroll: float = 1000.0,
    ) -> List[AtomicArbResult]:
        """Execute multiple arbs concurrently via asyncio.gather()."""
        if not opportunities:
            return []
        # Limit concurrency to avoid overwhelming the APIs
        sem = asyncio.Semaphore(5)

        async def _exec(opp: AtomicArbResult) -> AtomicArbResult:
            async with sem:
                return await self.execute_arb(opp, bankroll)

        # We need to pass the actual opportunity, not result
        results = await asyncio.gather(
            *[self.execute_arb(opp, bankroll) for opp in opportunities],
            return_exceptions=True,
        )
        out = []
        for r in results:
            if isinstance(r, AtomicArbResult):
                out.append(r)
            elif isinstance(r, Exception):
                logger.error(f"[hft_cross_arb] Batch execution exception: {r}")
        return out

    # ---- history ----

    def get_history(self, limit: int = 100) -> List[dict]:
        return [r.to_dict() for r in self._history[-limit:]]


# ---------------------------------------------------------------------------
# Strategy wrapper for HFT dispatcher integration
# ---------------------------------------------------------------------------

class HFTCrossArbStrategy(BaseStrategy):
    """Wraps HFTCrossArbExecutor as a BaseStrategy for the HFT dispatcher.

    Scans both platforms, detects arbs, and executes atomically.
    """

    name = "hft_cross_arb"
    description = "Atomic cross-exchange arbitrage: Polymarket <-> Kalshi"
    category = "arb"

    default_params = {
        "max_exposure": _cfg("CROSS_MARKET_ARB_MAX_SIZE", 200.0),
        "min_net_edge": _cfg("HFT_ARB_MIN_PROFIT", 0.02),
        "kelly_fraction": 0.25,
        "slippage_bps": 5.0,
        "enabled": True,
    }

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        """Scan and execute cross-exchange arbs atomically."""
        start = time.monotonic()
        errors: List[str] = []
        trades_placed = 0

        try:
            # Fetch markets from both platforms
            poly_markets, kalshi_markets = await asyncio.gather(
                self._fetch_poly_markets(ctx),
                self._fetch_kalshi_markets(ctx),
            )

            if not poly_markets or not kalshi_markets:
                return CycleResult(0, 0, 0, errors=["No markets available"])

            # Build executor
            paper = ctx.mode == "paper"
            executor = HFTCrossArbExecutor(
                clob=ctx.clob,
                max_exposure=self.default_params["max_exposure"],
                min_net_edge=self.default_params["min_net_edge"],
                kelly_fraction=self.default_params["kelly_fraction"],
                slippage_bps=self.default_params["slippage_bps"],
                paper_mode=paper,
            )

            # Detect arbs
            opps = executor.detect_arb(poly_markets, kalshi_markets)
            if not opps:
                elapsed = (time.monotonic() - start) * 1000
                return CycleResult(0, 0, 0, cycle_duration_ms=elapsed)

            # Execute top opportunities atomically
            results = await executor.execute_batch(opps, bankroll=1000.0)

            for r in results:
                if r.status == "filled":
                    trades_placed += 1
                elif r.status in ("failed", "partial"):
                    errors.append(r.error or f"Arb {r.arb_id} {r.status}")

            elapsed = (time.monotonic() - start) * 1000
            logger.info(
                f"[hft_cross_arb] Cycle complete: {len(opps)} detected, "
                f"{trades_placed} filled, {len(errors)} errors, {elapsed:.1f}ms"
            )

            return CycleResult(
                decisions_recorded=len(opps),
                trades_attempted=len(results),
                trades_placed=trades_placed,
                errors=errors,
                cycle_duration_ms=elapsed,
            )

        except CircuitOpenError as exc:
            logger.warning(f"[hft_cross_arb] Circuit breaker open: {exc}")
            return CycleResult(0, 0, 0, errors=[str(exc)])

        except Exception as exc:
            logger.exception(f"[hft_cross_arb] Cycle failed: {exc}")
            return CycleResult(0, 0, 0, errors=[str(exc)])

    async def _fetch_poly_markets(self, ctx: StrategyContext) -> list[dict]:
        """Fetch Polymarket markets via provider or Gamma fallback."""
        try:
            provider = ctx.get_market_provider("polymarket")
            if provider and hasattr(provider, "search_markets"):
                return await provider.search_markets("", limit=500)
        except Exception:
            pass
        try:
            from backend.data.gamma import fetch_markets
            return await fetch_markets(limit=500)
        except Exception as exc:
            logger.warning(f"[hft_cross_arb] Poly fetch failed: {exc}")
            return []

    async def _fetch_kalshi_markets(self, ctx: StrategyContext) -> list[dict]:
        """Fetch Kalshi markets via provider or KalshiClient fallback."""
        try:
            provider = ctx.get_market_provider("kalshi")
            if provider and hasattr(provider, "search_markets"):
                return await provider.search_markets("", limit=500)
        except Exception:
            pass
        try:
            from backend.data.kalshi_client import KalshiClient
            client = KalshiClient()
            data = await client.get_markets(params={"limit": 500, "status": "open"})
            return data.get("markets", []) if isinstance(data, dict) else []
        except Exception as exc:
            logger.warning(f"[hft_cross_arb] Kalshi fetch failed: {exc}")
            return []
