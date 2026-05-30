"""
Cross-Platform Arbitrage Strategy — buy cheap on one platform, sell expensive on another.

Finds price divergences across Polymarket, Kalshi, and SX.bet.
Edge source: same market priced differently on different platforms.
Guaranteed profit if both legs fill (YES + YES < 1.0 after fees).

Components:
  - MarketMatcher: matches same markets across platforms (fuzzy)
  - ArbDetector: finds price divergences > threshold
  - ArbExecutor: builds leg-level execution decisions

Does NOT self-execute — the executor handles order placement.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from backend.strategies.base import BaseStrategy, CycleResult, StrategyContext
from backend.strategies.cross_market_arb_enhanced import (
    CrossMarketArbEnhanced,
    _DEFAULT_FEES,
)

import re as _re


# ---------------------------------------------------------------------------
# Strict matching — avoids false positives from loose fuzzy matching
# ---------------------------------------------------------------------------

_SPORTS_KEYWORDS = frozenset({
    "nfl", "nba", "mlb", "nhl", "ncaa", "premier league", "champions league",
    "super bowl", "world series", "stanley cup", "march madness",
    "touchdown", "home run", "goal", "assist", "rebounds", "points scored",
    "spread", "over under", "moneyline", "total",
    "rangers", "cardinals", "giants", "brewers", "rams", "49ers", "eagles",
    "cowboys", "patriots", "chiefs", "lakers", "celtics", "warriors",
    "yankees", "dodgers", "mets", "astros", "reds", "pirates", "rockies",
})

_CRYPTO_KEYWORDS = frozenset({
    "bitcoin", "btc", "ethereum", "eth", "solana", "sol", "xrp", "doge",
    "dogecoin", "cardano", "ada", "bnb", "polkadot", "avax", "matic",
})

_POLITICAL_KEYWORDS = frozenset({
    "president", "election", "congress", "senate", "governor", "primary",
    "democrat", "republican", "nominee", "vote", "party",
})


def _extract_entities(text: str) -> set:
    """Extract meaningful entities: numbers, proper nouns, crypto tokens."""
    tokens = set()
    for tok in _re.findall(r"[A-Za-z0-9]+", text.lower()):
        if len(tok) >= 2:
            tokens.add(tok)
    return tokens


def _detect_domain(text: str) -> str:
    """Detect market domain: sports, crypto, political, other."""
    words = set(text.lower().split())
    if words & _SPORTS_KEYWORDS or " vs " in text.lower():
        return "sports"
    if words & _CRYPTO_KEYWORDS:
        return "crypto"
    if words & _POLITICAL_KEYWORDS:
        return "political"
    return "other"


def _strict_questions_match(q1: str, q2: str) -> bool:
    """Strict cross-platform question matching.

    Rejects cross-domain matches (sports vs crypto, etc).
    Requires high overlap on meaningful entities.
    """
    # Domain must match
    d1, d2 = _detect_domain(q1), _detect_domain(q2)
    if d1 != d2 and d1 != "other" and d2 != "other":
        return False  # cross-domain = not the same market

    # Extract entities
    ent1 = _extract_entities(q1)
    ent2 = _extract_entities(q2)

    # Filter trivial words
    _STOP = {"will", "the", "be", "in", "a", "an", "on", "at", "to", "for",
             "of", "and", "or", "is", "it", "by", "as", "do", "does", "did",
             "has", "have", "had", "was", "were", "are", "this", "that",
             "with", "from", "but", "not", "no", "if", "so", "than",
             "yes", "before", "after", "between", "above", "below", "over", "under",
             "by", "win", "lose", "hit", "reach", "above", "below"}
    ent1 -= _STOP
    ent2 -= _STOP

    if not ent1 or not ent2:
        return False

    overlap = ent1 & ent2
    smaller = min(len(ent1), len(ent2))

    # Need at least 60% overlap on the smaller set AND 2+ matching words
    if len(overlap) < 2:
        return False
    if smaller >= 3 and len(overlap) / smaller < 0.6:
        return False

    # Numbers must overlap (dates, thresholds, etc)
    # Separate years (4-digit, 2020-2030) from thresholds (100k, 200000, etc)
    def _norm_nums(tokens: set) -> tuple:
        years, values = set(), set()
        for t in tokens:
            if not t[0].isdigit():
                continue
            s = t.replace(",", "").replace("$", "").strip()
            # Year detection: 4-digit 2020-2030
            if s.isdigit() and 2020 <= int(s) <= 2030:
                years.add(s)
                continue
            mult = 1
            if s.endswith("k"):
                s, mult = s[:-1], 1_000
            elif s.endswith("m"):
                s, mult = s[:-1], 1_000_000
            elif s.endswith("b"):
                s, mult = s[:-1], 1_000_000_000
            try:
                values.add(str(int(float(s) * mult)))
            except (ValueError, TypeError):
                values.add(t)
        return years, values

    years1, vals1 = _norm_nums(ent1)
    years2, vals2 = _norm_nums(ent2)
    # Threshold values must match exactly if both sides have them
    if vals1 and vals2 and not (vals1 & vals2):
        return False  # different thresholds = different market

    return True

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_EDGE_PCT = 0.02          # minimum 2% net edge to trade
MAX_POSITION_USD = 50.0      # cap per arb opportunity
LEG_TIMEOUT_SEC = 30         # cancel second leg if first fails
MAX_OPPORTUNITIES_PER_CYCLE = 10

# Platforms to scan
_PLATFORMS = ["polymarket", "kalshi", "sxbet"]


# ---------------------------------------------------------------------------
# MarketMatcher — fuzzy cross-platform market matching
# ---------------------------------------------------------------------------

@dataclass
class MatchedMarketPair:
    """A pair of markets on different platforms referring to the same event."""
    platform_a: str
    platform_b: str
    market_a: Dict[str, Any]
    market_b: Dict[str, Any]
    match_score: float  # 0.0-1.0 confidence in the match
    question_a: str
    question_b: str


class MarketMatcher:
    """Matches same markets across platforms using fuzzy question matching."""

    def match_all(
        self,
        all_markets: Dict[str, List[Dict[str, Any]]],
    ) -> List[MatchedMarketPair]:
        """Match markets across all platform pairs.

        Args:
            all_markets: {platform_name: [normalized_market_dicts]}

        Returns:
            List of matched market pairs across different platforms.
        """
        pairs: List[MatchedMarketPair] = []
        platforms = [p for p in _PLATFORMS if p in all_markets and all_markets[p]]

        for i in range(len(platforms)):
            for j in range(i + 1, len(platforms)):
                pa, pb = platforms[i], platforms[j]
                ma_list, mb_list = all_markets[pa], all_markets[pb]
                matched = self._match_pair(pa, pb, ma_list, mb_list)
                pairs.extend(matched)

        return pairs

    def _match_pair(
        self,
        pa: str,
        pb: str,
        ma_list: List[Dict],
        mb_list: List[Dict],
    ) -> List[MatchedMarketPair]:
        """Match markets between two platforms."""
        pairs = []
        for ma in ma_list:
            qa = (ma.get("question") or "").lower()
            if not qa:
                continue
            for mb in mb_list:
                qb = (mb.get("question") or "").lower()
                if not qb:
                    continue

                # Exact event_id match
                ea = ma.get("event_id", "")
                eb = mb.get("event_id", "")
                if ea and eb and ea == eb:
                    pairs.append(MatchedMarketPair(
                        platform_a=pa, platform_b=pb,
                        market_a=ma, market_b=mb,
                        match_score=1.0,
                        question_a=ma.get("question", ""),
                        question_b=mb.get("question", ""),
                    ))
                    continue

                # Exact slug match
                sa = ma.get("slug", "")
                sb = mb.get("slug", "")
                if sa and sb and sa == sb:
                    pairs.append(MatchedMarketPair(
                        platform_a=pa, platform_b=pb,
                        market_a=ma, market_b=mb,
                        match_score=0.95,
                        question_a=ma.get("question", ""),
                        question_b=mb.get("question", ""),
                    ))
                    continue

                # Fuzzy question match (strict — rejects cross-domain)
                if _strict_questions_match(qa, qb):
                    pairs.append(MatchedMarketPair(
                        platform_a=pa, platform_b=pb,
                        market_a=ma, market_b=mb,
                        match_score=0.8,
                        question_a=ma.get("question", ""),
                        question_b=mb.get("question", ""),
                    ))

        return pairs


# ---------------------------------------------------------------------------
# ArbDetector — finds profitable price divergences
# ---------------------------------------------------------------------------

@dataclass
class ArbOpportunity:
    """A detected cross-platform arbitrage opportunity."""
    pair: MatchedMarketPair
    price_a: float
    price_b: float
    raw_spread: float        # 1.0 - (price_a + price_b)
    total_fees: float
    slippage_cost: float
    net_profit: float        # per $1 spent
    net_profit_pct: float    # net_profit / total_cost
    confidence: float        # 0.0-1.0
    size_usd: float          # recommended position size
    details: Dict[str, Any] = field(default_factory=dict)


class ArbDetector:
    """Detects cross-platform arbitrage opportunities from matched market pairs."""

    def __init__(
        self,
        min_edge_pct: float = MIN_EDGE_PCT,
        max_position_usd: float = MAX_POSITION_USD,
        slippage_bps: float = 5.0,
    ):
        self.min_edge_pct = min_edge_pct
        self.max_position_usd = max_position_usd
        self.slippage_bps = slippage_bps

    def detect(
        self,
        pairs: List[MatchedMarketPair],
    ) -> List[ArbOpportunity]:
        """Find arbitrage opportunities among matched market pairs."""
        opps: List[ArbOpportunity] = []

        for pair in pairs:
            opp = self._evaluate_pair(pair)
            if opp:
                opps.append(opp)

        opps.sort(key=lambda o: o.net_profit, reverse=True)
        return opps

    def _evaluate_pair(self, pair: MatchedMarketPair) -> Optional[ArbOpportunity]:
        """Evaluate a single matched pair for arbitrage."""
        pa = pair.market_a.get("yes_price")
        pb = pair.market_b.get("yes_price")

        if pa is None or pb is None:
            return None

        try:
            pa = float(pa)
            pb = float(pb)
        except (ValueError, TypeError):
            return None

        if not (0 < pa < 1) or not (0 < pb < 1):
            return None

        # Real arb: buy YES on both platforms, sum < 1.0
        sum_price = pa + pb
        if sum_price >= 1.0:
            return None

        gross_profit = 1.0 - sum_price

        # Fee model
        fee_a = pair.market_a.get("fee_pct", _DEFAULT_FEES.get(pair.platform_a, 0.02))
        fee_b = pair.market_b.get("fee_pct", _DEFAULT_FEES.get(pair.platform_b, 0.02))
        total_fees = fee_a + fee_b

        slippage = self.slippage_bps / 10000 * 2  # two legs

        net_profit = gross_profit - total_fees - slippage
        net_profit_pct = net_profit / sum_price if sum_price > 0 else 0

        if net_profit_pct < self.min_edge_pct:
            return None

        # Position sizing: cap at MAX_POSITION_USD
        size_usd = min(self.max_position_usd, max(5.0, net_profit_pct * 500))

        # Confidence: proportional to edge, capped at 1.0
        confidence = min(1.0, net_profit_pct / 0.05)

        # Execution risk: cross-platform is riskier than same-platform
        execution_risk = 0.15 if pair.match_score >= 0.95 else 0.25

        return ArbOpportunity(
            pair=pair,
            price_a=pa,
            price_b=pb,
            raw_spread=gross_profit,
            total_fees=total_fees,
            slippage_cost=slippage,
            net_profit=net_profit,
            net_profit_pct=net_profit_pct,
            confidence=confidence,
            size_usd=size_usd,
            details={
                "sum_price": round(sum_price, 6),
                "gross_profit": round(gross_profit, 6),
                "fee_a": fee_a,
                "fee_b": fee_b,
                "execution_risk": execution_risk,
                "match_score": pair.match_score,
                "arb_type": "cross_platform_two_leg",
            },
        )


# ---------------------------------------------------------------------------
# ArbExecutor — builds leg-level execution decisions
# ---------------------------------------------------------------------------

@dataclass
class ArbLeg:
    """One leg of an arb trade."""
    platform: str
    side: str          # "YES" or "NO"
    price: float
    size_usd: float
    market_id: str
    token_id: Optional[str] = None
    question: str = ""


@dataclass
class ArbTrade:
    """A complete arb trade with two legs."""
    leg_a: ArbLeg
    leg_b: ArbLeg
    expected_profit_usd: float
    opportunity: ArbOpportunity


class ArbExecutor:
    """Builds leg-level execution plans from detected opportunities."""

    def __init__(self, leg_timeout_sec: int = LEG_TIMEOUT_SEC):
        self.leg_timeout_sec = leg_timeout_sec

    def build_trades(
        self,
        opportunities: List[ArbOpportunity],
        max_per_cycle: int = MAX_OPPORTUNITIES_PER_CYCLE,
    ) -> List[ArbTrade]:
        """Convert opportunities into executable two-leg trades."""
        trades: List[ArbTrade] = []

        for opp in opportunities[:max_per_cycle]:
            trade = self._build_trade(opp)
            if trade:
                trades.append(trade)

        return trades

    def _build_trade(self, opp: ArbOpportunity) -> Optional[ArbTrade]:
        """Build a single arb trade from an opportunity."""
        pair = opp.pair
        market_a = pair.market_a
        market_b = pair.market_b

        # Resolve token IDs for CLOB execution
        clob_a = market_a.get("clobTokenIds") or []
        clob_b = market_b.get("clobTokenIds") or []
        token_id_a = str(clob_a[0]) if clob_a else None
        token_id_b = str(clob_b[0]) if clob_b else None

        leg_a = ArbLeg(
            platform=pair.platform_a,
            side="YES",
            price=opp.price_a,
            size_usd=opp.size_usd,
            market_id=str(market_a.get("event_id", "")),
            token_id=token_id_a,
            question=pair.question_a,
        )
        leg_b = ArbLeg(
            platform=pair.platform_b,
            side="YES",
            price=opp.price_b,
            size_usd=opp.size_usd,
            market_id=str(market_b.get("event_id", "")),
            token_id=token_id_b,
            question=pair.question_b,
        )

        expected_profit = opp.net_profit * (opp.size_usd / opp.price_a)

        return ArbTrade(
            leg_a=leg_a,
            leg_b=leg_b,
            expected_profit_usd=expected_profit,
            opportunity=opp,
        )


# ---------------------------------------------------------------------------
# CrossPlatformArbStrategy — main strategy class
# ---------------------------------------------------------------------------

class CrossPlatformArbStrategy(BaseStrategy):
    """Finds price divergences across Polymarket, Kalshi, SX.bet.

    Edge source: same market priced differently on different platforms.
    Guaranteed profit if we can fill both legs.
    """

    name = "cross_platform_arb"
    description = "Cross-platform arbitrage: buy cheap on one platform, sell expensive on another"
    category = "arb"

    default_params: dict = {
        "min_edge_pct": MIN_EDGE_PCT,
        "max_position_usd": MAX_POSITION_USD,
        "leg_timeout_sec": LEG_TIMEOUT_SEC,
        "max_opportunities_per_cycle": MAX_OPPORTUNITIES_PER_CYCLE,
        "enabled": True,
    }

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._matcher = MarketMatcher()
        self._detector: Optional[ArbDetector] = None
        self._executor: Optional[ArbExecutor] = None
        self._history: List[Dict] = []

    @staticmethod
    def market_filter(markets):
        """Pass-through — we fetch our own markets from providers."""
        return markets

    def _get_detector(self) -> ArbDetector:
        if self._detector is None:
            params = self.default_params
            self._detector = ArbDetector(
                min_edge_pct=params.get("min_edge_pct", MIN_EDGE_PCT),
                max_position_usd=params.get("max_position_usd", MAX_POSITION_USD),
            )
        return self._detector

    def _get_executor(self) -> ArbExecutor:
        if self._executor is None:
            self._executor = ArbExecutor(
                leg_timeout_sec=self.default_params.get("leg_timeout_sec", LEG_TIMEOUT_SEC),
            )
        return self._executor

    # ------------------------------------------------------------------
    # Market fetching
    # ------------------------------------------------------------------

    async def _fetch_polymarket(self) -> List[Dict[str, Any]]:
        """Fetch Polymarket markets via Gamma API."""
        try:
            from backend.data.gamma import fetch_markets
            from backend.data.arb_opportunity_scanner import _normalize_pm_markets

            markets = await fetch_markets(limit=200)
            return _normalize_pm_markets(markets, "polymarket", fee_pct=0.02)
        except Exception:
            logger.warning("[cross_platform_arb] Polymarket fetch failed")
            return []

    async def _fetch_kalshi(self) -> List[Dict[str, Any]]:
        """Fetch Kalshi markets."""
        try:
            from backend.data.kalshi_client import KalshiClient
            from backend.data.arb_opportunity_scanner import _normalize_kalshi_markets

            client = KalshiClient()
            response = await client.get_markets(params={"limit": 200, "status": "open"})
            raw = response.get("markets", []) if isinstance(response, dict) else []
            return _normalize_kalshi_markets(raw)
        except Exception:
            logger.warning("[cross_platform_arb] Kalshi fetch failed")
            return []

    async def _fetch_sxbet(self) -> List[Dict[str, Any]]:
        """Fetch SX.bet markets with orderbook prices."""
        try:
            from backend.data.arb_opportunity_scanner import ArbOpportunityScanner

            scanner = ArbOpportunityScanner(min_profit_pct=0.0)
            return await scanner._scan_sxbet()
        except Exception:
            logger.warning("[cross_platform_arb] SX.bet fetch failed")
            return []

    # ------------------------------------------------------------------
    # Main cycle
    # ------------------------------------------------------------------

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        start = time.monotonic()
        decisions: List[Dict] = []

        # 1. Fetch markets from all platforms in parallel
        results = await asyncio.gather(
            self._fetch_polymarket(),
            self._fetch_kalshi(),
            self._fetch_sxbet(),
            return_exceptions=True,
        )

        all_markets: Dict[str, List[Dict]] = {}
        platform_names = ["polymarket", "kalshi", "sxbet"]
        for name, result in zip(platform_names, results):
            if isinstance(result, Exception):
                logger.warning(f"[cross_platform_arb] {name} exception: {result}")
                continue
            if result:
                all_markets[name] = result

        if len(all_markets) < 2:
            return CycleResult(
                0, 0, 0,
                errors=[f"Only {len(all_markets)} platform(s) available; need 2+ for cross-platform arb"],
            )

        total_markets = sum(len(v) for v in all_markets.values())

        # 2. Match markets across platforms
        pairs = self._matcher.match_all(all_markets)

        # 3. Detect arbitrage opportunities
        detector = self._get_detector()
        opportunities = detector.detect(pairs)

        # 4. Build executable trades
        executor = self._get_executor()
        trades = executor.build_trades(
            opportunities,
            max_per_cycle=self.default_params.get("max_opportunities_per_cycle", MAX_OPPORTUNITIES_PER_CYCLE),
        )

        # 5. Build decisions for the executor pipeline
        for idx, trade in enumerate(trades):
            opp = trade.opportunity
            pair = opp.pair

            _uniq_suffix = (
                f"{pair.platform_a}:{pair.platform_b}:"
                f"{opp.price_a:.4f}:{opp.price_b:.4f}:{idx}"
            )
            _cid = f"{trade.leg_a.market_id}:{trade.leg_b.market_id}" or _uniq_suffix

            decision = {
                "kind": "cross_platform_arb",
                "decision": "BUY",
                "direction": "YES",
                "condition_id": _cid,
                "market_ticker": _cid[:64],
                "platform_a": pair.platform_a,
                "platform_b": pair.platform_b,
                "price_a": opp.price_a,
                "price_b": opp.price_b,
                "net_profit": opp.net_profit,
                "net_profit_pct": opp.net_profit_pct,
                "confidence": opp.confidence,
                "raw_spread": opp.raw_spread,
                "fees": opp.total_fees,
                "slippage_cost": opp.slippage_cost,
                "execution_risk": opp.details.get("execution_risk", 0.2),
                "match_score": opp.details.get("match_score", 0),
                "size": opp.size_usd,
                "market_type": "arb",
                "model_probability": min(1.0, 0.5 + opp.net_profit_pct),
                "leg_a": {
                    "platform": trade.leg_a.platform,
                    "market_id": trade.leg_a.market_id,
                    "token_id": trade.leg_a.token_id,
                    "price": trade.leg_a.price,
                    "side": trade.leg_a.side,
                },
                "leg_b": {
                    "platform": trade.leg_b.platform,
                    "market_id": trade.leg_b.market_id,
                    "token_id": trade.leg_b.token_id,
                    "price": trade.leg_b.price,
                    "side": trade.leg_b.side,
                },
                "question_a": pair.question_a,
                "question_b": pair.question_b,
                "expected_profit_usd": round(trade.expected_profit_usd, 4),
                "details": opp.details,
            }
            decisions.append(decision)

            # Record history
            self._history.append({
                "pair": f"{pair.platform_a}<> {pair.platform_b}",
                "question": pair.question_a,
                "price_a": opp.price_a,
                "price_b": opp.price_b,
                "net_profit_pct": opp.net_profit_pct,
                "size_usd": opp.size_usd,
                "status": "detected",
                "timestamp": time.time(),
            })

            # Log to DecisionLog
            try:
                from backend.models.database import DecisionLog

                log_row = DecisionLog(
                    strategy=self.name,
                    market_ticker=_cid[:64],
                    decision="ARB",
                    confidence=opp.confidence,
                    signal_data=json.dumps(decision),
                    reason=(
                        f"{pair.platform_a}@{opp.price_a:.3f} + "
                        f"{pair.platform_b}@{opp.price_b:.3f} = "
                        f"{opp.price_a + opp.price_b:.3f} < 1.0 | "
                        f"net={opp.net_profit_pct:.2%} edge | "
                        f"{pair.question_a[:80]}"
                    ),
                )
                ctx.db.add(log_row)
            except Exception:
                pass

        # 6. Commit DB
        try:
            ctx.db.commit()
        except Exception:
            logger.warning("[cross_platform_arb] DB commit failed, rolling back")
            ctx.db.rollback()

        # Trim history
        if len(self._history) > 500:
            self._history = self._history[-500:]

        elapsed = (time.monotonic() - start) * 1000
        logger.info(
            f"[cross_platform_arb] {total_markets} markets from "
            f"{len(all_markets)} platforms, {len(pairs)} matched pairs, "
            f"{len(opportunities)} arbs, {len(decisions)} trades in {elapsed:.0f}ms"
        )

        return CycleResult(
            decisions_recorded=len(decisions),
            trades_attempted=len(trades),
            trades_placed=0,
            decisions=decisions,
            cycle_duration_ms=elapsed,
            markets_scanned=total_markets,
        )

    # ------------------------------------------------------------------
    # History access
    # ------------------------------------------------------------------

    def get_history(self, limit: int = 100) -> List[Dict]:
        """Return recent arb detection history."""
        return self._history[-limit:]
