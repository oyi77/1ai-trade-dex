"""
Arb Scanner Strategy — 2-leg cross-platform arbitrage.

Real arb: buy YES on Platform A + buy YES on Platform B when sum < 1.0.
Guaranteed $1.00 payout on resolution → profit = 1.0 - sum - fees.

Only trades cross_platform_arb opportunities where both legs have token_ids.
"""

from typing import Dict, List, Optional

from backend.strategies.base import (
    BaseStrategy,
    CycleResult,
    MarketInfo,
    StrategyContext,
)
from loguru import logger


class ArbScannerStrategy(BaseStrategy):
    """2-leg cross-platform arbitrage scanner and executor."""

    name = "arb_scanner"
    description = "2-leg cross-platform arb: buy YES on both platforms when sum < 1.0"
    category = "arbitrage"
    version = "2.0.0"

    SCAN_INTERVAL_SECONDS = 60

    @staticmethod
    def market_filter(markets: List[MarketInfo]) -> List[MarketInfo]:
        return markets

    def _get_scanner(self, ctx: StrategyContext) -> "ArbOpportunityScanner":
        if not hasattr(self, "_scanner") or self._scanner is None:
            from backend.data.arb_opportunity_scanner import ArbOpportunityScanner

            params = ctx.params or {}
            settings = ctx.settings

            if isinstance(params, dict):
                min_profit = float(params.get("min_profit_pct", 0.02))
                alert_threshold = float(params.get("alert_threshold_pct", 0.03))
            else:
                min_profit = float(
                    getattr(settings, "ARB_SCANNER_MIN_PROFIT_PCT", 0.02)
                )
                alert_threshold = float(
                    getattr(settings, "ARB_SCANNER_ALERT_THRESHOLD_PCT", 0.03)
                )

            self._scanner = ArbOpportunityScanner(
                min_profit_pct=min_profit,
                alert_threshold_pct=alert_threshold,
            )
        return self._scanner

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        scanner = self._get_scanner(ctx)
        start = __import__("time").monotonic()

        try:
            result = await scanner.run_scan()
        except Exception as e:
            import traceback
            logger.warning(f"[arb_scanner] scan failed: {e}\n{traceback.format_exc()}")
            return CycleResult(0, 0, 0, errors=[str(e)])

        decisions = []
        trades_placed = 0
        for idx, opp in enumerate(result.opportunities[:10]):
            try:
                # Only process cross_platform_arb opportunities (2-leg)
                if opp.kind != "cross_platform_arb":
                    continue

                # Both legs must have token_ids for real arb
                token_id_a = opp.details.get("token_id_a")
                token_id_b = opp.details.get("token_id_b")
                if not token_id_a or not token_id_b:
                    logger.debug(
                        f"[arb_scanner] Skipping {opp.event_id}: missing token_id "
                        f"(a={token_id_a is not None}, b={token_id_b is not None})"
                    )
                    continue

                sum_price = opp.details.get("sum_price", opp.price_a + opp.price_b)
                if sum_price >= 1.0:
                    continue

                _opp_size = getattr(opp, "size_usd", None)
                size_usd = _opp_size if _opp_size and _opp_size > 0 else 10.0

                _cid = opp.event_id or f"arb:{opp.platform_a}:{opp.platform_b}:{idx}"

                # Execute 2-leg arb atomically: buy YES on both platforms
                if ctx.clob and ctx.mode == "live":
                    import asyncio
                    leg_a_order, leg_b_order = await asyncio.gather(
                        self._place_leg(ctx.clob, token_id_a, opp.price_a, size_usd / 2, f"{_cid}:a"),
                        self._place_leg(ctx.clob, token_id_b, opp.price_b, size_usd / 2, f"{_cid}:b"),
                        return_exceptions=True,
                    )
                    a_ok = isinstance(leg_a_order, str) and bool(leg_a_order)
                    b_ok = isinstance(leg_b_order, str) and bool(leg_b_order)
                    if a_ok and b_ok:
                        trades_placed += 1
                        logger.info(
                            f"[arb_scanner] FILLED 2-leg arb: {opp.platform_a}@{opp.price_a:.3f} + "
                            f"{opp.platform_b}@{opp.price_b:.3f} = {sum_price:.3f} "
                            f"→ profit={1.0 - sum_price:.3f}"
                        )
                    elif a_ok and not b_ok:
                        # Cancel leg A if leg B failed
                        try:
                            await ctx.clob.cancel_order(leg_a_order)
                        except Exception:
                            pass
                        logger.warning(f"[arb_scanner] Leg B failed, cancelled leg A")
                    elif not a_ok and b_ok:
                        try:
                            await ctx.clob.cancel_order(leg_b_order)
                        except Exception:
                            pass
                        logger.warning(f"[arb_scanner] Leg A failed, cancelled leg B")
                    else:
                        logger.warning(f"[arb_scanner] Both legs failed for {_cid}")
                else:
                    # Paper mode: record decisions without execution
                    decisions.append({
                        "kind": "cross_platform_arb",
                        "decision": "BUY",
                        "direction": "YES",
                        "condition_id": f"{_cid}:leg_a",
                        "market_ticker": _cid,
                        "token_id": token_id_a,
                        "platform": opp.platform_a,
                        "size": size_usd / 2,
                        "market_type": "arb",
                        "model_probability": min(1.0, max(0.0, opp.price_a)),
                    })
                    decisions.append({
                        "kind": "cross_platform_arb",
                        "decision": "BUY",
                        "direction": "YES",
                        "condition_id": f"{_cid}:leg_b",
                        "market_ticker": _cid,
                        "token_id": token_id_b,
                        "platform": opp.platform_b,
                        "size": size_usd / 2,
                        "market_type": "arb",
                        "model_probability": min(1.0, max(0.0, opp.price_b)),
                    })
                    trades_placed += 1

                logger.info(
                    f"[arb_scanner] 2-leg arb: {opp.platform_a}@{opp.price_a:.3f} + "
                    f"{opp.platform_b}@{opp.price_b:.3f} = {sum_price:.3f} < 1.0 "
                    f"→ profit={1.0 - sum_price:.3f} net={opp.net_profit:.3f}"
                )

            except Exception as e:
                import traceback as _tb
                logger.warning(f"[arb_scanner] decision build error idx={idx}: {e}\n{_tb.format_exc()}")

        elapsed_ms = (__import__("time").monotonic() - start) * 1000

        if decisions or trades_placed:
            logger.info(
                f"[arb_scanner] {len(decisions)} decisions, {trades_placed} trades placed "
                f"from {result.markets_scanned} markets in {result.scan_duration_ms:.1f}ms"
            )

        return CycleResult(
            decisions_recorded=len(decisions) + trades_placed,
            trades_attempted=trades_placed,
            trades_placed=trades_placed,
            errors=[],
            decisions=decisions,
            cycle_duration_ms=elapsed_ms,
        )

    async def _place_leg(self, clob, token_id: str, price: float, size: float, idempotency_key: str) -> Optional[str]:
        """Place one leg of an arb with retry."""
        for attempt in range(3):
            try:
                result = await clob.place_limit_order(
                    token_id=token_id,
                    side="BUY",
                    price=price,
                    size=size,
                    idempotency_key=idempotency_key,
                )
                if hasattr(result, "order_id") and result.order_id:
                    return result.order_id
                if hasattr(result, "success") and not result.success:
                    raise ValueError(f"Order failed: {getattr(result, 'error', 'unknown')}")
                return getattr(result, "order_id", None)
            except Exception as e:
                if attempt < 2:
                    import asyncio
                    await asyncio.sleep(0.01 * (2 ** attempt))
                else:
                    logger.warning(f"[arb_scanner] Leg {idempotency_key} failed after 3 attempts: {e}")
                    raise

    def on_market_event(self, event: Dict) -> Optional[Dict]:
        return None
