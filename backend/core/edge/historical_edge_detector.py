"""Historical edge detector — finds calibration mispricing using past market outcomes.

Queries the trades database for similar resolved markets and compares
current market price against historical outcome frequency. When the gap
exceeds a threshold, generates CALIBRATION_MISPRICING edges.

This is the data-driven edge that the system has been missing — using
its own 6,557 settled trades as a training set instead of relying
solely on LLM debate opinions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from sqlalchemy import func

from backend.core.edge.edge_model import Edge, EdgeType
from backend.db.utils import get_db_session, utcnow


# ── Configuration ────────────────────────────────────────────────────────────

MIN_SIMILAR_MARKETS = 10       # minimum resolved markets for statistical significance
MIN_MISPRICING_GAP_PP = 0.05   # minimum gap in percentage points (5pp)
MAX_MARKET_AGE_DAYS = 180      # only consider markets from last 6 months
MIN_CONFIDENCE_FOR_EDGE = 0.3  # minimum confidence to emit an edge


@dataclass
class HistoricalEdge:
    """A detected calibration mispricing edge with supporting evidence."""
    market_id: str
    token_id: str
    direction: str
    entry_price: float
    historical_frequency: float  # actual win rate for similar markets
    gap_pp: float                # |entry_price - historical_frequency|
    sample_size: int             # number of similar resolved markets
    confidence: float            # 0-1, based on sample size and gap magnitude
    similar_categories: list[str] = field(default_factory=list)


class HistoricalEdgeDetector:
    """Detect edges by comparing current prices to historical outcome frequencies.

    Usage:
        detector = HistoricalEdgeDetector()
        edges = detector.detect(market_question="Will BTC hit $100K?",
                                market_price=0.65, category="crypto")
    """

    def __init__(
        self,
        min_similar: int = MIN_SIMILAR_MARKETS,
        min_gap_pp: float = MIN_MISPRICING_GAP_PP,
        max_age_days: int = MAX_MARKET_AGE_DAYS,
    ):
        self.min_similar = min_similar
        self.min_gap_pp = min_gap_pp
        self.max_age_days = max_age_days

    def detect(
        self,
        market_question: str,
        market_price: float,
        category: str = "",
        market_id: str = "",
        token_id: str = "",
    ) -> list[Edge]:
        """Detect calibration mispricing edges for a market.

        Args:
            market_question: The market question text
            market_price: Current market probability [0, 1]
            category: Market category for similarity matching
            market_id: Market identifier
            token_id: CLOB token ID

        Returns:
            List of Edge objects (empty if no mispricing detected)
        """
        edges: list[Edge] = []

        # Query similar resolved markets
        similar = self._query_similar_markets(market_question, category)
        if len(similar) < self.min_similar:
            logger.debug(
                f"[HistoricalEdge] '{market_question[:40]}' — "
                f"only {len(similar)} similar markets (need {self.min_similar})"
            )
            return edges

        # Compute historical frequency
        wins = sum(1 for s in similar if s["result"] == "win")
        historical_freq = wins / len(similar)
        gap_pp = abs(market_price - historical_freq)

        if gap_pp < self.min_gap_pp:
            logger.debug(
                f"[HistoricalEdge] '{market_question[:40]}' — "
                f"gap={gap_pp:.3f} below threshold {self.min_gap_pp}"
            )
            return edges

        # Determine direction: if market underpriced relative to history, buy YES
        direction = "yes" if historical_freq > market_price else "no"
        fair_price = historical_freq

        # Confidence: based on sample size and gap magnitude
        sample_confidence = min(1.0, len(similar) / 50.0)  # max at 50 samples
        gap_confidence = min(1.0, gap_pp / 0.15)           # max at 15pp gap
        confidence = (sample_confidence * 0.4 + gap_confidence * 0.6)

        if confidence < MIN_CONFIDENCE_FOR_EDGE:
            return edges

        edge_score = gap_pp * confidence

        edge = Edge(
            market_id=market_id or market_question[:40],
            token_id=token_id or "",
            edge_type=EdgeType.CALIBRATION_MISPRICING,
            direction=direction,
            entry_price=market_price,
            fair_price=fair_price,
            edge_pp=gap_pp,
            confidence=confidence,
            edge_score=edge_score,
            time_horizon_min=1440,  # 24h — calibration edges are slower
            metadata={
                "historical_frequency": historical_freq,
                "sample_size": len(similar),
                "similar_categories": list(set(s["category"] for s in similar if s.get("category")))[:5],
                "detector": "HistoricalEdgeDetector",
            },
            detected_at=datetime.now(timezone.utc),
        )

        logger.info(
            f"[HistoricalEdge] '{market_question[:40]}' — "
            f"price={market_price:.3f} hist_freq={historical_freq:.3f} "
            f"gap={gap_pp:.3f}pp dir={direction} conf={confidence:.2f} "
            f"n={len(similar)}"
        )
        edges.append(edge)
        return edges

    def detect_batch(
        self,
        markets: list[dict],
    ) -> list[Edge]:
        """Detect edges for a batch of markets.

        Args:
            markets: List of dicts with keys: question, price, category, market_id, token_id

        Returns:
            List of Edge objects sorted by edge_score descending
        """
        all_edges: list[Edge] = []
        for m in markets:
            edges = self.detect(
                market_question=m.get("question", ""),
                market_price=m.get("price", 0.5),
                category=m.get("category", ""),
                market_id=m.get("market_id", ""),
                token_id=m.get("token_id", ""),
            )
            all_edges.extend(edges)

        all_edges.sort(key=lambda e: e.edge_score, reverse=True)
        return all_edges

    # ── private ──────────────────────────────────────────────────────────────

    def _query_similar_markets(
        self, question: str, category: str
    ) -> list[dict]:
        """Query the trades database for similar resolved markets.

        Similarity is based on:
        1. Same category (if provided)
        2. Keyword overlap in market question
        3. Settled within max_age_days
        """
        from backend.models.database import Trade

        cutoff = utcnow()
        try:
            from datetime import timedelta
            cutoff = utcnow() - timedelta(days=self.max_age_days)
        except Exception:
            pass

        with get_db_session() as db:
            # Base query: settled trades with known outcomes
            query = (
                db.query(
                    Trade.market_ticker,
                    Trade.result,
                    Trade.market_type,
                    func.count(Trade.id).label("count"),
                )
                .filter(
                    Trade.settled.is_(True),
                    Trade.result.isnot(None),
                    Trade.result.in_(["win", "loss"]),
                )
            )

            # Category filter
            if category:
                query = query.filter(Trade.market_type == category)

            # Keyword overlap: extract significant words from question
            keywords = self._extract_keywords(question)
            if keywords:
                # Match any keyword in market_ticker
                from sqlalchemy import or_
                keyword_filters = [
                    Trade.market_ticker.ilike(f"%{kw}%") for kw in keywords[:5]
                ]
                if keyword_filters:
                    query = query.filter(or_(*keyword_filters))

            # Group by market to avoid double-counting
            query = query.group_by(
                Trade.market_ticker, Trade.result, Trade.market_type
            )

            rows = query.limit(200).all()

        results: list[dict] = []
        seen_tickers: set[str] = set()
        for row in rows:
            ticker = row.market_ticker or ""
            if ticker in seen_tickers:
                continue
            seen_tickers.add(ticker)
            results.append({
                "ticker": ticker,
                "result": row.result,
                "category": row.market_type or "",
            })

        return results

    @staticmethod
    def _extract_keywords(question: str) -> list[str]:
        """Extract significant keywords from a market question.

        Filters out common stop words and short tokens.
        """
        stop_words = {
            "will", "the", "be", "a", "an", "in", "on", "at", "to", "of",
            "for", "by", "or", "and", "is", "are", "was", "has", "have",
            "what", "which", "who", "how", "when", "where", "if", "than",
            "that", "this", "these", "those", "it", "its", "from", "with",
            "above", "below", "over", "under", "before", "after", "between",
            "any", "all", "some", "most", "more", "less", "no", "not",
            "there", "their", "they", "about", "into", "up", "out", "do",
            "does", "did", "can", "could", "may", "might", "shall", "should",
            "would", "get", "got", "make", "made", "go", "went", "come",
        }
        tokens = question.lower().replace("?", "").replace(",", "").split()
        keywords = [
            t for t in tokens
            if len(t) > 2 and t not in stop_words and not t.isdigit()
        ]
        # Return longest/most distinctive words first
        keywords.sort(key=lambda k: len(k), reverse=True)
        return keywords[:8]


# ── Module-level singleton ───────────────────────────────────────────────────

_detector: HistoricalEdgeDetector | None = None


def get_historical_edge_detector() -> HistoricalEdgeDetector:
    global _detector
    if _detector is None:
        _detector = HistoricalEdgeDetector()
    return _detector


def reset_historical_edge_detector() -> None:
    global _detector
    _detector = None
