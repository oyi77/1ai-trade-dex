from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.core.agi_types import (
    KGEntity as KGEntityType,
    MarketRegime,
)
from loguru import logger
from backend.models.kg_models import (
    KGEntity as KGEntityModel,
    KGRelation as KGRelationModel,
)


class KnowledgeGraphQueryMixin:
    """Strategy query methods mixin for KnowledgeGraph."""

    def get_strategies_for_regime(self, regime: MarketRegime) -> list[KGEntityType]:
        regime_entity = (
            self._session.query(KGEntityModel)
            .filter(
                KGEntityModel.entity_type == "regime",
                KGEntityModel.entity_id.ilike(f"%{regime.value}%"),
            )
            .first()
        )
        if regime_entity is None:
            return []
        relations = (
            self._session.query(KGRelationModel)
            .filter(
                KGRelationModel.to_entity_id == regime_entity.id,
                KGRelationModel.relation_type == "performs_well_in",
            )
            .all()
        )

        # ⚡ Bolt Optimization: Replace N+1 queries with bulk fetch
        strategy_ids = [rel.from_entity_id for rel in relations]
        if not strategy_ids:
            return []

        strategies = (
            self._session.query(KGEntityModel)
            .filter(KGEntityModel.id.in_(strategy_ids))
            .all()
        )
        strategy_dict = {strat.id: strat for strat in strategies}

        results = []
        for rel in relations:
            strategy = strategy_dict.get(rel.from_entity_id)
            if strategy:
                results.append(
                    KGEntityType(
                        entity_type=strategy.entity_type,
                        entity_id=strategy.entity_id,
                        properties=strategy.properties or {},
                    )
                )
        return results

    def get_regime_performance(self, strategy: str) -> dict[str, dict[str, Any]]:
        strategy_entity = (
            self._session.query(KGEntityModel)
            .filter(
                KGEntityModel.entity_id == strategy,
            )
            .first()
        )
        if strategy_entity is None:
            return {}
        relations = (
            self._session.query(KGRelationModel)
            .filter(
                KGRelationModel.from_entity_id == strategy_entity.id,
            )
            .all()
        )

        # ⚡ Bolt Optimization: Replace N+1 queries with bulk fetch
        regime_ids = [rel.to_entity_id for rel in relations]
        if not regime_ids:
            return {}

        regimes = (
            self._session.query(KGEntityModel)
            .filter(KGEntityModel.id.in_(regime_ids))
            .all()
        )
        regime_dict = {r.id: r for r in regimes}

        performance = {}
        for rel in relations:
            regime = regime_dict.get(rel.to_entity_id)
            if regime and regime.entity_type == "regime":
                performance[regime.entity_id] = {
                    "weight": rel.weight,
                    "confidence": rel.confidence,
                    "relation_type": rel.relation_type,
                }
        return performance

    def query_regime_performance(
        self, strategy: str, db: Optional[Session] = None
    ) -> dict[MarketRegime, dict[str, Any]]:
        session = db or self._session
        strategy_model = (
            session.query(KGEntityModel)
            .filter(KGEntityModel.entity_id == strategy)
            .first()
        )
        if not strategy_model:
            return {}
        relations = (
            session.query(KGRelationModel)
            .filter(KGRelationModel.from_entity_id == strategy_model.id)
            .all()
        )

        # ⚡ Bolt Optimization: Replace N+1 queries with bulk fetch
        regime_ids = [rel.to_entity_id for rel in relations]
        if not regime_ids:
            return {}

        regimes = (
            session.query(KGEntityModel).filter(KGEntityModel.id.in_(regime_ids)).all()
        )
        regime_dict = {r.id: r for r in regimes}

        result = {}
        for rel in relations:
            regime_model = regime_dict.get(rel.to_entity_id)
            if regime_model and regime_model.entity_type == "regime":
                try:
                    regime = MarketRegime(regime_model.entity_id)
                    result[regime] = {
                        "weight": rel.weight,
                        "confidence": rel.confidence,
                        "relation_type": rel.relation_type,
                    }
                except ValueError:
                    logger.debug("knowledge_graph: failed to parse regime relationship")
        return result

    def query_best_strategies(
        self, regime: MarketRegime, db: Optional[Session] = None, limit: int = 10
    ) -> list[KGEntityType]:
        session = db or self._session
        regime_id = regime.value if isinstance(regime, MarketRegime) else str(regime)
        regime_model = (
            session.query(KGEntityModel)
            .filter(
                KGEntityModel.entity_type == "regime",
                KGEntityModel.entity_id == regime_id,
            )
            .first()
        )
        if not regime_model:
            return []
        relations = (
            session.query(KGRelationModel)
            .filter(
                KGRelationModel.to_entity_id == regime_model.id,
                KGRelationModel.relation_type == "performs_well_in",
            )
            .order_by(KGRelationModel.weight.desc())
            .limit(limit)
            .all()
        )

        # ⚡ Bolt Optimization: Replace N+1 queries with bulk fetch
        strategy_ids = [rel.from_entity_id for rel in relations]
        if not strategy_ids:
            return []

        strategies = (
            session.query(KGEntityModel)
            .filter(KGEntityModel.id.in_(strategy_ids))
            .all()
        )
        strategy_dict = {strat.id: strat for strat in strategies}

        results = []
        for rel in relations:
            strategy_model = strategy_dict.get(rel.from_entity_id)
            if strategy_model:
                results.append(
                    KGEntityType(
                        entity_type=strategy_model.entity_type,
                        entity_id=strategy_model.entity_id,
                        properties=strategy_model.properties or {},
                    )
                )
        return results

    def store_trade_memory(
        self,
        trade_id,
        strategy,
        market_id,
        signal_reasoning,
        outcome_pnl,
        outcome_correct,
    ):
        try:
            trade_entity_id = f"trade:{trade_id}"
            self.add_entity(
                "trade_memory",
                trade_entity_id,
                {
                    "trade_id": trade_id,
                    "strategy": strategy,
                    "market_id": str(market_id),
                    "reasoning": str(signal_reasoning)[:500],
                    "pnl": float(outcome_pnl or 0),
                    "correct": bool(outcome_correct),
                },
            )
            self.add_relation(
                trade_entity_id,
                f"strategy:{strategy}",
                "executed_by",
                weight=1.0,
                confidence=1.0,
            )
        except Exception as e:
            logger.error(f"store_trade_memory failed for trade {trade_id}: {e}")

    def query_by_type(self, entity_type: str, limit: int = 50) -> list[KGEntityType]:
        """Return all entities of a given type, most recently created first."""
        try:
            rows = (
                self._session.query(KGEntityModel)
                .filter(KGEntityModel.entity_type == entity_type)
                .order_by(KGEntityModel.created_at.desc())
                .limit(limit)
                .all()
            )
            return [
                KGEntityType(
                    entity_type=r.entity_type,
                    entity_id=r.entity_id,
                    properties=r.properties or {},
                )
                for r in rows
            ]
        except Exception as e:
            logger.error("query_by_type failed for type '%s': %s", entity_type, e)
            return []

    def query_relations(
        self,
        from_entity_id: str,
        relation_type: str | None = None,
        limit: int = 20,
    ) -> list[KGEntityType]:
        """Return entities related to *from_entity_id*, optionally filtered by relation_type."""
        try:
            from_model = (
                self._session.query(KGEntityModel)
                .filter(KGEntityModel.entity_id == from_entity_id)
                .first()
            )
            if not from_model:
                return []

            q = self._session.query(KGRelationModel).filter(
                KGRelationModel.from_entity_id == from_model.id
            )
            if relation_type:
                q = q.filter(KGRelationModel.relation_type == relation_type)
            relations = q.order_by(KGRelationModel.weight.desc()).limit(limit).all()

            to_ids = [r.to_entity_id for r in relations]
            if not to_ids:
                return []

            entities = (
                self._session.query(KGEntityModel)
                .filter(KGEntityModel.id.in_(to_ids))
                .all()
            )
            entity_map = {e.id: e for e in entities}
            return [
                KGEntityType(
                    entity_type=entity_map[r.to_entity_id].entity_type,
                    entity_id=entity_map[r.to_entity_id].entity_id,
                    properties=entity_map[r.to_entity_id].properties or {},
                )
                for r in relations
                if r.to_entity_id in entity_map
            ]
        except Exception as e:
            logger.error(
                "query_relations failed for entity '%s': %s", from_entity_id, e
            )
            return []

    def retrieve_similar_trades(
        self, strategy: str, market_context: str = "", limit: int = 5
    ) -> list:
        try:
            from backend.models.kg_models import KGEntity

            entities = (
                self._session.query(KGEntity)
                .filter(KGEntity.entity_type == "trade_memory")
                .order_by(KGEntity.created_at.desc())
                .limit(limit * 3)
                .all()
            )
            results = []
            for e in entities:
                props = e.properties or {}
                if props.get("strategy") == strategy:
                    results.append(props)
                    if len(results) >= limit:
                        break
            return results
        except Exception as e:
            logger.error(f"retrieve_similar_trades failed for strategy {strategy}: {e}")
            return []
