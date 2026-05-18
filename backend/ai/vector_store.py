"""In-memory vector store for RAG pipeline.

Simple cosine-similarity based retrieval. Upgrade path: FAISS or ChromaDB.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class Document:
    """A document chunk with embedding and metadata."""
    text: str
    embedding: List[float] = field(default_factory=list)
    metadata: Dict[str, str] = field(default_factory=dict)
    doc_id: str = ""


class VectorStore:
    """In-memory vector store with cosine similarity search."""

    def __init__(self):
        self._documents: List[Document] = []
        self._index_dirty: bool = False

    @property
    def size(self) -> int:
        return len(self._documents)

    def add(self, doc: Document) -> None:
        """Add a single document to the store."""
        if not doc.doc_id:
            doc.doc_id = f"doc_{len(self._documents)}"
        self._documents.append(doc)
        self._index_dirty = True

    def add_batch(self, docs: List[Document]) -> None:
        """Add multiple documents."""
        for doc in docs:
            self.add(doc)

    def search(self, query_embedding: List[float], top_k: int = 5) -> List[Tuple[Document, float]]:
        """Search for most similar documents by cosine similarity."""
        if not self._documents or not query_embedding:
            return []

        scored: List[Tuple[Document, float]] = []
        for doc in self._documents:
            if not doc.embedding:
                continue
            sim = _cosine_similarity(query_embedding, doc.embedding)
            scored.append((doc, sim))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def clear(self) -> None:
        """Remove all documents."""
        self._documents.clear()

    def get_by_metadata(self, key: str, value: str) -> List[Document]:
        """Retrieve documents by metadata key-value pair."""
        return [d for d in self._documents if d.metadata.get(key) == value]


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
