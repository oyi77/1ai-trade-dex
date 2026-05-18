"""News ingester for the RAG pipeline.

Fetches prediction-market news from multiple sources and chunks them
for embedding and vector storage.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Dict, List

import httpx

from loguru import logger

# HuggingFace dataset for prediction market news
HF_NEWS_DATASET = "prediction-market-news"
HF_NEWS_API = "https://datasets-server.huggingface.co/rows"


@dataclass
class NewsArticle:
    """A raw news article before chunking."""
    title: str
    text: str
    source: str = "unknown"
    url: str = ""
    published: str = ""
    metadata: Dict[str, str] = field(default_factory=dict)

    @property
    def article_id(self) -> str:
        raw = f"{self.source}:{self.title}:{self.url}"
        return hashlib.md5(raw.encode()).hexdigest()[:12]


@dataclass
class NewsChunk:
    """A chunk of a news article ready for embedding."""
    text: str
    article_id: str
    chunk_index: int
    metadata: Dict[str, str] = field(default_factory=dict)


class NewsIngester:
    """Fetches and chunks news articles from multiple sources."""

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    async def fetch_hf_news(
        self, dataset: str = HF_NEWS_DATASET, limit: int = 100
    ) -> List[NewsArticle]:
        """Fetch news from HuggingFace datasets API."""
        articles: List[NewsArticle] = []
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                offset = 0
                while offset < limit:
                    batch_size = min(100, limit - offset)
                    params = {
                        "dataset": dataset,
                        "config": "default",
                        "split": "train",
                        "offset": offset,
                        "length": batch_size,
                    }
                    resp = await client.get(HF_NEWS_API, params=params)
                    if resp.status_code != 200:
                        logger.warning(f"HF news API returned {resp.status_code}")
                        break
                    data = resp.json()
                    rows = data.get("rows", [])
                    if not rows:
                        break
                    for row_data in rows:
                        row = row_data.get("row", row_data)
                        article = NewsArticle(
                            title=row.get("title", ""),
                            text=row.get("text", row.get("content", "")),
                            source=row.get("source", "huggingface"),
                            url=row.get("url", ""),
                            published=row.get("published", row.get("date", "")),
                        )
                        if article.text:
                            articles.append(article)
                    offset += len(rows)
                    if len(rows) < batch_size:
                        break
        except Exception as e:
            logger.warning(f"Failed to fetch HF news: {e}")
        logger.info(f"news_ingester: fetched {len(articles)} articles from HF")
        return articles

    async def fetch_url_news(self, urls: List[str]) -> List[NewsArticle]:
        """Fetch and extract text from news URLs."""
        articles: List[NewsArticle] = []
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            for url in urls:
                try:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        continue
                    text = _extract_text_from_html(resp.text)
                    if text:
                        articles.append(NewsArticle(
                            title=_extract_title(resp.text),
                            text=text,
                            source=url.split("/")[2] if "/" in url else url,
                            url=url,
                        ))
                except Exception as e:
                    logger.debug(f"Failed to fetch {url}: {e}")
        logger.info(f"news_ingester: fetched {len(articles)} articles from URLs")
        return articles

    def chunk_articles(self, articles: List[NewsArticle]) -> List[NewsChunk]:
        """Split articles into overlapping text chunks."""
        chunks: List[NewsChunk] = []
        for article in articles:
            text = article.text.strip()
            if not text:
                continue
            # Split on sentence boundaries when possible
            sentences = re.split(r'(?<=[.!?])\s+', text)
            current_chunk = ""
            chunk_idx = 0
            for sentence in sentences:
                if len(current_chunk) + len(sentence) > self.chunk_size and current_chunk:
                    chunks.append(NewsChunk(
                        text=current_chunk.strip(),
                        article_id=article.article_id,
                        chunk_index=chunk_idx,
                        metadata={
                            "title": article.title,
                            "source": article.source,
                            "url": article.url,
                            **article.metadata,
                        },
                    ))
                    chunk_idx += 1
                    # Keep overlap
                    overlap_text = current_chunk[-self.chunk_overlap:] if self.chunk_overlap else ""
                    current_chunk = overlap_text + " " + sentence
                else:
                    current_chunk = (current_chunk + " " + sentence).strip()
            if current_chunk.strip():
                chunks.append(NewsChunk(
                    text=current_chunk.strip(),
                    article_id=article.article_id,
                    chunk_index=chunk_idx,
                    metadata={
                        "title": article.title,
                        "source": article.source,
                        "url": article.url,
                        **article.metadata,
                    },
                ))
        logger.info(f"news_ingester: created {len(chunks)} chunks from {len(articles)} articles")
        return chunks


def _extract_text_from_html(html: str) -> str:
    """Simple HTML text extraction (no external deps)."""
    # Remove script/style tags and their content
    html = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', ' ', html)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _extract_title(html: str) -> str:
    """Extract title from HTML."""
    match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""
