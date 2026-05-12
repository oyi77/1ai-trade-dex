"""Knowledge Graph operations for Wave 10.

Knowledge Graph (Part 10) — Provides graph operations for querying strategy evolution,
gene performance, and market relationships.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy import and_

from backend.models.database import KgNode, KgEdge, EvolutionLog


class KnowledgeGraph:
    """Knowledge Graph operations for strategy evolution analysis."""

    def add_node(self, node_id: str, node_type: str, label: str,
                 properties: Dict[str, Any] = None, db: Session = None) -> KgNode:
        """Add a node to the knowledge graph."""
        from backend.db.utils import get_db_session
        with get_db_session() as db:
            node = KgNode(
                node_id=node_id or str(uuid.uuid4()),
                node_type=node_type,
                label=label,
                properties_json=json.dumps(properties) if properties else None,
                created_at=datetime.now(timezone.utc)
            )
            db.add(node)
            db.commit()
            return node

    def add_edge(self, from_id: str, to_id: str, relationship: str,
                 weight: float = 1.0, properties: Dict[str, Any] = None,
                 db: Session = None) -> KgEdge:
        """Add an edge between two nodes in the knowledge graph."""
        from backend.db.utils import get_db_session
        with get_db_session() as db:
            edge = KgEdge(
                edge_id=str(uuid.uuid4()),
                from_node_id=from_id,
                to_node_id=to_id,
                relationship=relationship,
                weight=weight,
                properties_json=json.dumps(properties) if properties else None,
                created_at=datetime.now(timezone.utc)
            )
            db.add(edge)
            db.commit()
            return edge

    def query_neighbors(self, node_id: str, relationship: str = None,
                        direction: str = "outgoing", db: Session = None) -> List[KgNode]:
        """Query neighbors of a node."""
        from backend.db.utils import get_db_session
        with get_db_session() as db:
            if direction == "outgoing":
                query = db.query(KgEdge).filter(KgEdge.from_node_id == node_id)
                if relationship:
                    query = query.filter(KgEdge.relationship == relationship)
                edges = query.all()
                node_ids = [edge.to_node_id for edge in edges]
            else:  # incoming
                query = db.query(KgEdge).filter(KgEdge.to_node_id == node_id)
                if relationship:
                    query = query.filter(KgEdge.relationship == relationship)
                edges = query.all()
                node_ids = [edge.from_node_id for edge in edges]

            if not node_ids:
                return []

            nodes = db.query(KgNode).filter(KgNode.node_id.in_(node_ids)).all()
            return nodes

    def query_graph(self, query_name: str, params: Dict[str, Any] = None,
                   db: Session = None) -> List[Dict[str, Any]]:
        """Run a pre-built graph query."""
        from backend.db.utils import get_db_session
        with get_db_session() as db:
            query_func = GRAPH_QUERIES.get(query_name)
            if query_func is None:
                raise ValueError(f"Unknown query: {query_name}")

            return query_func(db, params or {})


# Pre-built graph queries

def _query_best_genes_volatile_regime(db: Session, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Find genes performing best during volatile regimes on crypto markets."""
    # Find strategies that performed well in volatile regimes
    volatile_strategies = db.query(KgNode).filter(
        and_(
            KgNode.node_type == "strategy",
            KgNode.properties_json.like('%"regime":"volatile"%')
        )
    ).all()

    result = []
    for strategy in volatile_strategies:
        # Find genes associated with this strategy
        genes = db.query(KgNode).join(
            KgEdge, KgEdge.to_node_id == KgNode.node_id
        ).filter(
            and_(
                KgEdge.from_node_id == strategy.node_id,
                KgEdge.relationship == "HAS_GENE",
                KgNode.node_type == "gene"
            )
        ).all()

        for gene in genes:
            result.append({
                "strategy": strategy.label,
                "gene": gene.label,
                "gene_type": gene.properties_json.get("gene_type", "unknown") if gene.properties_json else "unknown"
            })

    return result


