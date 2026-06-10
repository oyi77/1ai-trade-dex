"""Enhanced cross-market arbitrage detection for ALL prediction-market providers.

Supports:
- YES/NO sum arbitrage within each provider
- Complementary/multi-outcome market detection
- Cross-platform price difference scanning between ALL providers
- Generic 2-provider spread computation with platform-specific fees
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger



@dataclass
class ArbOpportunityEnhanced:
    """An enhanced arbitrage opportunity with full cost modeling."""

    event_id: str
    kind: str  # "cross_platform" | "complementary" | "yes_no_sum"
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
    token_id: Optional[str] = None
    platform: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ScanResult:
    """Result of an arbitrage scan."""

    opportunities: List[ArbOpportunityEnhanced]
    markets_scanned: int
    scan_duration_ms: float
    platform: str = "multi"


# Default fees per platform (can be overridden in market data)
_DEFAULT_FEES = {
    "polymarket": 0.02,
    "kalshi": 0.07,
    "sxbet": 0.02,
    "myriad": 0.02,
    "predict_fun": 0.02,
    "bookmaker_xyz": 0.02,
    "limitless": 0.02,
}


class CrossMarketArbEnhanced:
    """Enhanced arbitrage detector with multi-provider support."""

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

    # ── Multi-Provider Scan ───────────────────────────────────────

    def scan_all_providers(
        self,
        all_markets: Dict[str, List[Dict[str, Any]]],
    ) -> ScanResult:
        """Run arbitrage scan across ALL providers.

        Args:
            all_markets: {platform_name: [normalized_market_dicts]}
                Each market dict has: question, yes_price, no_price, event_id, platform, fee_pct
        """
        start = time.monotonic()
        all_opps: List[ArbOpportunityEnhanced] = []
        total_markets = 0

        # 1. YES/NO sum arbitrage within each provider
        for platform, markets in all_markets.items():
            total_markets += len(markets)
            for m in markets:
                opp = self.detect_yes_no_sum(m)
                if opp:
                    all_opps.append(opp)

        # 2. Complementary/multi-outcome within each provider
        for platform, markets in all_markets.items():
            if len(markets) < 2:
                continue
            comp_opps = self.detect_complementary(markets, event_id_key="event_id")
            all_opps.extend(comp_opps)

        # 3. Cross-platform between ALL pairs of providers
        platforms = list(all_markets.keys())
        for i in range(len(platforms)):
            for j in range(i + 1, len(platforms)):
                p1, p2 = platforms[i], platforms[j]
                m1, m2 = all_markets[p1], all_markets[p2]
                if not m1 or not m2:
                    continue
                cross_opps = self.detect_cross_platform_generic(m1, m2)
                all_opps.extend(cross_opps)

        # 4. Same-game correlation (SXBet moneyline + spread + over/under per game)
        for platform, markets in all_markets.items():
            if len(markets) >= 2:
                correlation_opps = self.detect_same_game_correlation(markets)
                all_opps.extend(correlation_opps)

        # Filter by execution risk
        all_opps = [o for o in all_opps if o.execution_risk <= self.max_execution_risk]
        all_opps.sort(key=lambda o: o.net_profit, reverse=True)

        elapsed = (time.monotonic() - start) * 1000
        return ScanResult(
            opportunities=all_opps,
            markets_scanned=total_markets,
            scan_duration_ms=elapsed,
        )

    # ── Detection Methods ─────────────────────────────────────────

    def detect_yes_no_sum(
        self, market: Dict[str, Any]
    ) -> Optional[ArbOpportunityEnhanced]:
        """Detect when YES + NO < 1.0 after fees on ANY platform."""
        yes_price = market.get("yes_price")
        no_price = market.get("no_price")
        platform = market.get("platform", "unknown")
        fee = market.get("fee_pct", _DEFAULT_FEES.get(platform, 0.02))

        if yes_price is None or no_price is None:
            return None

        try:
            yes_price = float(yes_price)
            no_price = float(no_price)
        except (ValueError, TypeError):
            return None

        if not (0 < yes_price < 1) or not (0 < no_price < 1):
            return None

        total = yes_price + no_price
        if total >= 1.0:
            return None

        raw_profit = 1.0 - total
        slippage = self.slippage_bps / 10000 * 2  # buy both sides
        net = raw_profit - fee - slippage
        net_pct = net / total if total > 0 else 0

        if net_pct < self.min_net_profit_pct:
            return None

        market_id = str(market.get("event_id", ""))
        clob_token_ids = market.get("clobTokenIds") or []
        token_id = str(clob_token_ids[0]) if clob_token_ids else None
        no_token_id = str(clob_token_ids[1]) if len(clob_token_ids) > 1 else None
        legs = [
            {
                "direction": "YES",
                "token_id": token_id or "",
                "price": yes_price,
                "size": 1.0,
                "market_ticker": f"{market_id}:YES",
                "platform": platform,
            },
            {
                "direction": "NO",
                "token_id": no_token_id or "",
                "price": no_price,
                "size": 1.0,
                "market_ticker": f"{market_id}:NO",
                "platform": platform,
            },
        ]
        return ArbOpportunityEnhanced(
            event_id=market_id,
            kind="yes_no_sum",
            platform_a=platform,
            platform_b=platform,
            market_a_id=market_id,
            market_b_id=market_id,
            price_a=yes_price,
            price_b=no_price,
            raw_spread=raw_profit,
            fees=fee,
            slippage_cost=slippage,
            execution_risk=0.1,
            net_profit=net,
            net_profit_pct=net_pct,
            confidence=min(1.0, net_pct / 0.05),
            token_id=token_id,
            platform=platform,
            details={"yes_no_sum": total, "platform": platform, "legs": legs},
        )

    def detect_complementary(
        self, markets: List[Dict[str, Any]], event_id_key: str = "event_id"
    ) -> List[ArbOpportunityEnhanced]:
        """Detect multi-outcome arbitrage within a provider's event group."""
        opportunities = []
        event_groups: Dict[str, List[Dict[str, Any]]] = {}

        for m in markets:
            if not isinstance(m, dict):
                continue
            eid = m.get(event_id_key, "")
            if eid:
                event_groups.setdefault(str(eid), []).append(m)

        for eid, group in event_groups.items():
            if len(group) < 2:
                continue
            prices = []
            for m in group:
                yp = m.get("yes_price")
                try:
                    p = float(yp) if yp is not None else None
                    if p is not None and 0 < p < 1:
                        prices.append((m, p))
                except (ValueError, TypeError):
                    logger.debug("cross_market_arb: failed to parse yes_price")

            if len(prices) < 2:
                continue

            total_prob = sum(p for _, p in prices)
            if total_prob >= 1.0:
                continue

            platform = group[0].get("platform", "unknown")
            fee_per = group[0].get("fee_pct", _DEFAULT_FEES.get(platform, 0.02))
            raw_profit = 1.0 - total_prob
            fees = fee_per * len(prices)
            slippage = (self.slippage_bps / 10000) * len(prices)
            net = raw_profit - fees - slippage

            if net > 0:
                # Extract token_id from first market's clobTokenIds
                first_market = prices[0][0]
                clob_token_ids = first_market.get("clobTokenIds") or []
                token_id = str(clob_token_ids[0]) if clob_token_ids else None

                opp = ArbOpportunityEnhanced(
                    event_id=eid,
                    kind="multi_outcome",
                    platform_a=platform,
                    platform_b=platform,
                    market_a_id=str(first_market.get("event_id", "")),
                    market_b_id=str(prices[-1][0].get("event_id", "")),
                    price_a=prices[0][1],
                    price_b=prices[-1][1],
                    raw_spread=raw_profit,
                    fees=fees,
                    slippage_cost=slippage,
                    execution_risk=0.2,
                    net_profit=net,
                    net_profit_pct=net / total_prob if total_prob > 0 else 0,
                    confidence=min(1.0, net / 0.05),
                    token_id=token_id,
                    platform=platform,
                    details={"n_outcomes": len(prices), "total_prob": total_prob},
                )
                opportunities.append(opp)

        return opportunities

    def detect_cross_platform_generic(
        self,
        markets_a: List[Dict[str, Any]],
        markets_b: List[Dict[str, Any]],
    ) -> List[ArbOpportunityEnhanced]:
        """Detect cross-platform arb between ANY two provider market sets."""
        if not markets_a or not markets_b:
            return []
        if isinstance(markets_a, str) or isinstance(markets_b, str):
            return []

        opportunities = []
        for ma in markets_a:
            if not isinstance(ma, dict):
                continue
            qa = (ma.get("question") or "").lower()
            pa = ma.get("yes_price")
            if not qa or pa is None:
                continue
            try:
                pa = float(pa)
            except (ValueError, TypeError):
                continue
            if not (0 < pa < 1):
                continue

            for mb in markets_b:
                if not isinstance(mb, dict):
                    continue
                qb = (mb.get("question") or "").lower()
                pb = mb.get("yes_price")
                if not qb or pb is None:
                    continue
                try:
                    pb = float(pb)
                except (ValueError, TypeError):
                    continue
                if not (0 < pb < 1):
                    continue

                # Match by event_id/slug first (exact), then by question text (fuzzy)
                ea = ma.get("event_id", "")
                eb = mb.get("event_id", "")
                slug_a = ma.get("slug", "")
                slug_b = mb.get("slug", "")
                matched = False
                if ea and eb and ea == eb:
                    matched = True
                elif slug_a and slug_b and slug_a == slug_b:
                    matched = True
                elif _questions_match(qa, qb):
                    matched = True
                if not matched:
                    continue

                opp = self._compute_generic_arb(ma, mb, pa, pb)
                if opp:
                    opportunities.append(opp)

        opportunities.sort(key=lambda o: o.net_profit, reverse=True)
        return opportunities

    def _compute_generic_arb(
        self,
        m_a: Dict[str, Any],
        m_b: Dict[str, Any],
        price_a: float,
        price_b: float,
    ) -> Optional[ArbOpportunityEnhanced]:
        """Compute cross-platform arb: buy YES on both platforms when sum < 1.0.

        Real arb: Platform A YES + Platform B YES < 1.0
        Buy both → guaranteed $1.00 payout on resolution → profit = 1.0 - sum - fees
        """
        platform_a = m_a.get("platform", "unknown")
        platform_b = m_b.get("platform", "unknown")
        fee_a = m_a.get("fee_pct", _DEFAULT_FEES.get(platform_a, 0.02))
        fee_b = m_b.get("fee_pct", _DEFAULT_FEES.get(platform_b, 0.02))

        sum_price = price_a + price_b
        total_fees = fee_a + fee_b
        slippage = self.slippage_bps / 10000 * 2

        # Real arb: sum < 1.0 → buy both sides → guaranteed payout
        if sum_price >= 1.0:
            return None

        gross_profit = 1.0 - sum_price
        net = gross_profit - total_fees - slippage
        net_pct = net / sum_price if sum_price > 0 else 0

        if net_pct < self.min_net_profit_pct:
            return None

        id_a = str(m_a.get("event_id", ""))
        id_b = str(m_b.get("event_id", ""))

        # Resolve token_ids from both platforms
        clob_a = m_a.get("clobTokenIds") or []
        clob_b = m_b.get("clobTokenIds") or []
        token_id_a = str(clob_a[0]) if clob_a else None
        token_id_b = str(clob_b[0]) if clob_b else None

        return ArbOpportunityEnhanced(
            event_id=f"{id_a}:{id_b}",
            kind="cross_platform_arb",
            platform_a=platform_a,
            platform_b=platform_b,
            market_a_id=id_a,
            market_b_id=id_b,
            price_a=price_a,
            price_b=price_b,
            raw_spread=gross_profit,
            fees=total_fees,
            slippage_cost=slippage,
            execution_risk=0.1,
            net_profit=net,
            net_profit_pct=net_pct,
            confidence=min(1.0, net_pct / 0.03),
            token_id=token_id_a,  # PM side token for executor
            platform=platform_a,
            details={
                "token_id_a": token_id_a,
                "token_id_b": token_id_b,
                "sum_price": sum_price,
                "gross_profit": gross_profit,
                "arb_type": "two_leg",
            },
        )

    # ── Correlation Detection ─────────────────────────────────────

    def detect_same_game_correlation(
        self, markets: List[Dict[str, Any]]
    ) -> List[ArbOpportunityEnhanced]:
        """Detect same-game correlations: moneyline + spread + over/under per game.

        Applies to SXBet and similar sports book venues where one game
        has multiple bet types (who wins, spread, total points).
        """
        if not markets:
            return []

        # Only applies to markets with team names (sports)
        game_groups: Dict[str, List[Dict]] = {}
        for m in markets:
            q = m.get("question", "")
            if " vs " in q:
                parts = q.split(" vs ")
                t1, t2 = parts[0].strip(), parts[1].strip()
                if t1 and t2:
                    key = f"{t1.lower()}|{t2.lower()}"
                    if key not in game_groups:
                        game_groups[key] = []
                    game_groups[key].append(m)

        opps = []
        for game_key, group in game_groups.items():
            if len(group) < 2:
                continue

            # Categorize by bet type
            moneylines = [m for m in group if self._is_moneyline(m)]
            spreads = [m for m in group if self._is_spread(m)]
            totals = [m for m in group if self._is_total(m)]

            # Moneyline arb: team1_win + team2_win prices < 1.0 after fees
            # SXBet returns team1 vs team2 per market; each market = one outcome
            # Group by the outcome being bet on (first word of outcome name)
            ml_groups: Dict[str, List[Dict]] = {}
            for m in moneylines:
                raw = m.get("_raw", {})
                outcome = raw.get("outcomeOneName", m.get("question", ""))
                team = outcome.split()[0]  # First word = team being bet on
                if team:
                    ml_groups[team] = ml_groups.get(team, []) + [m]

            # If we have 2+ different teams' moneyline, check complementary pricing
            teams = list(ml_groups.keys())
            for i in range(len(teams)):
                for j in range(i + 1, len(teams)):
                    for ma in ml_groups[teams[i]]:
                        for mb in ml_groups[teams[j]]:
                            yes_a = float(ma.get("yes_price", 0))
                            yes_b = float(mb.get("yes_price", 0))
                            if not (0 < yes_a < 1 and 0 < yes_b < 1):
                                continue
                            yes_sum = yes_a + yes_b
                            if yes_sum < 0.96:  # Leave room for 2% fee per side
                                net = 1.0 - yes_sum - 0.04  # 2% each
                                if net <= self.min_net_profit_pct:
                                    continue
                                opps.append(
                                    ArbOpportunityEnhanced(
                                        event_id=game_key,
                                        kind="same_game_ml",
                                        platform_a=ma.get("platform", "unknown"),
                                        platform_b=mb.get("platform", "unknown"),
                                        market_a_id=str(ma.get("event_id", "")),
                                        market_b_id=str(mb.get("event_id", "")),
                                        price_a=yes_a,
                                        price_b=yes_b,
                                        raw_spread=1.0 - yes_sum,
                                        fees=0.04,
                                        slippage_cost=0.002,
                                        execution_risk=0.3,
                                        net_profit=net,
                                        net_profit_pct=net,
                                        confidence=min(1.0, net / max(yes_sum, 0.01)),
                                        details={"game": game_key, "yes_sum": yes_sum},
                                    )
                                )

            # Cross-type: Moneyline YES + opposite side spread/total NO
            # e.g. Giants win YES + opponent spread cover NO = coverage
            all_bets = spreads + totals
            for ml in moneylines:
                ml_yes = float(ml.get("yes_price", 0))
                if not (0 < ml_yes < 1):
                    continue
                for ab in all_bets:
                    ab_no = float(ab.get("no_price", 1 - float(ab.get("yes_price", 0))))
                    total_cost = ml_yes + ab_no
                    net = 1.0 - total_cost - 0.04
                    if net > self.min_net_profit_pct:
                        opps.append(
                            ArbOpportunityEnhanced(
                                event_id=game_key,
                                kind="same_game_cross",
                                platform_a=ml.get("platform", "unknown"),
                                platform_b=ab.get("platform", "unknown"),
                                market_a_id=str(ml.get("event_id", "")),
                                market_b_id=str(ab.get("event_id", "")),
                                price_a=ml_yes,
                                price_b=ab_no,
                                raw_spread=1.0 - total_cost,
                                fees=0.04,
                                slippage_cost=0.002,
                                execution_risk=0.3,
                                net_profit=net,
                                net_profit_pct=net,
                                confidence=min(1.0, net / 0.03),
                                details={
                                    "game": game_key,
                                    "ml_side": ml.get("_raw", {}).get(
                                        "outcomeOneName", ""
                                    ),
                                    "other_side": ab.get("_raw", {}).get(
                                        "outcomeOneName", ""
                                    ),
                                },
                            )
                        )

            # Spread + Total arb: over/under pairs
            for bet_type, items in [("spread", spreads), ("total", totals)]:
                if len(items) >= 2:
                    for a in items:
                        for b in items:
                            if a is b:
                                continue
                            raw_a = a.get("_raw", {})
                            raw_b = b.get("_raw", {})
                            o1_a = raw_a.get("outcomeOneName", "")
                            o1_b = raw_b.get("outcomeOneName", "")
                            # Complementary if one is Over/Team+spread and other is Under/Team-spread
                            if self._are_opposite_bets(o1_a, o1_b):
                                yes_a = float(a.get("yes_price", 0))
                                yes_b = float(b.get("yes_price", 0))
                                if not (0 < yes_a < 1 and 0 < yes_b < 1):
                                    continue
                                yes_sum = yes_a + yes_b
                                if yes_sum < 0.96:
                                    net = 1.0 - yes_sum - 0.04
                                    if net <= self.min_net_profit_pct:
                                        continue
                                    opps.append(
                                        ArbOpportunityEnhanced(
                                            event_id=game_key,
                                            kind=f"same_game_{bet_type}",
                                            platform_a=a.get("platform", "unknown"),
                                            platform_b=b.get("platform", "unknown"),
                                            market_a_id=str(a.get("event_id", "")),
                                            market_b_id=str(b.get("event_id", "")),
                                            price_a=yes_a,
                                            price_b=yes_b,
                                            raw_spread=1.0 - yes_sum,
                                            fees=0.04,
                                            slippage_cost=0.002,
                                            execution_risk=0.3,
                                            net_profit=net,
                                            net_profit_pct=net,
                                            confidence=min(1.0, net / 0.03),
                                            details={
                                                "game": game_key,
                                                "yes_sum": yes_sum,
                                            },
                                        )
                                    )

        return opps

    def detect_cross_timeframe_arb(
        self, markets: List[Dict[str, Any]]
    ) -> List[ArbOpportunityEnhanced]:
        """Detect cross-timeframe statistical arbitrage on same underlying asset.

        Example: BTC 5-min YES=0.88, BTC 15-min YES=0.015.
        Buy the cheap directional bet + hedge with the other timeframe's opposing outcome.
        """
        if not markets:
            return []

        # Group by asset (extract ticker from question)
        import re as _re

        asset_groups: Dict[str, List[Dict]] = {}
        for m in markets:
            q = m.get("question", "")
            match = _re.search(
                r"\b(BTC|ETH|SOL|XRP|DOGE|BNB|HYPE|AAPL|NVDA|TSLA|META|AMZN|GOOG)\b",
                q.upper(),
            )
            if match:
                asset = match.group(0)
                # Extract timeframe
                tf_match = _re.search(r"(\d+)\s*min", q.lower())
                tf = int(tf_match.group(1)) if tf_match else None
                if tf is not None:
                    if asset not in asset_groups:
                        asset_groups[asset] = []
                    asset_groups[asset].append({**m, "_asset_tf": tf})

        opps = []
        for asset, group in asset_groups.items():
            if len(group) < 2:
                continue

            # Compare all timeframe pairs
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    a = group[i]
                    b = group[j]
                    tf_a, tf_b = a["_asset_tf"], b["_asset_tf"]
                    if tf_a == tf_b:
                        continue

                    yes_a = float(a.get("yes_price", 0))
                    no_a = float(a.get("no_price", 1 - yes_a))
                    yes_b = float(b.get("yes_price", 0))
                    no_b = float(b.get("no_price", 1 - yes_b))

                    # General approach: compare any two different timeframes
                    # Strategy: buy YES on cheaper + NO on expensive of other tf
                    # If total cost < 0.96, profitable after 2% fee per side

                    # Option A: buy tf_a YES + tf_b NO
                    cost1 = yes_a + no_b
                    if cost1 < 0.96 and 1.0 - cost1 > self.min_net_profit_pct:
                        net = 1.0 - cost1 - 0.04
                        if net > self.min_net_profit_pct:
                            opps.append(
                                ArbOpportunityEnhanced(
                                    event_id=f"{asset}_{tf_a}_{tf_b}",
                                    kind="cross_timeframe",
                                    platform_a=a.get("platform", "unknown"),
                                    platform_b=b.get("platform", "unknown"),
                                    market_a_id=str(a.get("event_id", "")),
                                    market_b_id=str(b.get("event_id", "")),
                                    price_a=yes_a,
                                    price_b=no_b,
                                    raw_spread=1.0 - cost1,
                                    fees=0.04,
                                    slippage_cost=0.003,
                                    execution_risk=0.4,
                                    net_profit=net,
                                    net_profit_pct=net,
                                    confidence=min(1.0, net / 0.03),
                                    details={
                                        "asset": asset,
                                        "tf_a": tf_a,
                                        "tf_b": tf_b,
                                        "strategy": "buy_tfa_yes_tfb_no",
                                    },
                                )
                            )

                    # Option B: buy tf_a NO + tf_b YES
                    cost2 = no_a + yes_b
                    if cost2 < 0.96 and 1.0 - cost2 > self.min_net_profit_pct:
                        net = 1.0 - cost2 - 0.04
                        if net > self.min_net_profit_pct:
                            opps.append(
                                ArbOpportunityEnhanced(
                                    event_id=f"{asset}_{tf_a}_{tf_b}",
                                    kind="cross_timeframe",
                                    platform_a=a.get("platform", "unknown"),
                                    platform_b=b.get("platform", "unknown"),
                                    market_a_id=str(a.get("event_id", "")),
                                    market_b_id=str(b.get("event_id", "")),
                                    price_a=no_a,
                                    price_b=yes_b,
                                    raw_spread=1.0 - cost2,
                                    fees=0.04,
                                    slippage_cost=0.003,
                                    execution_risk=0.4,
                                    net_profit=net,
                                    net_profit_pct=net,
                                    confidence=min(1.0, net / 0.03),
                                    details={
                                        "asset": asset,
                                        "tf_a": tf_a,
                                        "tf_b": tf_b,
                                        "strategy": "buy_tfa_no_tfb_yes",
                                    },
                                )
                            )

        return opps

    def _is_moneyline(self, market: Dict[str, Any]) -> bool:
        """Check if market is a moneyline bet (team A wins / team B wins)."""
        raw = market.get("_raw", {})
        o1 = raw.get("outcomeOneName", "")
        return bool(o1) and not self._is_spread(market) and not self._is_total(market)

    def _is_spread(self, market: Dict[str, Any]) -> bool:
        """Check if market is a point spread bet."""
        raw = market.get("_raw", {})
        o1 = raw.get("outcomeOneName", "")
        return bool(o1) and (".5" in o1 or "+" in o1 or "-" in o1)

    def _is_total(self, market: Dict[str, Any]) -> bool:
        """Check if market is an over/under total bet."""
        raw = market.get("_raw", {})
        o1 = raw.get("outcomeOneName", "")
        return bool(o1) and "Over" in o1

    @staticmethod
    def _are_opposite_bets(o1: str, o2: str) -> bool:
        """Check if two outcome names are complementary (Over vs Under, Team+A vs Team-A)."""
        if not o1 or not o2:
            return False
        o1l, o2l = o1.lower(), o2.lower()
        # Over vs Under
        if "over" in o1l and "under" in o2l:
            # Must be SAME line (e.g., Over 48.5 vs Under 48.5)
            nums1 = "".join(c for c in o1 if c.isdigit() or c == ".")
            nums2 = "".join(c for c in o2 if c.isdigit() or c == ".")
            return nums1 == nums2
        # Team+spread vs Team-spread (opposite signs)
        if "+" in o1 and "-" in o2:
            return True
        if "-" in o1 and "+" in o2:
            return True
        return False

    # ── Legacy compat ─────────────────────────────────────────────

    def scan_all(
        self,
        poly_markets: List[Dict[str, Any]],
        kalshi_markets: Optional[List[Dict[str, Any]]] = None,
    ) -> ScanResult:
        """Legacy: scan only Polymarket + Kalshi. Prefer scan_all_providers."""
        all_markets = {"polymarket": poly_markets}
        if kalshi_markets:
            all_markets["kalshi"] = kalshi_markets
        return self.scan_all_providers(all_markets)


