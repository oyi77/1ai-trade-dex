"""Knowledge Graph operations for Wave 10.

Thin wrapper delegating to ``backend.core.knowledge_graph.KnowledgeGraph``
for backward compatibility.  The canonical implementation lives in core.
"""

from typing import List, Dict, Any

from sqlalchemy.orm import Session

from backend.core.knowledge_graph import KnowledgeGraph as CoreKnowledgeGraph, _GRAPH_QUERIES


class KnowledgeGraph:
    """Backward-compatible wrapper around the core KnowledgeGraph.

    All node/edge operations and named queries are delegated to the core
    implementation which uses the ``kg_entities``/``kg_relations`` tables.
    """

    def __init__(self):
        self._core = CoreKnowledgeGraph()

    def add_node(self, node_id: str, node_type: str, label: str,
                 properties: Dict[str, Any] = None, db: Session = None):
        """Add a node (delegates to core)."""
        return self._core.add_node(node_id, node_type, label, properties)

    def add_edge(self, from_id: str, to_id: str, relationship: str,
                 weight: float = 1.0, properties: Dict[str, Any] = None,
                 db: Session = None):
        """Add an edge (delegates to core)."""
        return self._core.add_edge(from_id, to_id, relationship, weight, properties)

    def query_neighbors(self, node_id: str, relationship: str = None,
                        direction: str = "outgoing", db: Session = None):
        """Query neighbors (delegates to core)."""
        return self._core.query_neighbors(node_id, relationship, direction)

    def query_graph(self, query_name: str, params: Dict[str, Any] = None,
                    db: Session = None) -> List[Dict[str, Any]]:
        """Run a pre-built graph query (delegates to core)."""
        return self._core.query_graph(query_name, params)
