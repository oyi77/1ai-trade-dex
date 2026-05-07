"""Knowledge Graph API router.

Wave 10: Knowledge Graph (Part 10) — Provides /api/agi/knowledge-graph/query endpoint.
"""

import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from backend.models.database import get_db
from backend.application.agi.knowledge_graph import KnowledgeGraph


kg_router = APIRouter(prefix="/api/agi/knowledge-graph", tags=["agi"])


@kg_router.get("/query")
async def query_knowledge_graph(
    query_name: str,
    params: Optional[str] = None,  # JSON-encoded params
    db: Session = Depends(get_db),
) -> dict:
    """Run a pre-built graph query.

    Available queries:
    - best_genes_volatile_regime: Genes performing best during volatile regimes
    - martingale_lifespan: Average lifespan of martingale strategies
    - highest_alpha_by_category: Market categories with highest alpha
    - legend_mutation_path: Mutation paths that produced LEGEND strategies
    """
    kg = KnowledgeGraph()

    try:
        # Parse params if provided
        params_dict = json.loads(params) if params else {}

        # Execute query
        result = kg.query_graph(query_name, params_dict, db)

        return {
            "success": True,
            "query": query_name,
            "result": result,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query execution failed: {e}")


@kg_router.get("/nodes/{node_id}/neighbors")
async def get_node_neighbors(
    node_id: str,
    relationship: Optional[str] = None,
    direction: str = "outgoing",
    db: Session = Depends(get_db),
) -> dict:
    """Get neighbors of a node in the knowledge graph."""
    if direction not in ["outgoing", "incoming"]:
        raise HTTPException(status_code=400, detail="direction must be 'outgoing' or 'incoming'")

    kg = KnowledgeGraph()
    neighbors = kg.query_neighbors(node_id, relationship, direction, db)

    return {
        "success": True,
        "node_id": node_id,
        "relationship": relationship,
        "direction": direction,
        "neighbors": [
            {
                "node_id": n.node_id,
                "node_type": n.node_type,
                "label": n.label,
                "properties": json.loads(n.properties_json) if n.properties_json else {}
            }
            for n in neighbors
        ],
    }


@kg_router.post("/nodes")
async def create_node(
    node_type: str,
    label: str,
    properties: Optional[dict] = None,
    db: Session = Depends(get_db),
) -> dict:
    """Create a new node in the knowledge graph."""
    kg = KnowledgeGraph()
    node = kg.add_node(None, node_type, label, properties, db)

    return {
        "success": True,
        "node_id": node.node_id,
        "node_type": node.node_type,
        "label": node.label,
    }


@kg_router.post("/edges")
async def create_edge(
    from_id: str,
    to_id: str,
    relationship: str,
    weight: float = 1.0,
    properties: Optional[dict] = None,
    db: Session = Depends(get_db),
) -> dict:
    """Create a new edge in the knowledge graph."""
    kg = KnowledgeGraph()
    edge = kg.add_edge(from_id, to_id, relationship, weight, properties, db)

    return {
        "success": True,
        "edge_id": edge.edge_id,
        "from_node_id": edge.from_node_id,
        "to_node_id": edge.to_node_id,
        "relationship": edge.relationship,
    }
