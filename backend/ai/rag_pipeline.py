"""RAG pipeline for news-informed market predictions."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, List

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
        logger.info("rag_pipeline: ingested %d chunks from %d articles", len(docs), len(articles))
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
            summary_parts.append("[%.2f] %s (%s): %s..." % (score, title, source, doc.text[:200]))

        return RAGContext(
            query=question,
            documents=documents,
            scores=scores,
            summary="\n".join(summary_parts),
        )

    def query_for_market(self, market_question: str, top_k: int = 5) -> RAGContext:
        """Query with market-specific context enhancement."""
        enhanced = "prediction market: %s" % market_question
        return self.query(enhanced, top_k=top_k)

    def get_stats(self) -> Dict[str, Any]:
        """Return pipeline statistics."""
        return {
            "total_documents": self.store.size,
            "embedding_dim": self.embedder.dim,
        }

    def retrieve_context_for_debate(
        self,
        market_question: str,
        category: str = "",
        top_k: int = 5,
        max_chars: int = 3000,
    ) -> str:
        """Retrieve relevant context for the debate engine.

        Builds an enhanced query from the market question and category,
        then formats the top results as a context string suitable for
        injection into debate prompts via the ``context`` parameter of
        ``backend.ai.debate_engine.run_debate()``.

        Args:
            market_question: The prediction market question.
            category: Optional market category for query enhancement.
            top_k: Number of documents to retrieve.
            max_chars: Maximum character length of the returned context.

        Returns:
            Formatted context string with source attribution, or empty string
            if no relevant documents are found.
        """
        rag_ctx = self.query_for_market(market_question, top_k=top_k)
        if not rag_ctx.documents:
            return ""

        lines = ["RELEVANT CONTEXT (retrieved by RAG pipeline):"]
        total_chars = len(lines[0])

        for i, (doc, score) in enumerate(zip(rag_ctx.documents, rag_ctx.scores), 1):
            source = doc.metadata.get("source", "unknown")
            title = doc.metadata.get("title", "")
            snippet = "\n[%d] (source=%s, relevance=%.2f) %s: %s" % (i, source, score, title, doc.text[:500])
            if total_chars + len(snippet) > max_chars:
                break
            lines.append(snippet)
            total_chars += len(snippet)

        context = "\n".join(lines)
        logger.info(
            "rag_pipeline: retrieved %d docs for debate (chars=%d)",
            min(len(rag_ctx.documents), len(lines) - 1),
            len(context),
        )
        return context


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_pipeline_instance: RAGPipeline | None = None


def get_rag_pipeline() -> RAGPipeline:
    """Get or create the global RAG pipeline singleton."""
    global _pipeline_instance
    if _pipeline_instance is None:
        _pipeline_instance = RAGPipeline()
    return _pipeline_instance


def reset_rag_pipeline() -> None:
    """Reset the global pipeline (useful for testing)."""
    global _pipeline_instance
    _pipeline_instance = None