def _query_martingale_lifespan(db: Session, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Calculate average lifespan of strategies with martingale risk_chromosome."""
    # Find strategies with martingale gene
    martingale_strategies = db.query(KgNode).filter(
        and_(
            KgNode.node_type == "strategy",
            KgNode.properties_json.like('%"risk_chromosome":"martingale"%')
        )
    ).all()

    if not martingale_strategies:
        return [{"average_lifespan_days": 0, "count": 0}]

    genome_ids = [s.label for s in martingale_strategies]

    logs = db.query(EvolutionLog).filter(
        and_(
            EvolutionLog.genome_id.in_(genome_ids),
            EvolutionLog.event_type.in_(["promotion", "auto_killed", "retired"])
        )
    ).order_by(EvolutionLog.genome_id, EvolutionLog.timestamp.asc()).all()

    lifespans = []
    current_genome = None
    created_at = None
    for log in logs:
        if log.genome_id != current_genome:
            if created_at is not None:
                lifespans.append(0)
            current_genome = log.genome_id
            created_at = log.timestamp if log.event_type == "promotion" and log.from_stage == "DRAFT" else None
        if created_at and log.event_type in ("auto_killed", "retired"):
            days = (log.timestamp - created_at).total_seconds() / 86400
            lifespans.append(max(0, days))
            created_at = None

    avg_lifespan = sum(lifespans) / len(lifespans) if lifespans else 0
    return [{"average_lifespan_days": round(avg_lifespan, 1), "count": len(martingale_strategies)}]


def _query_highest_alpha_by_category(db: Session, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Find which market categories show highest alpha for statistical_arb genomes."""
    # Find statistical_arb strategies
    stat_arb_strategies = db.query(KgNode).filter(
        and_(
            KgNode.node_type == "strategy",
            KgNode.label.like('%statistical_arb%')
        )
    ).all()

    result = []
    for strategy in stat_arb_strategies:
        # Find markets this strategy traded on
        markets = db.query(KgNode).join(
            KgEdge, KgEdge.to_node_id == KgNode.node_id
        ).filter(
            and_(
                KgEdge.from_node_id == strategy.node_id,
                KgEdge.relationship == "TRADED_ON",
                KgNode.node_type == "market"
            )
        ).all()

        for market in markets:
            result.append({
                "strategy": strategy.label,
                "market": market.label,
                "alpha": strategy.properties_json.get("alpha", 0.0) if strategy.properties_json else 0.0
            })

    # Sort by alpha descending
    result.sort(key=lambda x: x["alpha"], reverse=True)
    return result


def _query_legend_mutation_path(db: Session, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Find what mutation sequence produced the most LEGEND strategies."""
    # Find LEGEND strategies
    legend_strategies = db.query(KgNode).filter(
        and_(
            KgNode.node_type == "strategy",
            KgNode.properties_json.like('%"stage":"LEGEND"%')
        )
    ).all()

    result = []
    for strategy in legend_strategies:
        # Find mutation paths
        mutations = db.query(KgEdge).filter(
            and_(
                KgEdge.to_node_id == strategy.node_id,
                KgEdge.relationship == "MUTATED_FROM"
            )
        ).all()

        for mutation in mutations:
            # Get parent strategy
            parent = db.query(KgNode).filter(KgNode.node_id == mutation.from_node_id).first()
            if parent:
                result.append({
                    "legend_strategy": strategy.label,
                    "mutated_from": parent.label,
                    "mutation_weight": mutation.weight
                })

    # Sort by mutation weight descending
    result.sort(key=lambda x: x["mutation_weight"], reverse=True)
    return result


# Query registry
GRAPH_QUERIES = {
    "best_genes_volatile_regime": _query_best_genes_volatile_regime,
    "martingale_lifespan": _query_martingale_lifespan,
    "highest_alpha_by_category": _query_highest_alpha_by_category,
    "legend_mutation_path": _query_legend_mutation_path,
}
