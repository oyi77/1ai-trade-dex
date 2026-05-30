"""Sentiment EdgeCalculator — news/social sentiment edge.

Computes model probability from aggregated sentiment signals
(news sentiment, social media, on-chain activity).
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from backend.strategies.edge_models.base import EdgeCalculator, EdgeResult


class SentimentEdgeCalculator(EdgeCalculator):
    """Edge from news and social sentiment.

    Expected market_data keys:
        - 'sentiment_score': float (-1.0 bearish to +1.0 bullish)
        - 'news_volume': int (number of recent news items)
        - 'social_volume': int (number of social mentions)
        - 'on_chain_signal': float (-1.0 to +1.0, optional)
    """

    @property
    def name(self) -> str:
        return "sentiment"

    @property
    def description(self) -> str:
        return (
            "Sentiment edge from news, social media, and on-chain signals. "
            "Converts aggregated sentiment into model probability."
        )

    async def calculate(
        self,
        market_price: float,
        market_data: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> EdgeResult | None:
        params = params or {}
        sentiment_score = market_data.get("sentiment_score")
        if sentiment_score is None:
            logger.debug("SentimentEdgeCalculator: no sentiment_score, skipping")
            return None

        news_volume = market_data.get("news_volume", 0)
        social_volume = market_data.get("social_volume", 0)
        on_chain = market_data.get("on_chain_signal", 0.0)

        # Volume-weighted confidence: more sources = higher confidence
        total_volume = news_volume + social_volume
        volume_factor = min(1.0, total_volume / 50.0)  # saturates at 50 mentions

        # Weighted sentiment: news 40%, social 35%, on-chain 25%
        weighted = (
            sentiment_score * 0.40
            + market_data.get("social_sentiment", sentiment_score) * 0.35
            + on_chain * 0.25
        )

        # Map sentiment to probability
        base_prob = params.get("sentiment_base", 0.50)
        scale = params.get("sentiment_scale", 0.25)
        model_probability = base_prob + weighted * scale
        model_probability = max(0.0, min(1.0, model_probability))

        direction = "up" if model_probability > 0.5 else "down"
        edge = abs(model_probability - market_price)

        min_edge = params.get("min_edge", 0.02)
        if edge < min_edge:
            return None

        confidence = min(1.0, volume_factor * abs(weighted))

        return EdgeResult(
            edge=edge,
            model_probability=model_probability,
            confidence=confidence,
            direction=direction,
            reasoning=(
                f"Sentiment: score={sentiment_score:.3f}, news={news_volume}, "
                f"social={social_volume}, on_chain={on_chain:.3f}"
            ),
            metadata={
                "sentiment_score": sentiment_score,
                "news_volume": news_volume,
                "social_volume": social_volume,
                "on_chain_signal": on_chain,
                "weighted_sentiment": weighted,
            },
        )
