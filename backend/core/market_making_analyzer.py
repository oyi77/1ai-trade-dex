"""Market Making Analyzer — order book depth, spread analysis, and liquidity metrics.

Provides tools for analyzing order book structure to identify market-making
opportunities, detect liquidity gaps, and measure market microstructure.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from typing import Optional



@dataclass
class DepthLevel:
    """Single level in the order book depth analysis."""
    price: float
    size: float
    cumulative_size: float
    distance_from_mid_pct: float


@dataclass
class SpreadAnalysis:
    """Bid-ask spread analysis results."""
    best_bid: float
    best_ask: float
    spread: float
    spread_pct: float
    mid_price: float
    micro_price: float  # size-weighted mid
    time_since_last_trade_s: float


@dataclass
class DepthAnalysis:
    """Order book depth analysis results."""
    bid_depth: list[DepthLevel]
    ask_depth: list[DepthLevel]
    total_bid_size: float
    total_ask_size: float
    depth_imbalance: float  # (bid - ask) / (bid + ask), range [-1, 1]
    depth_ratio: float  # bid_size / ask_size
    wall_bid_price: Optional[float] = None  # largest bid level
    wall_ask_price: Optional[float] = None  # largest ask level


@dataclass
class LiquidityMetrics:
    """Comprehensive liquidity metrics for a market."""
    market_id: str
    spread: SpreadAnalysis
    depth: DepthAnalysis
    resilience_score: float  # 0-1, how quickly book refills
    toxicity_score: float  # 0-1, adverse selection risk
    maker_opportunity_score: float  # 0-1, profitability of market making
    timestamp: float = field(default_factory=time.time)


@dataclass
class MarketMakingOpportunity:
    """A detected market-making opportunity."""
    market_id: str
    bid_price: float
    ask_price: float
    expected_spread_capture: float
    estimated_fill_prob: float
    risk_score: float  # 0-1
    recommended_size: float
    confidence: float


class MarketMakingAnalyzer:
    """Analyze order book structure for market-making opportunities.

    Computes spread, depth, imbalance, resilience, and toxicity metrics
    to identify profitable market-making setups.
    """

    def __init__(
        self,
        min_spread_pct: float = 0.005,
        max_toxicity: float = 0.7,
        depth_levels: int = 10,
    ):
        self.min_spread_pct = min_spread_pct
        self.max_toxicity = max_toxicity
        self.depth_levels = depth_levels
        self._history: dict[str, list[LiquidityMetrics]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        market_id: str,
        bids: list[dict],
        asks: list[dict],
        last_trade_price: Optional[float] = None,
        last_trade_time: Optional[float] = None,
    ) -> LiquidityMetrics:
        """Run full liquidity analysis on an order book snapshot.

        Args:
            market_id: Market identifier.
            bids: Bid levels [{"price": float, "size": float}, ...].
            asks: Ask levels [{"price": float, "size": float}, ...].
            last_trade_price: Most recent trade price.
            last_trade_time: Timestamp of most recent trade.

        Returns:
            LiquidityMetrics with spread, depth, and opportunity scores.
        """
        spread = self._analyze_spread(bids, asks, last_trade_price, last_trade_time)
        depth = self._analyze_depth(bids, asks)
        resilience = self._compute_resilience(market_id, spread, depth)
        toxicity = self._compute_toxicity(spread, depth, last_trade_price)
        maker_score = self._compute_maker_opportunity(spread, depth, toxicity)

        metrics = LiquidityMetrics(
            market_id=market_id,
            spread=spread,
            depth=depth,
            resilience_score=resilience,
            toxicity_score=toxicity,
            maker_opportunity_score=maker_score,
        )

        # Track history for resilience calculation
        if market_id not in self._history:
            self._history[market_id] = []
        self._history[market_id].append(metrics)
        if len(self._history[market_id]) > 100:
            self._history[market_id] = self._history[market_id][-100:]

        return metrics

    def find_opportunities(
        self,
        market_id: str,
        bids: list[dict],
        asks: list[dict],
        bankroll: float = 100.0,
        last_trade_price: Optional[float] = None,
    ) -> list[MarketMakingOpportunity]:
        """Find market-making opportunities in the order book.

        Returns a list of opportunities sorted by expected spread capture.
        """
        metrics = self.analyze(market_id, bids, asks, last_trade_price)

        if metrics.toxicity_score > self.max_toxicity:
            return []

        if metrics.spread.spread_pct < self.min_spread_pct:
            return []

        opportunities: list[MarketMakingOpportunity] = []

        bid_price = metrics.spread.best_bid + 0.001
        ask_price = metrics.spread.best_ask - 0.001

        if bid_price >= ask_price:
            return []

        spread_capture = ask_price - bid_price
        fill_prob = self._estimate_fill_probability(metrics)
        risk = self._estimate_risk(metrics)

        max_exposure = bankroll * 0.1 * (1 - risk)
        recommended_size = min(max_exposure, bankroll * 0.05)

        if spread_capture > 0 and fill_prob > 0.3:
            confidence = fill_prob * (1 - risk) * min(1.0, spread_capture / 0.02)
            opportunities.append(MarketMakingOpportunity(
                market_id=market_id,
                bid_price=round(bid_price, 4),
                ask_price=round(ask_price, 4),
                expected_spread_capture=round(spread_capture, 4),
                estimated_fill_prob=round(fill_prob, 3),
                risk_score=round(risk, 3),
                recommended_size=round(recommended_size, 2),
                confidence=round(confidence, 3),
            ))

        opportunities.sort(key=lambda o: o.expected_spread_capture * o.confidence, reverse=True)
        return opportunities

    def get_spread_history(self, market_id: str) -> list[dict]:
        """Get historical spread data for a market."""
        history = self._history.get(market_id, [])
        return [
            {
                "spread_pct": m.spread.spread_pct,
                "mid_price": m.spread.mid_price,
                "depth_imbalance": m.depth.depth_imbalance,
                "timestamp": m.timestamp,
            }
            for m in history
        ]

    # ------------------------------------------------------------------
    # Internal analysis
    # ------------------------------------------------------------------

    def _analyze_spread(
        self,
        bids: list[dict],
        asks: list[dict],
        last_price: Optional[float],
        last_time: Optional[float],
    ) -> SpreadAnalysis:
        """Analyze bid-ask spread."""
        if not bids or not asks:
            return SpreadAnalysis(
                best_bid=0, best_ask=0, spread=0, spread_pct=0,
                mid_price=0, micro_price=0, time_since_last_trade_s=0,
            )

        best_bid = max(float(b.get("price", 0)) for b in bids)
        best_ask = min(float(a.get("price", 0)) for a in asks)
        spread = best_ask - best_bid
        mid = (best_bid + best_ask) / 2
        spread_pct = spread / mid if mid > 0 else 0

        bid_size = sum(float(b.get("size", 0)) for b in bids if float(b.get("price", 0)) == best_bid)
        ask_size = sum(float(a.get("size", 0)) for a in asks if float(a.get("price", 0)) == best_ask)
        total_size = bid_size + ask_size
        micro_price = (
            (best_bid * ask_size + best_ask * bid_size) / total_size
            if total_size > 0 else mid
        )

        time_since = (time.time() - last_time) if last_time else 0

        return SpreadAnalysis(
            best_bid=best_bid,
            best_ask=best_ask,
            spread=spread,
            spread_pct=spread_pct,
            mid_price=mid,
            micro_price=micro_price,
            time_since_last_trade_s=time_since,
        )

    def _analyze_depth(self, bids: list[dict], asks: list[dict]) -> DepthAnalysis:
        """Analyze order book depth."""
        sorted_bids = sorted(bids, key=lambda x: float(x.get("price", 0)), reverse=True)
        sorted_asks = sorted(asks, key=lambda x: float(x.get("price", 0)))

        mid = 0
        if sorted_bids and sorted_asks:
            mid = (float(sorted_bids[0].get("price", 0)) + float(sorted_asks[0].get("price", 0))) / 2

        bid_levels: list[DepthLevel] = []
        cum_bid = 0.0
        wall_bid_price = None
        wall_bid_size = 0.0
        for b in sorted_bids[: self.depth_levels]:
            price = float(b.get("price", 0))
            size = float(b.get("size", 0))
            cum_bid += size
            dist = ((mid - price) / mid * 100) if mid > 0 else 0
            bid_levels.append(DepthLevel(
                price=price, size=size, cumulative_size=cum_bid,
                distance_from_mid_pct=dist,
            ))
            if size > wall_bid_size:
                wall_bid_size = size
                wall_bid_price = price

        ask_levels: list[DepthLevel] = []
        cum_ask = 0.0
        wall_ask_price = None
        wall_ask_size = 0.0
        for a in sorted_asks[: self.depth_levels]:
            price = float(a.get("price", 0))
            size = float(a.get("size", 0))
            cum_ask += size
            dist = ((price - mid) / mid * 100) if mid > 0 else 0
            ask_levels.append(DepthLevel(
                price=price, size=size, cumulative_size=cum_ask,
                distance_from_mid_pct=dist,
            ))
            if size > wall_ask_size:
                wall_ask_size = size
                wall_ask_price = price

        total = cum_bid + cum_ask
        imbalance = (cum_bid - cum_ask) / total if total > 0 else 0
        ratio = cum_bid / cum_ask if cum_ask > 0 else float("inf")

        return DepthAnalysis(
            bid_depth=bid_levels,
            ask_depth=ask_levels,
            total_bid_size=cum_bid,
            total_ask_size=cum_ask,
            depth_imbalance=imbalance,
            depth_ratio=ratio,
            wall_bid_price=wall_bid_price,
            wall_ask_price=wall_ask_price,
        )

    def _compute_resilience(
        self, market_id: str, spread: SpreadAnalysis, depth: DepthAnalysis
    ) -> float:
        """Compute book resilience score (0-1)."""
        history = self._history.get(market_id, [])
        if len(history) < 2:
            return 0.5

        recent_spreads = [m.spread.spread_pct for m in history[-20:]]
        recent_depths = [m.depth.total_bid_size + m.depth.total_ask_size for m in history[-20:]]

        spread_stability = 1.0 - min(1.0, statistics.stdev(recent_spreads) / max(statistics.mean(recent_spreads), 0.001))
        depth_stability = 1.0 - min(1.0, statistics.stdev(recent_depths) / max(statistics.mean(recent_depths), 0.001))

        return (spread_stability * 0.5 + depth_stability * 0.5)

    def _compute_toxicity(
        self, spread: SpreadAnalysis, depth: DepthAnalysis, last_price: Optional[float]
    ) -> float:
        """Compute adverse selection / toxicity score (0-1)."""
        factors: list[float] = []

        spread_factor = min(1.0, spread.spread_pct / 0.05) if spread.spread_pct > 0 else 0
        factors.append(spread_factor * 0.3)

        total_depth = depth.total_bid_size + depth.total_ask_size
        depth_factor = min(1.0, total_depth / 1000)
        factors.append(depth_factor * 0.3)

        imbalance_factor = abs(depth.depth_imbalance)
        factors.append(imbalance_factor * 0.4)

        return min(1.0, sum(factors))

    def _compute_maker_opportunity(
        self, spread: SpreadAnalysis, depth: DepthAnalysis, toxicity: float
    ) -> float:
        """Compute market-making opportunity score (0-1)."""
        if spread.spread_pct < self.min_spread_pct:
            return 0.0

        spread_score = min(1.0, spread.spread_pct / 0.03)
        balance_score = 1.0 - abs(depth.depth_imbalance)
        safety_score = 1.0 - toxicity

        return (spread_score * 0.4 + balance_score * 0.3 + safety_score * 0.3)

    def _estimate_fill_probability(self, metrics: LiquidityMetrics) -> float:
        """Estimate probability of both sides filling."""
        spread_factor = min(1.0, metrics.spread.spread_pct / 0.02)
        balance = 1.0 - abs(metrics.depth.depth_imbalance)
        return spread_factor * 0.5 + balance * 0.5

    def _estimate_risk(self, metrics: LiquidityMetrics) -> float:
        """Estimate risk score for market making (0-1)."""
        return metrics.toxicity_score * 0.6 + abs(metrics.depth.depth_imbalance) * 0.4
