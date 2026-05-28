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
from dataclasses import dataclass, field
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
# DEX price types (inlined from cross_dex_arb.py)
# ---------------------------------------------------------------------------

@dataclass
class PriceQuote:
    """Normalized price from a single exchange for one asset."""
    exchange: str
    base: str
    quote: str = "USD"
    bid: float = 0.0
    ask: float = 0.0
    mid: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class DexArbOpportunity:
    """Cross-DEX arbitrage opportunity."""
    asset: str
    buy_exchange: str
    sell_exchange: str
    buy_price: float
    sell_price: float
    gross_spread: float
    taker_fees_pct: float
    gas_estimate: float
    net_profit_pct: float
    confidence: float
    timestamp: float = field(default_factory=time.time)


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
# DEX Price Feed (inlined from cross_dex_arb.py)
# ---------------------------------------------------------------------------

class DexPriceFeed:
    """Fetch prices from all DEX providers using existing clients."""

    DEFAULT_TAKER_FEES = {
        "hyperliquid": 0.0005,
        "aster": 0.00035,
        "lighter": 0.0,
        "ostium": 0.005,
    }

    DEFAULT_TIMEOUTS = {
        "hyperliquid": 15.0,
        "aster": 20.0,
        "lighter": 10.0,
        "ostium": 10.0,
    }

    def __init__(
        self,
        taker_fees: Optional[Dict[str, float]] = None,
        timeouts: Optional[Dict[str, float]] = None,
    ):
        self._taker_fees = taker_fees or dict(self.DEFAULT_TAKER_FEES)
        self._timeouts = timeouts or dict(self.DEFAULT_TIMEOUTS)

    async def fetch_hyperliquid_prices(self) -> List[PriceQuote]:
        try:
            def _sync_fetch():
                from hyperliquid.info import Info
                from hyperliquid.utils import constants as hl_constants
                info = Info(hl_constants.MAINNET_API_URL, skip_ws=True)
                mids = info.all_mids()
                books = {}
                for name in list(mids.keys())[:50]:
                    if name.startswith("#"):
                        continue
                    try:
                        l2 = info.l2_snapshot(name)
                        if l2 and "levels" in l2:
                            levels = l2["levels"]
                            bids = levels[0] if len(levels) > 0 else []
                            asks = levels[1] if len(levels) > 1 else []
                            best_bid = float(bids[0]["px"]) if bids else 0
                            best_ask = float(asks[0]["px"]) if asks else 0
                            if best_bid > 0 and best_ask > 0 and best_bid < best_ask:
                                books[name] = (best_bid, best_ask)
                    except Exception:
                        pass
                return mids, books

            mids, books = await asyncio.to_thread(_sync_fetch)
            quotes = []
            for name, mid in mids.items():
                try:
                    mid_f = float(mid)
                    if mid_f <= 0 or name.startswith("#"):
                        continue
                    if name in books:
                        bid, ask = books[name]
                        spread_pct = (ask - bid) / mid_f
                        if spread_pct > 0.02:
                            continue
                        quotes.append(PriceQuote(exchange="hyperliquid", base=name, bid=bid, ask=ask, mid=mid_f))
                except (ValueError, TypeError):
                    continue
            return quotes
        except Exception as e:
            logger.warning(f"dex_feed: Hyperliquid failed: {e}")
            return []

    async def fetch_aster_prices(self) -> List[PriceQuote]:
        client = None
        try:
            from backend.clients.aster_client import AsterClient
            client = AsterClient()
            tickers = await client.get_tickers()
            quotes = []
            for symbol, ticker in tickers.items():
                if not symbol.endswith("/USDC") and not symbol.endswith("/USDT"):
                    continue
                try:
                    bid = float(ticker.get("bid", 0) or 0)
                    ask = float(ticker.get("ask", 0) or 0)
                    last = float(ticker.get("last", 0) or 0)
                    if bid <= 0 and ask <= 0:
                        continue
                    base = symbol.split("/")[0]
                    quotes.append(PriceQuote(exchange="aster", base=base, bid=bid, ask=ask, mid=last or ((bid + ask) / 2 if bid and ask else 0)))
                except Exception:
                    continue
            return quotes
        except Exception as e:
            logger.warning(f"dex_feed: Aster failed: {e}")
            return []
        finally:
            if client:
                await client.close()

    async def fetch_lighter_prices(self) -> List[PriceQuote]:
        try:
            from backend.clients.lighter_client import LighterClient
            client = LighterClient(skip_signer=True)
            order_books = await client.get_markets()
            quotes = []
            for ob in order_books:
                if hasattr(ob, "__dict__") and not isinstance(ob, dict):
                    ob = ob.__dict__
                if not isinstance(ob, dict):
                    continue
                base = ob.get("base_symbol") or ob.get("symbol") or ob.get("name") or ob.get("baseAsset", "")
                if not base:
                    continue
                bids = ob.get("bids") or []
                asks = ob.get("asks") or []
                best_bid = float(bids[0].get("price", 0)) if bids else 0
                best_ask = float(asks[0].get("price", 0)) if asks else 0
                if best_bid <= 0 and best_ask <= 0:
                    continue
                quotes.append(PriceQuote(exchange="lighter", base=str(base).split("/")[0].split("-")[0], bid=best_bid, ask=best_ask, mid=(best_bid + best_ask) / 2 if best_bid and best_ask else 0))
            return quotes
        except Exception as e:
            logger.warning(f"dex_feed: Lighter failed: {e}")
            return []

    async def fetch_ostium_prices(self) -> List[PriceQuote]:
        try:
            from backend.clients.ostium_client import OstiumClient
            client = OstiumClient()
            markets = await client.get_markets()
            quotes = []
            for m in markets:
                if hasattr(m, "__dict__") and not isinstance(m, dict):
                    m = m.__dict__
                if not isinstance(m, dict):
                    continue
                base = m.get("base_symbol") or m.get("from") or m.get("name") or m.get("pair", "")
                if not base:
                    continue
                bid_val = 0.0
                ask_val = 0.0
                for key in ("best_bid", "bid", "bid_price"):
                    val = m.get(key)
                    if val is not None:
                        try:
                            bid_val = float(val)
                            if bid_val > 0:
                                break
                        except (ValueError, TypeError):
                            pass
                for key in ("best_ask", "ask", "ask_price"):
                    val = m.get(key)
                    if val is not None:
                        try:
                            ask_val = float(val)
                            if ask_val > 0:
                                break
                        except (ValueError, TypeError):
                            pass
                if bid_val > 0 and ask_val > 0 and bid_val < ask_val:
                    spread_pct = (ask_val - bid_val) / ((bid_val + ask_val) / 2)
                    if spread_pct > 0.02:
                        continue
                    quotes.append(PriceQuote(exchange="ostium", base=str(base).split("/")[0].split("-")[0], bid=bid_val, ask=ask_val, mid=(bid_val + ask_val) / 2))
                elif m.get("price") or m.get("mark_price"):
                    continue  # skip assets without real bid/ask
            return quotes
        except Exception as e:
            logger.warning(f"dex_feed: Ostium failed: {e}")
            return []

    async def fetch_all_prices(self, exchanges: Optional[List[str]] = None) -> Dict[str, List[PriceQuote]]:
        targets = exchanges or ["hyperliquid", "aster", "lighter", "ostium"]
        fetchers = {
            "hyperliquid": (self.fetch_hyperliquid_prices, self._timeouts.get("hyperliquid", 15.0)),
            "aster": (self.fetch_aster_prices, self._timeouts.get("aster", 20.0)),
            "lighter": (self.fetch_lighter_prices, self._timeouts.get("lighter", 10.0)),
            "ostium": (self.fetch_ostium_prices, self._timeouts.get("ostium", 10.0)),
        }
        coros = []
        names = []
        for ex in targets:
            if ex in fetchers:
                fetcher, timeout = fetchers[ex]
                coros.append(self._wrap(ex, fetcher, timeout))
                names.append(ex)
        results_list = await asyncio.gather(*coros, return_exceptions=True)
        results = {}
        for i, r in enumerate(results_list):
            results[names[i]] = [] if isinstance(r, Exception) else (r or [])
        return results

    async def _wrap(self, name: str, fetcher, timeout: float):
        try:
            return await asyncio.wait_for(fetcher(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"dex_feed: {name} timeout ({timeout}s)")
        except Exception as e:
            logger.warning(f"dex_feed: {name} failed: {e}")
        return []


def _detect_cross_dex_opportunities(
    all_prices: Dict[str, List[PriceQuote]],
    min_profit_pct: float = 0.003,
    gas_estimate: float = 2.0,
    taker_fees: Optional[Dict[str, float]] = None,
) -> List[DexArbOpportunity]:
    """Scan all exchange pairs for arbitrage on same asset."""
    if taker_fees is None:
        taker_fees = {}

    asset_map: Dict[str, List[Tuple[str, PriceQuote]]] = {}
    for exchange, quotes in all_prices.items():
        for q in quotes:
            key = q.base.upper()
            if key not in asset_map:
                asset_map[key] = []
            asset_map[key].append((exchange, q))

    opps = []
    for asset, entries in asset_map.items():
        if len(entries) < 2:
            continue
        for i in range(len(entries)):
            for j in range(len(entries)):
                if i == j:
                    continue
                ex_i, qi = entries[i]
                ex_j, qj = entries[j]
                if qi.ask <= 0 or qj.bid <= 0:
                    continue
                buy_price = qi.ask
                sell_price = qj.bid
                gross_spread = (sell_price - buy_price) / buy_price
                if gross_spread <= 0:
                    continue
                fee_i = taker_fees.get(ex_i.lower(), 0.005)
                fee_j = taker_fees.get(ex_j.lower(), 0.005)
                total_fees = fee_i + fee_j
                gas_pct = gas_estimate / buy_price if buy_price > 0 else 0
                net_pct = gross_spread - total_fees - gas_pct
                if net_pct < min_profit_pct:
                    continue
                confidence = min(1.0, (net_pct - min_profit_pct) / (min_profit_pct * 2))
                opps.append(DexArbOpportunity(
                    asset=asset, buy_exchange=ex_i, sell_exchange=ex_j,
                    buy_price=buy_price, sell_price=sell_price,
                    gross_spread=gross_spread, taker_fees_pct=total_fees,
                    gas_estimate=gas_estimate, net_profit_pct=net_pct,
                    confidence=confidence,
                ))

    seen = set()
    unique = []
    for o in sorted(opps, key=lambda o: o.net_profit_pct, reverse=True):
        key = (o.asset, o.buy_exchange, o.sell_exchange)
        if key not in seen:
            seen.add(key)
            unique.append(o)
    return unique


# ---------------------------------------------------------------------------
# Unified PM Arbitrage Strategy
# ---------------------------------------------------------------------------

class UnifiedPMArb(BaseStrategy):
    """Single prediction-market arbitrage strategy.

    Scans all registered PM venues via market_registry, detects arb using
    CrossMarketArbEnhanced, and executes atomically via provider.place_order().
    """

    name = "unified_arb"
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
                    logger.warning(f"[unified_arb] {venue} fetch failed: {result}")
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
            logger.debug(f"[unified_arb] {venue}: {len(normalized)} markets")
            return normalized
        except asyncio.TimeoutError:
            logger.warning(f"[unified_arb] {venue} timed out (30s)")
            return []
        except Exception as exc:
            logger.warning(f"[unified_arb] {venue} fetch failed: {exc}")
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
                f"[unified_arb] FILLED arb={arb_id} "
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
            logger.warning(f"[unified_arb] PARTIAL arb={arb_id}: {error}")
            return {"status": "partial", "error": error, "arb_id": arb_id}

        elif not a_ok and b_ok:
            # Leg B filled, leg A failed — emergency cancel B
            order_id_b = result_b.venue_order_id if isinstance(result_b, NormalizedOrderResult) else str(result_b)
            await self._emergency_cancel(provider_b, order_id_b, arb_id)
            error = f"leg_a_failed: {result_a}"
            logger.warning(f"[unified_arb] PARTIAL arb={arb_id}: {error}")
            return {"status": "partial", "error": error, "arb_id": arb_id}

        else:
            error_a = str(result_a) if isinstance(result_a, Exception) else str(result_a)
            error_b = str(result_b) if isinstance(result_b, Exception) else str(result_b)
            logger.warning(
                f"[unified_arb] FAILED arb={arb_id}: "
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
                    f"[unified_arb] EMERGENCY CANCEL order={order_id} arb={arb_id}"
                )
            else:
                logger.error(
                    f"[unified_arb] Cannot cancel order={order_id}: "
                    f"provider has no cancel_order"
                )
        except Exception as exc:
            logger.error(
                f"[unified_arb] Cancel failed order={order_id} arb={arb_id}: {exc}"
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
                    logger.warning(f"[unified_arb] Circuit breaker open: {exc}")
                    errors.append(str(exc))
                except Exception as exc:
                    logger.exception(f"[unified_arb] Execution error: {exc}")
                    errors.append(str(exc))

            # Trim history
            if len(self._history) > 500:
                self._history = self._history[-500:]

            elapsed = (time.monotonic() - start) * 1000
            logger.info(
                f"[unified_arb] Cycle: {len(opportunities)} detected, "
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
            logger.warning(f"[unified_arb] Circuit breaker open: {exc}")
            return CycleResult(0, 0, 0, errors=[str(exc)])

        except Exception as exc:
            logger.exception(f"[unified_arb] Cycle failed: {exc}")
            return CycleResult(0, 0, 0, errors=[str(exc)])

    # ------------------------------------------------------------------
    # History access (for tests and diagnostics)
    # ------------------------------------------------------------------

    def get_history(self, limit: int = 100) -> List[dict]:
        """Return recent arb execution history."""
        return self._history[-limit:]
