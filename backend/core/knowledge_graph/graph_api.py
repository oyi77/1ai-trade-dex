from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.models.database import KgNode, KgEdge
from .analysis import _GRAPH_QUERIES


class KnowledgeGraphGraphMixin:
    """Node/Edge API mixin for KnowledgeGraph (KgNode/KgEdge tables)."""

    def add_node(
        self,
        node_id: str,
        node_type: str,
        label: str,
        properties: dict[str, Any] | None = None,
    ) -> KgNode:
        """Add a node to the knowledge graph (KgNode table)."""
        node = KgNode(
            node_id=node_id or str(uuid.uuid4()),
            node_type=node_type,
            label=label,
            properties_json=json.dumps(properties) if properties else None,
            created_at=datetime.now(timezone.utc),
        )
        self._session.merge(node)
        self._session.commit()
        return node

    def add_edge(
        self,
        from_id: str,
        to_id: str,
        relationship: str,
        weight: float = 1.0,
        properties: dict[str, Any] | None = None,
    ) -> KgEdge:
        """Add an edge between two KgNode entries."""
        edge = KgEdge(
            edge_id=str(uuid.uuid4()),
            from_node_id=from_id,
            to_node_id=to_id,
            relationship=relationship,
            weight=weight,
            properties_json=json.dumps(properties) if properties else None,
            created_at=datetime.now(timezone.utc),
        )
        self._session.add(edge)
        self._session.commit()
        return edge

    def query_neighbors(
        self, node_id: str, relationship: str | None = None, direction: str = "outgoing"
    ) -> list[KgNode]:
        """Query neighbors of a KgNode."""
        if direction == "outgoing":
            q = self._session.query(KgEdge).filter(KgEdge.from_node_id == node_id)
        else:
            q = self._session.query(KgEdge).filter(KgEdge.to_node_id == node_id)
        if relationship:
            q = q.filter(KgEdge.relationship == relationship)
        edges = q.all()

        if direction == "outgoing":
            neighbor_ids = [e.to_node_id for e in edges]
        else:
            neighbor_ids = [e.from_node_id for e in edges]

        if not neighbor_ids:
            return []
        return (
            self._session.query(KgNode).filter(KgNode.node_id.in_(neighbor_ids)).all()
        )

    def query_graph(
        self, query_name: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Run a pre-built named graph query."""
        query_func = _GRAPH_QUERIES.get(query_name)
        if query_func is None:
            raise ValueError(f"Unknown query: {query_name}")
        return query_func(self._session, params or {})
