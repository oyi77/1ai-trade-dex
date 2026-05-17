"""Persist sentiment analysis results to the Knowledge Graph.

Stores ``SentimentResult`` objects as KG entities of type ``sentiment_snapshot``
and links them to market entities via an ``INFLUENCED`` relation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from loguru import logger

from backend.core.knowledge_graph import KnowledgeGraph


class SentimentPersistence:
    """Stores and queries sentiment snapshots in the Knowledge Graph."""

    def __init__(self, kg: KnowledgeGraph):
        self._kg = kg

    def store_sentiment(
        self,
        source: str,
        score: float,
        label: str,
        confidence: float,
        market_ticker: str,
        timestamp: Optional[datetime] = None,
    ) -> str:
        """Persist a single sentiment result as a KG entity.

        Returns the entity_id of the created snapshot.
        """
        ts = timestamp or datetime.now(timezone.utc)
        entity_id = f"sentiment:{market_ticker}:{int(ts.timestamp())}"

        self._kg.add_entity(
            entity_type="sentiment_snapshot",
            entity_id=entity_id,
            properties={
                "source": source,
                "score": score,
                "label": label,
                "confidence": confidence,
                "timestamp": ts.isoformat(),
                "market_ticker": market_ticker,
            },
        )

        # Ensure market entity exists, then link via INFLUENCED
        market_entity_id = f"market:{market_ticker}"
        existing_market = self._kg.get_entity(market_entity_id)
        if existing_market is None:
            self._kg.add_entity("market", market_entity_id, {"ticker": market_ticker})

        try:
            self._kg.add_relation(
                from_entity_id=entity_id,
                to_entity_id=market_entity_id,
                relation_type="INFLUENCED",
                weight=abs(score),
                confidence=confidence,
            )
        except Exception as exc:
            logger.warning("Failed to link sentiment to market: %s", exc)

        return entity_id

    def get_sentiment_history(
        self,
        market_ticker: str,
        lookback_hours: int = 24,
    ) -> list[dict[str, Any]]:
        """Return sentiment snapshots for *market_ticker* within the lookback window."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        market_entity_id = f"market:{market_ticker}"

        # Get all sentiment_snapshot entities linked to this market
        self._kg.get_related(market_entity_id, relation_type="INFLUENCED")
        # Also check direct sentiment entities by ticker
        sentiments = self._kg.query_by_type("sentiment_snapshot", limit=200)

        results: list[dict[str, Any]] = []
        for ent in sentiments:
            props = ent.properties or {}
            if props.get("market_ticker") != market_ticker:
                continue
            ts_str = props.get("timestamp")
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts < cutoff:
                        continue
                except (ValueError, TypeError):
                    continue
            results.append(props)

        results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return results

    def get_sentiment_trend(
        self,
        market_ticker: str,
        lookback_hours: int = 24,
    ) -> dict[str, Any]:
        """Determine whether sentiment is trending more bullish or bearish.

        Returns ``{"trend": "bullish"|"bearish"|"neutral", "avg_score": float, "count": int}``.
        """
        history = self.get_sentiment_history(market_ticker, lookback_hours)
        if not history:
            return {"trend": "neutral", "avg_score": 0.0, "count": 0}

        scores = [h.get("score", 0.0) for h in history]
        avg = sum(scores) / len(scores) if scores else 0.0

        if avg > 0.1:
            trend = "bullish"
        elif avg < -0.1:
            trend = "bearish"
        else:
            trend = "neutral"

        return {"trend": trend, "avg_score": round(avg, 4), "count": len(history)}
