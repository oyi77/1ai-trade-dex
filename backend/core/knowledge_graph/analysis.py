from __future__ import annotations

import json
from typing import Any

from sqlalchemy import and_
from sqlalchemy.orm import Session

from backend.models.database import KgNode, KgEdge, EvolutionLog


def _query_best_genes_volatile_regime(
    db: Session, params: dict[str, Any]
) -> list[dict[str, Any]]:
    """Find genes performing best during volatile regimes on crypto markets."""
    volatile_strategies = (
        db.query(KgNode)
        .filter(
            and_(
                KgNode.node_type == "strategy",
                KgNode.properties_json.like('%"regime":"volatile"%'),
            )
        )
        .all()
    )

    result = []
    for strategy in volatile_strategies:
        genes = (
            db.query(KgNode)
            .join(KgEdge, KgEdge.to_node_id == KgNode.node_id)
            .filter(
                and_(
                    KgEdge.from_node_id == strategy.node_id,
                    KgEdge.relationship == "HAS_GENE",
                    KgNode.node_type == "gene",
                )
            )
            .all()
        )

        for gene in genes:
            props = json.loads(gene.properties_json) if gene.properties_json else {}
            result.append(
                {
                    "strategy": strategy.label,
                    "gene": gene.label,
                    "gene_type": props.get("gene_type", "unknown"),
                }
            )
    return result


def _query_martingale_lifespan(
    db: Session, params: dict[str, Any]
) -> list[dict[str, Any]]:
    """Calculate average lifespan of strategies with martingale risk_chromosome."""
    martingale_strategies = (
        db.query(KgNode)
        .filter(
            and_(
                KgNode.node_type == "strategy",
                KgNode.properties_json.like('%"risk_chromosome":"martingale"%'),
            )
        )
        .all()
    )

    if not martingale_strategies:
        return [{"average_lifespan_days": 0, "count": 0}]

    genome_ids = [s.label for s in martingale_strategies]
    logs = (
        db.query(EvolutionLog)
        .filter(
            and_(
                EvolutionLog.genome_id.in_(genome_ids),
                EvolutionLog.event_type.in_(["promotion", "auto_killed", "retired"]),
            )
        )
        .order_by(EvolutionLog.genome_id, EvolutionLog.timestamp.asc())
        .all()
    )

    lifespans: list[float] = []
    current_genome = None
    created_at = None
    for log in logs:
        if log.genome_id != current_genome:
            if created_at is not None:
                lifespans.append(0)
            current_genome = log.genome_id
            created_at = (
                log.timestamp
                if log.event_type == "promotion" and log.from_stage == "DRAFT"
                else None
            )
        if created_at and log.event_type in ("auto_killed", "retired"):
            days = (log.timestamp - created_at).total_seconds() / 86400
            lifespans.append(max(0.0, days))
            created_at = None

    avg_lifespan = sum(lifespans) / len(lifespans) if lifespans else 0
    return [
        {
            "average_lifespan_days": round(avg_lifespan, 1),
            "count": len(martingale_strategies),
        }
    ]


def _query_highest_alpha_by_category(
    db: Session, params: dict[str, Any]
) -> list[dict[str, Any]]:
    """Find which market categories show highest alpha for statistical_arb genomes."""
    stat_arb_strategies = (
        db.query(KgNode)
        .filter(
            and_(
                KgNode.node_type == "strategy",
                KgNode.label.like("%statistical_arb%"),
            )
        )
        .all()
    )

    result = []
    for strategy in stat_arb_strategies:
        markets = (
            db.query(KgNode)
            .join(KgEdge, KgEdge.to_node_id == KgNode.node_id)
            .filter(
                and_(
                    KgEdge.from_node_id == strategy.node_id,
                    KgEdge.relationship == "TRADED_ON",
                    KgNode.node_type == "market",
                )
            )
            .all()
        )

        props = json.loads(strategy.properties_json) if strategy.properties_json else {}
        for market in markets:
            result.append(
                {
                    "strategy": strategy.label,
                    "market": market.label,
                    "alpha": props.get("alpha", 0.0),
                }
            )

    result.sort(key=lambda x: x["alpha"], reverse=True)
    return result


def _query_legend_mutation_path(
    db: Session, params: dict[str, Any]
) -> list[dict[str, Any]]:
    """Find what mutation sequence produced the most LEGEND strategies."""
    legend_strategies = (
        db.query(KgNode)
        .filter(
            and_(
                KgNode.node_type == "strategy",
                KgNode.properties_json.like('%"stage":"LEGEND"%'),
            )
        )
        .all()
    )

    result = []
    for strategy in legend_strategies:
        mutations = (
            db.query(KgEdge)
            .filter(
                and_(
                    KgEdge.to_node_id == strategy.node_id,
                    KgEdge.relationship == "MUTATED_FROM",
                )
            )
            .all()
        )

        for mutation in mutations:
            parent = (
                db.query(KgNode).filter(KgNode.node_id == mutation.from_node_id).first()
            )
            if parent:
                result.append(
                    {
                        "legend_strategy": strategy.label,
                        "mutated_from": parent.label,
                        "mutation_weight": mutation.weight,
                    }
                )

    result.sort(key=lambda x: x["mutation_weight"], reverse=True)
    return result


_GRAPH_QUERIES = {
    "best_genes_volatile_regime": _query_best_genes_volatile_regime,
    "martingale_lifespan": _query_martingale_lifespan,
    "highest_alpha_by_category": _query_highest_alpha_by_category,
    "legend_mutation_path": _query_legend_mutation_path,
}
