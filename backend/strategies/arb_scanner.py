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

                # Leg A: buy YES on platform A
                decision_a = {
                    "kind": "cross_platform_arb",
                    "decision": "BUY",
                    "direction": "YES",
                    "condition_id": f"{_cid}:leg_a",
                    "market_ticker": _cid,
                    "token_id": token_id_a,
                    "platform": opp.platform_a,
                    "size": size_usd / 2,  # Split size across both legs
                    "market_type": "arb",
                    "model_probability": min(1.0, max(0.0, opp.price_a)),
                    "details": {
                        "leg": "a",
                        "sum_price": sum_price,
                        "gross_profit": 1.0 - sum_price,
                        "arb_type": "two_leg",
                        "partner_platform": opp.platform_b,
                        "partner_token_id": token_id_b,
                    },
                }

                # Leg B: buy YES on platform B
                decision_b = {
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
                    "details": {
                        "leg": "b",
                        "sum_price": sum_price,
                        "gross_profit": 1.0 - sum_price,
                        "arb_type": "two_leg",
                        "partner_platform": opp.platform_a,
                        "partner_token_id": token_id_a,
                    },
                }

                decisions.append(decision_a)
                decisions.append(decision_b)

                logger.info(
                    f"[arb_scanner] 2-leg arb: {opp.platform_a}@{opp.price_a:.3f} + "
                    f"{opp.platform_b}@{opp.price_b:.3f} = {sum_price:.3f} < 1.0 "
                    f"→ profit={1.0 - sum_price:.3f} net={opp.net_profit:.3f}"
                )

            except Exception as e:
                import traceback as _tb
                logger.warning(f"[arb_scanner] decision build error idx={idx}: {e}\n{_tb.format_exc()}")

        elapsed_ms = (__import__("time").monotonic() - start) * 1000

        if decisions:
            logger.info(
                f"[arb_scanner] {len(decisions)} decisions ({len(decisions)//2} arb pairs) "
                f"from {result.markets_scanned} markets in {result.scan_duration_ms:.1f}ms"
            )

        return CycleResult(
            decisions_recorded=len(decisions),
            trades_attempted=len(decisions),
            trades_placed=0,
            errors=[],
            decisions=decisions,
            cycle_duration_ms=elapsed_ms,
        )

    def on_market_event(self, event: Dict) -> Optional[Dict]:
        return None
