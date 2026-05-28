"""Unified Arb Strategy — consolidates all arb strategies into one.

Replaces: arb_scanner, cross_market_arb, hft_cross_arb, cross_dex_arb
Uses provider plugin pattern with auto-discovery.
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Tuple, Union

from backend.strategies.base import BaseStrategy, CycleResult, StrategyContext
from backend.strategies.unified_arb.types import (
    ArbKind,
    ArbOpportunity,
    DEXProvider,
    FeeSchedule,
    OrderResult,
    PMMarket,
    PMProvider,
    SpotMarket,
)
from backend.strategies.unified_arb.providers import ALL_PROVIDERS, PM_PROVIDERS, DEX_PROVIDERS

logger = logging.getLogger(__name__)


def _kelly_size(
    edge: float,
    bankroll: float,
    max_size: float,
    kelly_fraction: float = 0.25,
) -> float:
    """Fractional Kelly criterion position sizing.

    Pure function — no venue-specific logic.
    """
    if edge <= 0 or bankroll <= 0:
        return 0.0
    # Kelly: f* = edge / odds, where odds = payout for $1 bet
    # For binary arb: odds ~= 1 (you get $1 back on $1 bet, minus fees)
    # Fractional Kelly: use kelly_fraction of full Kelly
    kelly = min(edge * kelly_fraction, 0.5)  # cap at 50% of bankroll
    size = bankroll * kelly
    return min(size, max_size)


class UnifiedArbStrategy(BaseStrategy):
    """Unified arbitrage strategy with pluggable providers.

    Replaces arb_scanner, cross_market_arb, hft_cross_arb, cross_dex_arb.
    """

    name = "unified_arb"

    default_params = {
        "min_edge": 0.02,
        "min_volume": 1000,
        "min_liquidity": 500,
        "max_open_positions": 5,
        "max_per_asset": 2,
        "stop_loss_pct": 0.10,
        "profit_target_pct": 0.08,
        "kelly_fraction": 0.25,
        "max_exposure": 500.0,
        "max_batch_arbs": 5,
        "cycle_timeout": 60,
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._providers = []
        self._pm_providers = []
        self._dex_providers = []
        self._initialized = False
        self._execution_history: List[Dict[str, Any]] = []

    def _init_providers(self, ctx: StrategyContext):
        """Initialize providers from context."""
        if self._initialized:
            return

        clob = getattr(ctx, "clob", None)
        mode = getattr(ctx, "mode", "paper")

        # Create provider instances
        for provider_cls in ALL_PROVIDERS:
            try:
                if provider_cls in PM_PROVIDERS:
                    if provider_cls.venue_name == "polymarket":
                        p = provider_cls(clob=clob)
                    elif provider_cls.venue_name == "kalshi":
                        # Kalshi client from context or import
                        kalshi_client = None
                        try:
                            from backend.clients.kalshi_client import KalshiClient
                            kalshi_client = KalshiClient()
                        except Exception:
                            pass
                        p = provider_cls(kalshi_client=kalshi_client)
                    else:
                        p = provider_cls()
                    self._pm_providers.append(p)
                else:
                    p = provider_cls()
                    self._dex_providers.append(p)
                self._providers.append(p)
            except Exception as e:
                logger.warning(f"[unified_arb] Failed to init {provider_cls.venue_name}: {e}")

        self._initialized = True
        logger.info(
            f"[unified_arb] Initialized {len(self._pm_providers)} PM + "
            f"{len(self._dex_providers)} DEX providers"
        )

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        """Main cycle: fetch → detect → dedup → execute."""
        self._init_providers(ctx)
        start = time.monotonic()

        try:
            # Phase 1: Fetch markets from all providers in parallel
            pm_markets, dex_markets = await self._fetch_all()

            # Phase 2: Detect opportunities
            pm_opps = self._detect_pm_arb(pm_markets)
            dex_opps = self._detect_dex_arb(dex_markets)

            # Phase 3: Merge and dedup
            all_opps = pm_opps + dex_opps
            deduped = self._dedup(all_opps)
            deduped.sort(key=lambda o: o.net_profit, reverse=True)

            # Phase 4: Execute top N
            max_batch = self.params.get("max_batch_arbs", 5)
            trades_placed = 0
            decisions = []

            for opp in deduped[:max_batch]:
                if opp.kind == ArbKind.CROSS_PLATFORM or opp.kind == ArbKind.YES_NO_SUM:
                    # PM arb — has execution
                    result = await self._execute_pm_arb(opp, ctx)
                    if result.get("success"):
                        trades_placed += 1
                    decisions.append(opp)
                elif opp.kind == ArbKind.CROSS_DEX:
                    # DEX arb — detection only (execution deferred)
                    decisions.append(opp)
                    logger.info(
                        f"[unified_arb] DEX arb detected: {opp.platform_a}@{opp.price_a:.4f} + "
                        f"{opp.platform_b}@{opp.price_b:.4f} = net {opp.net_profit:.4f} "
                        f"(execution deferred)"
                    )

            elapsed_ms = (time.monotonic() - start) * 1000

            return CycleResult(
                decisions_recorded=len(decisions),
                trades_attempted=trades_placed,
                trades_placed=trades_placed,
                errors=[],
                cycle_duration_ms=elapsed_ms,
            )

        except Exception as e:
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.warning(f"[unified_arb] Cycle failed: {e}")
            return CycleResult(
                decisions_recorded=0,
                trades_attempted=0,
                trades_placed=0,
                errors=[str(e)],
                cycle_duration_ms=elapsed_ms,
            )

    async def _fetch_all(self) -> Tuple[List[PMMarket], List[SpotMarket]]:
        """Fetch from all providers in parallel with semaphore."""
        sem = asyncio.Semaphore(10)
        limit = 500

        async def _fetch_one(provider):
            async with sem:
                try:
                    return await provider.fetch_markets(limit=limit)
                except Exception as e:
                    logger.warning(f"[unified_arb] {provider.venue_name} fetch failed: {e}")
                    return []

        tasks = [_fetch_one(p) for p in self._providers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        pm_markets = []
        dex_markets = []
        for provider, result in zip(self._providers, results):
            if isinstance(result, Exception):
                continue
            if isinstance(provider, PMProvider):
                pm_markets.extend([m for m in result if isinstance(m, PMMarket)])
            elif isinstance(provider, DEXProvider):
                dex_markets.extend([m for m in result if isinstance(m, SpotMarket)])

        return pm_markets, dex_markets

    def _detect_pm_arb(self, markets: List[PMMarket]) -> List[ArbOpportunity]:
        """Detect PM arbitrage: cross-platform YES+YES < 1.0."""
        from backend.strategies.cross_market_arb_enhanced import CrossMarketArbEnhanced

        opps = []
        # Group by event_id or question similarity
        by_event: Dict[str, List[PMMarket]] = {}
        for m in markets:
            key = m.event_id or m.slug or m.question[:50]
            by_event.setdefault(key, []).append(m)

        for event_key, group in by_event.items():
            if len(group) < 2:
                continue
            # Check pairwise for cross-platform arb
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    a, b = group[i], group[j]
                    if a.platform == b.platform:
                        continue
                    # Cross-platform: buy YES on both sides
                    sum_price = a.yes_price + b.yes_price
                    if sum_price < 1.0:
                        gross = 1.0 - sum_price
                        fees = (a.fee_pct * a.yes_price) + (b.fee_pct * b.yes_price)
                        net = gross - fees
                        if net > self.params.get("min_edge", 0.02):
                            opps.append(ArbOpportunity(
                                kind=ArbKind.CROSS_PLATFORM,
                                platform_a=a.platform,
                                platform_b=b.platform,
                                price_a=a.yes_price,
                                price_b=b.yes_price,
                                token_id_a=a.token_id_yes,
                                token_id_b=b.token_id_yes,
                                net_profit=net,
                                gross_profit=gross,
                                fees=fees,
                                event_id=event_key,
                                question=a.question or b.question,
                            ))

        return opps

    def _detect_dex_arb(self, markets: List[SpotMarket]) -> List[ArbOpportunity]:
        """Detect DEX arb: same asset on 2 exchanges, spread > fees."""
        # Group by base asset
        by_asset: Dict[str, List[SpotMarket]] = {}
        for m in markets:
            by_asset.setdefault(m.base.upper(), []).append(m)

        opps = []
        for asset, group in by_asset.items():
            if len(group) < 2:
                continue
            # Pairwise comparison
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    a, b = group[i], group[j]
                    # Buy at cheapest ask, sell at best bid
                    buy_price = min(a.ask, b.ask)
                    sell_price = max(a.bid, b.bid)
                    buy_exchange = a.exchange if a.ask <= b.ask else b.exchange
                    sell_exchange = b.exchange if a.ask <= b.ask else a.exchange

                    if buy_price <= 0 or sell_price <= 0:
                        continue
                    gross_spread = sell_price - buy_price
                    if gross_spread <= 0:
                        continue

                    gross_pct = gross_spread / buy_price
                    fee_pct = a.fee_pct + b.fee_pct
                    net_pct = gross_pct - fee_pct

                    if net_pct > self.params.get("min_edge", 0.02):
                        opps.append(ArbOpportunity(
                            kind=ArbKind.CROSS_DEX,
                            platform_a=buy_exchange,
                            platform_b=sell_exchange,
                            price_a=buy_price,
                            price_b=sell_price,
                            net_profit=net_pct,
                            gross_profit=gross_pct,
                            fees=fee_pct,
                            event_id=asset,
                            question=f"{asset} spread {buy_exchange}→{sell_exchange}",
                            details={"asset": asset},
                        ))

        return opps

    def _dedup(self, opps: List[ArbOpportunity]) -> List[ArbOpportunity]:
        """Deduplicate opportunities. Keep highest net_profit per key.

        PM key: (event_id, arb_kind, frozenset({platform_a, platform_b}))
        DEX key: (asset, platform_a, platform_b)
        """
        seen: Dict[str, ArbOpportunity] = {}
        for opp in opps:
            if opp.kind == ArbKind.CROSS_DEX:
                asset = opp.details.get("asset", opp.event_id)
                key = (asset, *sorted([opp.platform_a, opp.platform_b]))
            else:
                key = (opp.event_id, opp.kind.value, *sorted([opp.platform_a, opp.platform_b]))
            key_str = str(key)
            if key_str not in seen or opp.net_profit > seen[key_str].net_profit:
                seen[key_str] = opp
        return list(seen.values())

    async def _execute_pm_arb(self, opp: ArbOpportunity, ctx: StrategyContext) -> Dict[str, Any]:
        """Execute PM arb atomically — both legs via asyncio.gather."""
        mode = getattr(ctx, "mode", "paper")
        if mode == "paper":
            return {"success": True, "mode": "paper"}

        # Find providers for each platform
        provider_a = None
        provider_b = None
        for p in self._pm_providers:
            if p.venue_name == opp.platform_a:
                provider_a = p
            if p.venue_name == opp.platform_b:
                provider_b = p

        if not provider_a or not provider_b:
            return {"success": False, "error": "provider_not_found"}

        # Kelly sizing
        bankroll = getattr(ctx, "bankroll", 1000.0)
        size = _kelly_size(
            edge=opp.net_profit,
            bankroll=bankroll,
            max_size=self.params.get("max_exposure", 500.0),
            kelly_fraction=self.params.get("kelly_fraction", 0.25),
        )
        if size < 5.0:
            return {"success": False, "error": "size_too_small"}

        idempotency_key = f"{opp.event_id}:{opp.platform_a}:{opp.platform_b}"

        # Atomic execution
        leg_a, leg_b = await asyncio.gather(
            provider_a.place_order(opp.token_id_a, "BUY", opp.price_a, size / 2, f"{idempotency_key}:a"),
            provider_b.place_order(opp.token_id_b, "BUY", opp.price_b, size / 2, f"{idempotency_key}:b"),
            return_exceptions=True,
        )

        a_ok = isinstance(leg_a, OrderResult) and leg_a.status == "filled"
        b_ok = isinstance(leg_b, OrderResult) and leg_b.status == "filled"

        if a_ok and b_ok:
            self._execution_history.append({
                "opp": opp,
                "size": size,
                "leg_a": leg_a,
                "leg_b": leg_b,
                "timestamp": time.time(),
            })
            logger.info(
                f"[unified_arb] FILLED: {opp.platform_a}@{opp.price_a:.3f} + "
                f"{opp.platform_b}@{opp.price_b:.3f} net={opp.net_profit:.3f} size=${size:.2f}"
            )
            return {"success": True, "size": size}

        # Partial fill — cancel the successful leg
        if a_ok and not b_ok:
            try:
                await provider_a.cancel_order(leg_a.order_id)
            except Exception:
                pass
            logger.warning(f"[unified_arb] Leg B failed, cancelled leg A")
        elif not a_ok and b_ok:
            try:
                await provider_b.cancel_order(leg_b.order_id)
            except Exception:
                pass
            logger.warning(f"[unified_arb] Leg A failed, cancelled leg B")

        return {"success": False, "error": "partial_fill_cancelled"}
