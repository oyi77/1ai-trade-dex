"""Enhanced cross-market arbitrage detection.

Extends the existing cross_market_arb.py with:
- Complementary market detection (multi-outcome events)
- Cross-platform price difference scanning (Polymarket vs Kalshi)
- Profit calculation after fees with execution risk assessment
- Borrow/slippage cost modeling
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional



@dataclass
class ArbOpportunityEnhanced:
    """An enhanced arbitrage opportunity with full cost modeling."""
    event_id: str
    kind: str  # "cross_platform" | "complementary" | "yes_no_sum" | "multi_outcome"
    platform_a: str
    platform_b: str
    market_a_id: str
    market_b_id: str
    price_a: float
    price_b: float
    raw_spread: float
    fees: float
    slippage_cost: float
    execution_risk: float
    net_profit: float
    net_profit_pct: float
    confidence: float
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ScanResult:
    """Result of an arbitrage scan."""
    opportunities: List[ArbOpportunityEnhanced]
    markets_scanned: int
    scan_duration_ms: float
    platform: str = "multi"


class CrossMarketArbEnhanced:
    """Enhanced arbitrage detector with multi-platform and multi-outcome support."""

    def __init__(
        self,
        poly_fee_pct: float = 0.02,
        kalshi_fee_pct: float = 0.07,
        slippage_bps: float = 5.0,
        min_net_profit_pct: float = 0.01,
        max_execution_risk: float = 0.5,
    ):
        self.poly_fee_pct = poly_fee_pct
        self.kalshi_fee_pct = kalshi_fee_pct
        self.slippage_bps = slippage_bps
        self.min_net_profit_pct = min_net_profit_pct
        self.max_execution_risk = max_execution_risk

    def detect_cross_platform(
        self,
        poly_markets: List[Dict[str, Any]],
        kalshi_markets: List[Dict[str, Any]],
    ) -> List[ArbOpportunityEnhanced]:
        """Detect arbitrage between Polymarket and Kalshi for matched markets."""
        opportunities = []
        for poly_m in poly_markets:
            poly_q = (poly_m.get("question") or "").lower()
            poly_price = _extract_yes_price(poly_m)
            if not poly_q or poly_price is None:
                continue

            for kalshi_m in kalshi_markets:
                kalshi_q = (kalshi_m.get("question") or "").lower()
                kalshi_price = _extract_yes_price(kalshi_m)
                if not kalshi_q or kalshi_price is None:
                    continue

                if not _questions_match(poly_q, kalshi_q):
                    continue

                opp = self._compute_cross_platform_arb(
                    poly_m, kalshi_m, poly_price, kalshi_price
                )
                if opp:
                    opportunities.append(opp)

        opportunities.sort(key=lambda o: o.net_profit, reverse=True)
        return opportunities

    def detect_yes_no_sum(self, market: Dict[str, Any]) -> Optional[ArbOpportunityEnhanced]:
        """Detect when YES + NO < 1.0 after fees."""
        yes_price = _extract_yes_price(market)
        no_price = market.get("no_price")
        if yes_price is None or no_price is None:
            # Compute no_price from yes_price if not explicit
            if yes_price is not None:
                no_price = 1.0 - yes_price
            else:
                return None

        total = yes_price + no_price
        if total >= 1.0:
            return None

        raw_profit = 1.0 - total
        fees = self.poly_fee_pct
        slippage = self.slippage_bps / 10000
        net = raw_profit - fees - slippage
        net_pct = net / total if total > 0 else 0

        if net_pct < self.min_net_profit_pct:
            return None

        market_id = str(market.get("conditionId", market.get("market_id", "")))
        return ArbOpportunityEnhanced(
            event_id=market_id,
            kind="yes_no_sum",
            platform_a="polymarket",
            platform_b="polymarket",
            market_a_id=market_id,
            market_b_id=market_id,
            price_a=yes_price,
            price_b=no_price,
            raw_spread=raw_profit,
            fees=fees,
            slippage_cost=slippage,
            execution_risk=0.1,
            net_profit=net,
            net_profit_pct=net_pct,
            confidence=min(1.0, net_pct / 0.05),
            details={"yes_no_sum": total},
        )

    def detect_complementary(
        self, markets: List[Dict[str, Any]], event_id_key: str = "event_id"
    ) -> List[ArbOpportunityEnhanced]:
        """Detect arbitrage across complementary markets (multi-outcome events)."""
        opportunities = []
        # Group markets by event
        event_groups: Dict[str, List[Dict[str, Any]]] = {}
        for m in markets:
            eid = m.get(event_id_key) or m.get("conditionId", "")
            if eid:
                event_groups.setdefault(str(eid), []).append(m)

        for eid, group in event_groups.items():
            if len(group) < 2:
                continue
            prices = []
            for m in group:
                p = _extract_yes_price(m)
                if p is not None:
                    prices.append((m, p))

            total_prob = sum(p for _, p in prices)
            if total_prob < 1.0:
                raw_profit = 1.0 - total_prob
                fees = self.poly_fee_pct * len(prices)
                slippage = (self.slippage_bps / 10000) * len(prices)
                net = raw_profit - fees - slippage

                if net > 0:
                    opp = ArbOpportunityEnhanced(
                        event_id=eid,
                        kind="multi_outcome",
                        platform_a="polymarket",
                        platform_b="polymarket",
                        market_a_id=str(prices[0][0].get("conditionId", "")),
                        market_b_id=str(prices[-1][0].get("conditionId", "")),
                        price_a=prices[0][1],
                        price_b=prices[-1][1],
                        raw_spread=raw_profit,
                        fees=fees,
                        slippage_cost=slippage,
                        execution_risk=0.2,
                        net_profit=net,
                        net_profit_pct=net / total_prob if total_prob > 0 else 0,
                        confidence=min(1.0, net / 0.05),
                        details={"n_outcomes": len(prices), "total_prob": total_prob},
                    )
                    opportunities.append(opp)

        return opportunities

    def scan_all(
        self,
        poly_markets: List[Dict[str, Any]],
        kalshi_markets: Optional[List[Dict[str, Any]]] = None,
    ) -> ScanResult:
        """Run a full arbitrage scan across all detection methods."""
        start = time.monotonic()
        all_opps: List[ArbOpportunityEnhanced] = []

        # 1. Yes/No sum arbitrage
        for m in poly_markets:
            opp = self.detect_yes_no_sum(m)
            if opp:
                all_opps.append(opp)

        # 2. Complementary markets
        comp_opps = self.detect_complementary(poly_markets)
        all_opps.extend(comp_opps)

        # 3. Cross-platform
        if kalshi_markets:
            cross_opps = self.detect_cross_platform(poly_markets, kalshi_markets)
            all_opps.extend(cross_opps)

        # Filter by execution risk
        all_opps = [o for o in all_opps if o.execution_risk <= self.max_execution_risk]
        all_opps.sort(key=lambda o: o.net_profit, reverse=True)

        elapsed = (time.monotonic() - start) * 1000
        return ScanResult(
            opportunities=all_opps,
            markets_scanned=len(poly_markets) + (len(kalshi_markets) if kalshi_markets else 0),
            scan_duration_ms=elapsed,
        )

    def _compute_cross_platform_arb(
        self,
        poly_m: Dict[str, Any],
        kalshi_m: Dict[str, Any],
        poly_price: float,
        kalshi_price: float,
    ) -> Optional[ArbOpportunityEnhanced]:
        """Compute cross-platform arbitrage opportunity."""
        spread = abs(poly_price - kalshi_price)
        total_fees = self.poly_fee_pct + self.kalshi_fee_pct
        slippage = self.slippage_bps / 10000 * 2  # both sides
        net = spread - total_fees - slippage
        min_price = min(poly_price, kalshi_price)
        net_pct = net / min_price if min_price > 0 else 0

        if net_pct < self.min_net_profit_pct:
            return None

        cheaper = "polymarket" if poly_price < kalshi_price else "kalshi"
        poly_id = str(poly_m.get("conditionId", ""))
        kalshi_id = str(kalshi_m.get("id", kalshi_m.get("ticker", "")))

        return ArbOpportunityEnhanced(
            event_id=f"{poly_id}:{kalshi_id}",
            kind="cross_platform",
            platform_a="polymarket",
            platform_b="kalshi",
            market_a_id=poly_id,
            market_b_id=kalshi_id,
            price_a=poly_price,
            price_b=kalshi_price,
            raw_spread=spread,
            fees=total_fees,
            slippage_cost=slippage,
            execution_risk=0.3,
            net_profit=net,
            net_profit_pct=net_pct,
            confidence=min(1.0, net_pct / 0.03),
            details={"cheaper": cheaper},
        )


def _extract_yes_price(market: Dict[str, Any]) -> Optional[float]:
    """Extract YES price from a market dict."""
    for key in ("yes_price", "yesPrice", "price"):
        val = market.get(key)
        if val is not None:
            try:
                p = float(val)
                if 0 < p < 1:
                    return p
            except (ValueError, TypeError):
                pass
    # Try outcomePrices
    op = market.get("outcomePrices")
    if op:
        try:
            import json as _json
            if isinstance(op, str):
                op = _json.loads(op)
            if isinstance(op, list) and len(op) >= 1:
                p = float(op[0])
                if 0 < p < 1:
                    return p
        except Exception:
            pass
    return None


_STOP_WORDS = frozenset({
    "will", "the", "be", "in", "a", "an", "on", "at", "to", "for",
    "of", "and", "or", "is", "it", "by", "as", "do", "does", "did",
    "has", "have", "had", "was", "were", "are", "this", "that",
    "with", "from", "but", "not", "no", "if", "so", "than",
})


def _questions_match(q1: str, q2: str) -> bool:
    """Check if two market questions refer to the same event.

    Uses 70% overlap of meaningful (non-stop) words plus entity matching
    for numbers and capitalized tokens.
    """
    import re

    words1 = set(q1.lower().split()) - _STOP_WORDS
    words2 = set(q2.lower().split()) - _STOP_WORDS
    if not words1 or not words2:
        return False

    # 70% overlap of meaningful words
    overlap = words1 & words2
    min_len = min(len(words1), len(words2))
    if len(overlap) / min_len < 0.7:
        return False

    # Extract key entities: numbers and proper-noun-like tokens from originals
    def _entities(text: str) -> set[str]:
        tokens = set()
        for tok in re.findall(r"[A-Za-z0-9]+", text):
            if tok[0].isdigit() or (len(tok) > 1 and tok[0].isupper() and tok.lower() not in _STOP_WORDS):
                tokens.add(tok.lower())
        return tokens

    ent1 = _entities(q1)
    ent2 = _entities(q2)
    # If either question has entities, they must overlap
    if ent1 and ent2:
        ent_overlap = ent1 & ent2
        if not ent_overlap:
            return False

    return True