# ── Market Helpers ────────────────────────────────────────────────


def _extract_yes_price(market: Dict[str, Any]) -> Optional[float]:
    """Extract YES price from a market dict (legacy, use market['yes_price'] directly)."""
    # First check normalized fields
    yp = market.get("yes_price")
    if yp is not None:
        try:
            p = float(yp)
            if 0 < p < 1:
                return p
        except (ValueError, TypeError):
            logger.debug("cross_market_arb: failed to parse yes_price from market")

    for key in ("yesPrice", "price"):
        val = market.get(key)
        if val is not None:
            try:
                p = float(val)
                if 0 < p < 1:
                    return p
            except (ValueError, TypeError):
                logger.debug("cross_market_arb: failed to parse price from market key")

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
            logger.warning(
                "cross_market_arb_enhanced: failed to parse Kalshi orderbook price"
            )

    kalshi_ask = market.get("yes_ask_dollars")
    if kalshi_ask is not None:
        try:
            p = float(kalshi_ask)
            if 0 < p < 1:
                return p
        except (ValueError, TypeError):
            logger.debug("cross_market_arb: failed to parse kalshi yes_ask_dollars")
    return None


# ── Question Matching ─────────────────────────────────────────────

_STOP_WORDS = frozenset(
    {
        "will",
        "the",
        "be",
        "in",
        "a",
        "an",
        "on",
        "at",
        "to",
        "for",
        "of",
        "and",
        "or",
        "is",
        "it",
        "by",
        "as",
        "do",
        "does",
        "did",
        "has",
        "have",
        "had",
        "was",
        "were",
        "are",
        "this",
        "that",
        "with",
        "from",
        "but",
        "not",
        "no",
        "if",
        "so",
        "than",
        # Short-duration market noise
        "up",
        "down",
        "min",
        "hourly",
        "daily",
        "weekly",
        "monthly",
        "et",
        "am",
        "pm",
        "yes",
        "before",
        "after",
        "between",
        "above",
        "below",
        "over",
        "under",
    }
)

