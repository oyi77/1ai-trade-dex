"""
Cross-DEX Real-time Arbitrage Engine

Modular, zero-hardcode architecture following BaseStrategy pattern.
Auto-registers as 'cross_dex_arb' via __init_subclass__ in strategy registry.

Detection pipeline:
1. DexPriceFeed → normalized prices from all 4 DEXes (parallel fetch)
2. _detect_cross_dex_opportunities → spread analysis with fee accounting
3. CycleResult → decisions output (no execution yet)

DEX price sources:
- Hyperliquid: Info.all_mids() via asyncio.to_thread (sync SDK)
- Aster: ccxt fetch_ticker() via asyncio.to_thread (sync SDK)
- Lighter: SDK order_books() — gracefully skipped on auth error
- Ostium: subgraph get_markets() — gracefully skipped on timeout
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from backend.strategies.base import BaseStrategy, StrategyContext, CycleResult
from loguru import logger


# ── Data types ─────────────────────────────────────────────────────────


@dataclass
class PriceQuote:
    """Normalized price from a single exchange for one asset."""
    exchange: str
    base: str          # e.g. "BTC"
    quote: str = "USD"
    bid: float = 0.0   # Best bid (to sell into)
    ask: float = 0.0   # Best ask (to buy from)
    mid: float = 0.0   # Mark price
    timestamp: float = field(default_factory=time.time)


@dataclass
class DexArbOpportunity:
    """Cross-DEX arbitrage opportunity."""
    asset: str
    buy_exchange: str
    sell_exchange: str
    buy_price: float
    sell_price: float
    gross_spread: float       # (sell - buy) / buy
    taker_fees_pct: float     # Combined taker fees
    gas_estimate: float       # Estimated gas/settlement cost
    net_profit_pct: float     # After fees and gas
    confidence: float         # 0-1 based on liquidity and spread
    timestamp: float = field(default_factory=time.time)


# ── Price Feed ──────────────────────────────────────────────────────────


class DexPriceFeed:
    """Fetch prices from all DEX providers using existing clients.

    Reuses backend.clients.* — no new API wrappers needed.
    Each fetch is independent with graceful per-provider failure.
    """

    # Configurable taker fees per exchange (fraction, e.g. 0.0005 = 0.05%)
    DEFAULT_TAKER_FEES = {
        "hyperliquid": 0.0005,   # 0.05%
        "aster": 0.00035,         # 0.035%
        "lighter": 0.0,           # Zero-fee standard accounts
        "ostium": 0.005,          # ~0.5% (dynamic)
    }

    DEFAULT_SPREAD_ESTIMATES = {
        "hyperliquid": 0.0005,  # ±0.05% around mid
        "ostium": 0.001,        # ±0.1% around mid
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
        spread_estimates: Optional[Dict[str, float]] = None,
        timeouts: Optional[Dict[str, float]] = None,
    ):
        self._taker_fees = taker_fees or dict(self.DEFAULT_TAKER_FEES)
        self._spread_estimates = spread_estimates or dict(self.DEFAULT_SPREAD_ESTIMATES)
        self._timeouts = timeouts or dict(self.DEFAULT_TIMEOUTS)

    def get_taker_fee(self, exchange: str) -> float:
        return self._taker_fees.get(exchange.lower(), 0.005)

    async def fetch_hyperliquid_prices(self) -> List[PriceQuote]:
        """Fetch Hyperliquid mid prices via Info.all_mids() (sync SDK — runs in thread)."""
        try:
            def _sync_fetch():
                from hyperliquid.info import Info
                from hyperliquid.utils import constants as hl_constants
                info = Info(hl_constants.MAINNET_API_URL, skip_ws=True)
                return info.all_mids()

            mids = await asyncio.to_thread(_sync_fetch)
            quotes = []
            for name, mid in mids.items():
                try:
                    mid_f = float(mid)
                    if mid_f <= 0:
                        continue
                    if name.startswith("#"):
                        continue
                    quotes.append(PriceQuote(
                        exchange="hyperliquid",
                        base=name,
                        bid=mid_f * (1 - self._spread_estimates.get("hyperliquid", 0.0005)),
                        ask=mid_f * (1 + self._spread_estimates.get("hyperliquid", 0.0005)),
                        mid=mid_f,
                    ))
                except (ValueError, TypeError):
                    continue
            logger.debug(f"dex_feed: Hyperliquid got {len(quotes)} quotes")
            return quotes
        except Exception as e:
            logger.warning(f"dex_feed: Hyperliquid fetch failed: {e}")
            return []

    async def fetch_aster_prices(self) -> List[PriceQuote]:
        """Fetch Aster prices via ccxt fetch_tickers()."""
        client = None
        try:
            from backend.clients.aster_client import AsterClient
            client = AsterClient()

            markets = await client.get_markets()
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
                    quotes.append(PriceQuote(
                        exchange="aster",
                        base=base,
                        bid=bid,
                        ask=ask,
                        mid=last or ((bid + ask) / 2 if bid and ask else 0),
                    ))
                except Exception:
                    continue

            logger.debug(f"dex_feed: Aster got {len(quotes)} quotes")
            return quotes
        except Exception as e:
            logger.warning(f"dex_feed: Aster fetch failed: {e}")
            return []
        finally:
            if client:
                await client.close()

    async def fetch_lighter_prices(self) -> List[PriceQuote]:
        """Fetch Lighter prices via AccountApi.order_books()."""
        try:
            from backend.clients.lighter_client import LighterClient
            client = LighterClient(skip_signer=True)
            order_books = await client.get_markets()
            quotes = []
            for ob in order_books:
                # SDK returns objects — convert to dict
                if hasattr(ob, "__dict__") and not isinstance(ob, dict):
                    ob = ob.__dict__
                if not isinstance(ob, dict):
                    continue
                # Lighter uses various key names
                base = ob.get("base_symbol") or ob.get("symbol") or ob.get("name") or ob.get("baseAsset", "")
                if not base:
                    continue
                bids = ob.get("bids") or []
                asks = ob.get("asks") or []
                best_bid = float(bids[0].get("price", 0)) if bids else 0
                best_ask = float(asks[0].get("price", 0)) if asks else 0
                if best_bid <= 0 and best_ask <= 0:
                    continue
                quotes.append(PriceQuote(
                    exchange="lighter",
                    base=str(base).split("/")[0].split("-")[0],
                    bid=best_bid,
                    ask=best_ask,
                    mid=(best_bid + best_ask) / 2 if best_bid and best_ask else 0,
                ))
            logger.debug(f"dex_feed: Lighter got {len(quotes)} quotes")
            return quotes
        except Exception as e:
            logger.warning(f"dex_feed: Lighter fetch failed: {e}")
            return []

    async def fetch_ostium_prices(self) -> List[PriceQuote]:
        """Fetch Ostium prices via subgraph pairs."""
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
                # Try to extract price from market data directly
                price_val = 0.0
                for key in ("price", "mark_price", "last_price", "index_price", "mid_price"):
                    val = m.get(key)
                    if val is not None:
                        try:
                            price_val = float(val)
                            if price_val > 0:
                                break
                        except (ValueError, TypeError):
                            pass
                if price_val <= 0:
                    continue
                spread = self._spread_estimates.get("ostium", 0.001)
                quotes.append(PriceQuote(
                    exchange="ostium",
                    base=str(base).split("/")[0].split("-")[0],
                    bid=price_val * (1 - spread),
                    ask=price_val * (1 + spread),
                    mid=price_val,
                ))
            logger.debug(f"dex_feed: Ostium got {len(quotes)} quotes")
            return quotes
        except Exception as e:
            logger.warning(f"dex_feed: Ostium fetch failed: {e}")
            return []

    async def fetch_all_prices(
        self,
        exchanges: Optional[List[str]] = None,
    ) -> Dict[str, List[PriceQuote]]:
        """Fetch prices from all DEXes in parallel with per-exchange timeouts."""
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
        """Fetch with per-exchange timeout and error handling."""
        try:
            return await asyncio.wait_for(fetcher(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"dex_feed: {name} timeout ({timeout}s)")
        except Exception as e:
            logger.warning(f"dex_feed: {name} failed: {e}")
        return []


# ── Strategy ────────────────────────────────────────────────────────────


class CrossDexArbStrategy(BaseStrategy):
    """Cross-DEX arbitrage detection strategy.

    Fetches prices from all DEXes on each cycle, compares cross-venue
    spreads. Auto-registers as 'cross_dex_arb' in strategy registry.

    Configuration via ctx.params:
        min_profit_pct: float = 0.003  (0.3% minimum net profit)
        gas_estimate: float = 2.0      (estimated settlement cost in USD)
        exchanges: List[str]           (which DEXes to scan, default: all 4)
    """

    name = "cross_dex_arb"
    description = "Cross-DEX real-time arbitrage detection across Hyperliquid, Aster, Lighter, Ostium"
    category = "arbitrage"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._feed = DexPriceFeed()
        self._min_profit_pct = 0.003
        self._gas_estimate = 2.0
        self._exchanges = None

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        """Fetch prices → detect arbs → return decisions."""
        # Parse params from context
        params = ctx.params or {}
        if isinstance(params, str):
            import json
            params = json.loads(params)
        self._min_profit_pct = float(params.get("min_profit_pct", 0.005))
        self._gas_estimate = float(params.get("gas_estimate", 5.0))
        self._exchanges = params.get("exchanges", None)

        t0 = time.monotonic()
        decisions: List[Dict[str, Any]] = []
        errors: List[str] = []

        try:
            all_prices = await self._feed.fetch_all_prices(exchanges=self._exchanges)
        except Exception as e:
            logger.error(f"cross_dex_arb: fetch_all_prices failed: {e}", exc_info=True)
            return CycleResult(
                decisions_recorded=0,
                trades_attempted=0,
                trades_placed=0,
                errors=[str(e)],
                decisions=[],
                cycle_duration_ms=(time.monotonic() - t0) * 1000,
            )

        # Gate: ensure strategy has passed live gate before returning decisions
        if not await ctx.can_trade():
            return CycleResult(
                decisions_recorded=0,
                trades_attempted=0,
                trades_placed=0,
                errors=["gate_not_cleared"],
                decisions=[],
                cycle_duration_ms=(time.monotonic() - t0) * 1000,
            )

        all_opps = _detect_cross_dex_opportunities(
            all_prices,
            min_profit_pct=self._min_profit_pct,
            gas_estimate=self._gas_estimate,
            taker_fees=self._feed._taker_fees,
        )

        decisions = [
            {
                "type": "cross_dex_arb",
                "asset": opp.asset,
                "buy_exchange": opp.buy_exchange,
                "sell_exchange": opp.sell_exchange,
                "buy_price": opp.buy_price,
                "sell_price": opp.sell_price,
                "net_profit_pct": opp.net_profit_pct,
                "confidence": opp.confidence,
                "gross_spread": opp.gross_spread,
            }
            for opp in all_opps
        ]

        elapsed = (time.monotonic() - t0) * 1000
        logger.info(
            f"cross_dex_arb: {len(all_opps)} opportunities "
            f"from {sum(len(v) for v in all_prices.values())} markets "
            f"across {len(all_prices)} DEXes in {elapsed:.0f}ms"
        )

        return CycleResult(
            decisions_recorded=len(decisions),
            trades_attempted=0,
            trades_placed=0,
            errors=errors,
            decisions=decisions,
            cycle_duration_ms=elapsed,
        )


# ── Detection Engine ────────────────────────────────────────────────────


def _detect_cross_dex_opportunities(
    all_prices: Dict[str, List[PriceQuote]],
    min_profit_pct: float = 0.003,
    gas_estimate: float = 2.0,
    taker_fees: Optional[Dict[str, float]] = None,
) -> List[DexArbOpportunity]:
    """Scan all exchange pairs for arbitrage on same asset.

    For each asset listed on 2+ exchanges, compute:
        net_profit = (ask_min - bid_max) - sum(taker_fees) - gas_estimate
    where ask_min is the cheapest place to buy and bid_max is
    the best place to sell.

    Returns opportunities sorted by net profit descending.
    """
    if taker_fees is None:
        taker_fees = {}

    # Index: {asset -> [(exchange, PriceQuote), ...]}
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

                # Buy at exchange i's ask, sell at exchange j's bid
                buy_price = qi.ask
                sell_price = qj.bid
                gross_spread = (sell_price - buy_price) / buy_price

                if gross_spread <= 0:
                    continue

                fee_i = taker_fees.get(ex_i.lower(), 0.005)
                fee_j = taker_fees.get(ex_j.lower(), 0.005)
                total_fees = fee_i + fee_j

                # Convert gas estimate to percentage of trade value
                gas_pct = gas_estimate / buy_price if buy_price > 0 else 0

                net_pct = gross_spread - total_fees - gas_pct

                if net_pct < min_profit_pct:
                    continue

                # Confidence: scaled by how deep the spread is
                confidence = min(1.0, (net_pct - min_profit_pct) / (min_profit_pct * 2))

                opps.append(DexArbOpportunity(
                    asset=asset,
                    buy_exchange=ex_i,
                    sell_exchange=ex_j,
                    buy_price=buy_price,
                    sell_price=sell_price,
                    gross_spread=gross_spread,
                    taker_fees_pct=total_fees,
                    gas_estimate=gas_estimate,
                    net_profit_pct=net_pct,
                    confidence=confidence,
                ))

    # Deduplicate and sort by net profit
    seen = set()
    unique = []
    for o in sorted(opps, key=lambda o: o.net_profit_pct, reverse=True):
        key = (o.asset, o.buy_exchange, o.sell_exchange)
        if key not in seen:
            seen.add(key)
            unique.append(o)

    return unique
