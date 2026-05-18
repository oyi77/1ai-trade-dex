"""RAG pipeline for news-informed market predictions.

Pattern inspired by Polymarket/agents: ingest news, chunk, embed,
store in vector index, then retrieve relevant context for market queries.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List

from backend.ai.news_ingester import NewsArticle, NewsIngester
from backend.ai.vector_store import Document, VectorStore

from loguru import logger


@dataclass
class RAGContext:
    """Retrieved context for a market query."""
    query: str
    documents: List[Document]
    scores: List[float]
    summary: str = ""


class EmbeddingProvider:
    """Simple embedding provider using TF-IDF-like approach.

    Uses a lightweight bag-of-words with hashing trick for dimensionality
    reduction. No external dependencies required.
    """

    def __init__(self, dim: int = 256):
        self.dim = dim

    def embed(self, text: str) -> List[float]:
        """Produce a fixed-dimension embedding from text."""
        vec = [0.0] * self.dim
        words = text.lower().split()
        if not words:
            return vec
        for word in words:
            idx = hash(word) % self.dim
            vec[idx] += 1.0
        # L2 normalize
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of texts."""
        return [self.embed(t) for t in texts]


class RAGPipeline:
    """End-to-end RAG pipeline: ingest -> chunk -> embed -> store -> retrieve."""

    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        embedding_dim: int = 256,
    ):
        self.ingester = NewsIngester(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        self.embedder = EmbeddingProvider(dim=embedding_dim)
        self.store = VectorStore()

    async def ingest_hf_dataset(self, dataset: str = "prediction-market-news", limit: int = 100) -> int:
        """Ingest news from HuggingFace dataset into vector store."""
        articles = await self.ingester.fetch_hf_news(dataset=dataset, limit=limit)
        return await self._ingest_articles(articles)

    async def ingest_urls(self, urls: List[str]) -> int:
        """Ingest news from URLs into vector store."""
        articles = await self.ingester.fetch_url_news(urls)
        return await self._ingest_articles(articles)

    async def ingest_articles(self, articles: List[NewsArticle]) -> int:
        """Ingest pre-fetched articles into vector store."""
        return await self._ingest_articles(articles)

    async def _ingest_articles(self, articles: List[NewsArticle]) -> int:
        """Chunk, embed, and store articles."""
        chunks = self.ingester.chunk_articles(articles)
        if not chunks:
            return 0

        texts = [c.text for c in chunks]
        embeddings = self.embedder.embed_batch(texts)

        docs = []
        for chunk, embedding in zip(chunks, embeddings):
            doc = Document(
                text=chunk.text,
                embedding=embedding,
                metadata={
                    "article_id": chunk.article_id,
                    "chunk_index": str(chunk.chunk_index),
                    **chunk.metadata,
                },
                doc_id=f"{chunk.article_id}_{chunk.chunk_index}",
            )
            docs.append(doc)

        self.store.add_batch(docs)
        logger.info(f"rag_pipeline: ingested {len(docs)} chunks from {len(articles)} articles")
        return len(docs)

    def query(self, question: str, top_k: int = 5) -> RAGContext:
        """Query the vector store for relevant news context."""
        query_embedding = self.embedder.embed(question)
        results = self.store.search(query_embedding, top_k=top_k)

        documents = [doc for doc, _ in results]
        scores = [score for _, score in results]

        summary_parts = []
        for doc, score in results:
            source = doc.metadata.get("source", "unknown")
            title = doc.metadata.get("title", "")
            summary_parts.append(f"[{score:.2f}] {title} ({source}): {doc.text[:200]}...")

        return RAGContext(
            query=question,
            documents=documents,
            scores=scores,
            summary="\n".join(summary_parts),
        )

    def query_for_market(self, market_question: str, top_k: int = 5) -> RAGContext:
        """Query with market-specific context enhancement."""
        # Enhance the query with market-relevant terms
        enhanced = f"prediction market: {market_question}"
        return self.query(enhanced, top_k=top_k)

    def get_stats(self) -> Dict[str, Any]:
        """Return pipeline statistics."""
        return {
            "total_documents": self.store.size,
            "embedding_dim": self.embedder.dim,
        }