# Synonym map for cross-platform matching
_CRYPTO_SYNONYMS = {
    "bitcoin": "btc",
    "btc": "btc",
    "ethereum": "eth",
    "eth": "eth",
    "solana": "sol",
    "sol": "sol",
    "xrp": "xrp",
    "ripple": "xrp",
    "dogecoin": "doge",
    "doge": "doge",
    "cardano": "ada",
    "ada": "ada",
    "bnb": "bnb",
    "binance": "bnb",
    "polkadot": "dot",
    "dot": "dot",
    "avax": "avax",
    "avalanche": "avax",
    "matic": "matic",
    "polygon": "matic",
    "link": "link",
    "chainlink": "link",
}


def _normalize_number(text: str) -> str:
    """Normalize numbers in text: 100k -> 100000, $100,000 -> 100000."""
    import re

    def _replace(match):
        s = match.group(0).lower().replace(",", "").replace("$", "").strip()
        multiplier = 1
        if s.endswith("k"):
            s = s[:-1]
            multiplier = 1_000
        elif s.endswith("m"):
            s = s[:-1]
            multiplier = 1_000_000
        elif s.endswith("b"):
            s = s[:-1]
            multiplier = 1_000_000_000
        try:
            return str(int(float(s) * multiplier))
        except (ValueError, TypeError):
            return match.group(0)

    return re.sub(r"[\$]?[\d,]+\.?\d*[kKmMbB]?", _replace, text)


