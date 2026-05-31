"""
Arb Scanner Strategy — cross-platform arbitrage opportunity scanner.
"""

from typing import Dict, List, Optional, Any

from backend.strategies.base import (
    BaseStrategy,
    CycleResult,
    MarketInfo,
    StrategyContext,
)
from loguru import logger


class ArbScannerStrategy(BaseStrategy):
    """BaseStrategy wrapper for ArbOpportunityScanner — runs in strategy cycle."""

    name = "arb_scanner"
    description = "Cross-platform arbitrage scanner: Polymarket vs Kalshi, yes/no sum, complementary markets"
    category = "arbitrage"
    version = "1.0.0"

    SCAN_INTERVAL_SECONDS = 30

    @staticmethod
    def market_filter(markets: List[MarketInfo]) -> List[MarketInfo]:
        return markets

    def _get_scanner(self, ctx: StrategyContext) -> Any:
        if not hasattr(self, "_scanner") or self._scanner is None:
            from backend.data.arb_opportunity_scanner import ArbOpportunityScanner

            params = ctx.params or {}
            settings = ctx.settings

            # ctx.params can be a dict or a string (JSON). Handle both.
            if isinstance(params, dict):
                min_profit = float(params.get("min_profit_pct", 0.01))
                alert_threshold = float(params.get("alert_threshold_pct", 0.03))
            else:
                min_profit = float(
                    getattr(settings, "ARB_SCANNER_MIN_PROFIT_PCT", 0.01)
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
        import json as _json

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
                _opp_size = getattr(opp, "size_usd", None)
                size_usd = _opp_size if _opp_size and _opp_size > 0 else 10.0
                # condition_id must be unique per opportunity to avoid duplicate-trade guard blocking
                _uniq_suffix = f"{opp.platform_a}:{opp.platform_b}:{opp.price_a:.4f}:{opp.price_b:.4f}:{opp.kind}:{idx}"
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
                    "model_probability": 0.5 + opp.net_profit_pct,
                }
                decisions.append(decision)

                try:
                    from backend.models.database import DecisionLog
                    slug = opp.event_id or "unknown"
                    log_row = DecisionLog(
                        strategy=self.name,
                        market_ticker=slug[:64],
                        decision="ARB",
                        confidence=opp.confidence,
                        signal_data=_json.dumps(decision),
                        reason=(
                            f"{opp.kind}: {opp.platform_a}@{opp.price_a:.3f} vs "
                            f"{opp.platform_b}@{opp.price_b:.3f} | "
                            f"net={opp.net_profit_pct:.2%} edge"
                        ),
                    )
                    ctx.db.add(log_row)
                except Exception as e:
                    ctx.logger.debug(f"[arb_scanner] DecisionLog error: {e}")
            except Exception as e:
                import traceback as _tb
                logger.warning(f"[arb_scanner] decision build error idx={idx}: {e}\n{_tb.format_exc()}")

        try:
            ctx.db.commit()
        except Exception as e:
            ctx.logger.warning(f"[arb_scanner] DB commit failed: {e}")
            ctx.db.rollback()

        elapsed_ms = (__import__("time").monotonic() - start) * 1000

        if decisions:
            logger.info(
                f"[arb_scanner] {len(decisions)} arb opportunities from "
                f"{result.markets_scanned} markets in {result.scan_duration_ms:.1f}ms. "
                f"First decision keys: {list(decisions[0].keys()) if decisions else []}"
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
