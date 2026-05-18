"""News Collector — fetch from HuggingFace dataset, integrate with SentimentAnalyzer.

Fetches prediction-market news articles from HuggingFace datasets, runs them
through the LLM-based SentimentAnalyzer, and provides scored news items for
consumption by the RAG pipeline and debate engine.

Usage:
    from backend.data.news_collector import NewsCollector
    collector = NewsCollector()
    scored = await collector.collect_and_analyze(limit=50)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import List, Optional

import httpx
from loguru import logger

# HuggingFace datasets-server API for row-based access
HF_ROWS_API = "https://datasets-server.huggingface.co/rows"
DEFAULT_DATASET = "SII-WANGZJ/Polymarket_data"


@dataclass
class ScoredArticle:
    """A news article enriched with sentiment score."""
    title: str
    text: str
    source: str
    url: str = ""
    published: str = ""
    sentiment_score: float = 0.0      # -1.0 .. 1.0
    sentiment_label: str = "neutral"   # positive | negative | neutral
    sentiment_confidence: float = 0.0  # 0.0 .. 1.0

    def to_context_string(self) -> str:
        """Format as a one-line context string for debate injection."""
        return (
            "[%s] %s (sentiment=%.2f, conf=%.2f): %s"
            % (self.source, self.title, self.sentiment_score,
               self.sentiment_confidence, self.text[:300])
        )


class NewsCollector:
    """Fetch news from HuggingFace dataset and score via SentimentAnalyzer.

    Args:
        dataset: HuggingFace dataset identifier.
        analyzer: Optional SentimentAnalyzer instance. Created if not provided.
    """

    def __init__(
        self,
        dataset: str = DEFAULT_DATASET,
        analyzer=None,
    ):
        self.dataset = dataset
        self._analyzer = analyzer

    def _get_analyzer(self):
        if self._analyzer is None:
            from backend.ai.sentiment_analyzer import SentimentAnalyzer
            self._analyzer = SentimentAnalyzer()
        return self._analyzer

    async def fetch_articles(self, limit: int = 100) -> List[dict]:
        """Fetch raw articles from HuggingFace datasets-server API.

        Returns:
            List of dicts with keys: title, text, source, url, published.
        """
        articles: List[dict] = []
        offset = 0

        async with httpx.AsyncClient(timeout=30.0) as client:
            while offset < limit:
                batch_size = min(100, limit - offset)
                params = {
                    "dataset": self.dataset,
                    "config": "default",
                    "split": "train",
                    "offset": offset,
                    "length": batch_size,
                }
                try:
                    resp = await client.get(HF_ROWS_API, params=params)
                    if resp.status_code != 200:
                        logger.warning("news_collector: HF API returned %d", resp.status_code)
                        break
                    data = resp.json()
                    rows = data.get("rows", [])
                    if not rows:
                        break
                    for row_data in rows:
                        row = row_data.get("row", row_data)
                        text = row.get("text", row.get("content", ""))
                        title = row.get("title", "")
                        if text:
                            articles.append({
                                "title": title,
                                "text": text,
                                "source": row.get("source", "huggingface"),
                                "url": row.get("url", ""),
                                "published": row.get("published", row.get("date", "")),
                            })
                    offset += len(rows)
                    if len(rows) < batch_size:
                        break
                except Exception as e:
                    logger.warning("news_collector: fetch failed at offset=%d: %s", offset, e)
                    break

        logger.info("news_collector: fetched %d articles from %s", len(articles), self.dataset)
        return articles

    async def analyze_articles(self, articles: List[dict]) -> List[ScoredArticle]:
        """Run sentiment analysis on fetched articles.

        Args:
            articles: List of dicts from fetch_articles().

        Returns:
            List of ScoredArticle with sentiment scores populated.
        """
        analyzer = self._get_analyzer()
        scored: List[ScoredArticle] = []

        # Build text list for batch analysis
        texts = [a["text"][:4000] for a in articles]
        results = await analyzer.analyze_batch(texts)

        for article, result in zip(articles, results):
            scored.append(ScoredArticle(
                title=article["title"],
                text=article["text"],
                source=article["source"],
                url=article.get("url", ""),
                published=article.get("published", ""),
                sentiment_score=result.score,
                sentiment_label=result.label,
                sentiment_confidence=result.confidence,
            ))

        logger.info(
            "news_collector: analyzed %d articles (pos=%d, neg=%d, neu=%d)",
            len(scored),
            sum(1 for s in scored if s.sentiment_label == "positive"),
            sum(1 for s in scored if s.sentiment_label == "negative"),
            sum(1 for s in scored if s.sentiment_label == "neutral"),
        )
        return scored

    async def collect_and_analyze(self, limit: int = 50) -> List[ScoredArticle]:
        """Full pipeline: fetch articles from HF, then score with sentiment.

        Args:
            limit: Maximum number of articles to fetch.

        Returns:
            List of ScoredArticle sorted by absolute sentiment (strongest first).
        """
        articles = await self.fetch_articles(limit=limit)
        if not articles:
            return []

        scored = await self.analyze_articles(articles)
        # Sort by absolute sentiment score (strongest opinions first)
        scored.sort(key=lambda s: abs(s.sentiment_score), reverse=True)
        return scored

    def scored_to_context(self, scored: List[ScoredArticle], max_chars: int = 2000) -> str:
        """Format scored articles as a context string for debate engine.

        Args:
            scored: List of ScoredArticle from collect_and_analyze().
            max_chars: Maximum output length.

        Returns:
            Formatted multi-line context string.
        """
        if not scored:
            return ""

        lines = ["NEWS SENTIMENT CONTEXT:"]
        total = len(lines[0])

        for i, article in enumerate(scored, 1):
            line = "\n%d. %s" % (i, article.to_context_string())
            if total + len(line) > max_chars:
                break
            lines.append(line)
            total += len(line)

        return "\n".join(lines)