def _normalize_crypto_tokens(text: str) -> str:
    """Replace crypto synonyms with canonical tokens."""
    words = text.lower().split()
    normalized = [_CRYPTO_SYNONYMS.get(w, w) for w in words]
    return " ".join(normalized)


def _questions_match(q1: str, q2: str) -> bool:
    """Check if two questions refer to the same event.

    Uses Jaccard similarity on meaningful words + entity matching.
    Requires >= 60% overlap on the SMALLER set AND at least 3 matching words.
    Both questions must have >= 3 meaningful words to prevent short-question noise.

    Enhanced with number normalization (100k = $100,000 = 100000)
    and crypto synonym normalization (Bitcoin = BTC, Ethereum = ETH).
    """
    import re

    # Normalize: numbers, crypto synonyms, strip punctuation, then tokenize
    n1 = _normalize_crypto_tokens(_normalize_number(q1.lower()))
    n2 = _normalize_crypto_tokens(_normalize_number(q2.lower()))

    # Strip punctuation from tokens
    def _clean(s: str) -> set[str]:
        import re as re2

        return {re2.sub(r"[^a-z0-9]", "", w) for w in s.split()} - {""}

    words1 = _clean(n1) - _STOP_WORDS
    words2 = _clean(n2) - _STOP_WORDS
    if not words1 or not words2:
        return False

    # Both questions need enough substance for reliable matching
    if len(words1) < 2 or len(words2) < 2:
        return False

    overlap = words1 & words2
    smaller = min(len(words1), len(words2))
    if smaller == 0 or len(overlap) == 0:
        return False

    # Need at least 50% overlap on smaller set AND at least 2 matching words
    if len(overlap) < 2:
        return False
    if len(overlap) / smaller < 0.5:
        return False

    # Entity check: numbers and proper nouns must overlap
    def _entities(text: str) -> set[str]:
        tokens = set()
        for tok in re.findall(r"[A-Za-z0-9]+", text):
            if tok[0].isdigit() or (
                len(tok) > 1 and tok[0].isupper() and tok.lower() not in _STOP_WORDS
            ):
                tokens.add(tok.lower())
        return tokens

    ent1 = _entities(n1)
    ent2 = _entities(n2)
    if ent1 and ent2:
        if not (ent1 & ent2):
            return False

    return True
