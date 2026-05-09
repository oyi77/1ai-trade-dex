from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from backend.core.agi_types import KGEntity as KGEntityType, KGRelation as KGRelationType, MarketRegime
from backend.models.kg_models import (
    KGEntity as KGEntityModel,
    KGRelation as KGRelationModel,
    DecisionAuditLog,
)


class KnowledgeGraph:
    def __init__(self, session: Optional[Session] = None, db_url: str = "sqlite:///:memory:"):
        if session is not None:
            self._session = session
            self._owns_session = False
        else:
            from backend.models.database import Base
            self._engine = create_engine(db_url)
            Base.metadata.create_all(self._engine)
            self._session = sessionmaker(bind=self._engine)()
            self._owns_session = True

    def close(self):
        if self._owns_session:
            self._session.close()

    def add_entity(self, entity_type: str, entity_id: str, properties: dict[str, Any] | None = None) -> KGEntityType:
        existing = self._session.query(KGEntityModel).filter(KGEntityModel.entity_id == entity_id).first()
        if existing:
            if properties:
                existing.properties = properties
                existing.updated_at = datetime.now(timezone.utc)
            self._session.commit()
            return KGEntityType(
                entity_type=existing.entity_type,
                entity_id=existing.entity_id,
                properties=existing.properties or {},
            )
        model = KGEntityModel(
            entity_type=entity_type,
            entity_id=entity_id,
            properties=properties or {},
        )
        self._session.add(model)
        self._session.commit()
        return KGEntityType(
            entity_type=model.entity_type,
            entity_id=model.entity_id,
            properties=model.properties or {},
        )

    def get_entity(self, entity_id: str) -> KGEntityType | None:
        model = self._session.query(KGEntityModel).filter(KGEntityModel.entity_id == entity_id).first()
        if model is None:
            return None
        return KGEntityType(
            entity_type=model.entity_type,
            entity_id=model.entity_id,
            properties=model.properties or {},
        )

    def add_relation(
        self,
        from_entity_id: str,
        to_entity_id: str,
        relation_type: str,
        weight: float,
        confidence: float,
    ) -> KGRelationType | None:
        from_model = self._session.query(KGEntityModel).filter(KGEntityModel.entity_id == from_entity_id).first()
        to_model = self._session.query(KGEntityModel).filter(KGEntityModel.entity_id == to_entity_id).first()
        if from_model is None or to_model is None:
            return None
        model = KGRelationModel(
            from_entity_id=from_model.id,
            to_entity_id=to_model.id,
            relation_type=relation_type,
            weight=weight,
            confidence=confidence,
        )
        self._session.add(model)
        self._session.commit()
        return KGRelationType(
            from_entity=from_entity_id,
            to_entity=to_entity_id,
            relation_type=relation_type,
            weight=weight,
            confidence=confidence,
            timestamp=model.created_at,
        )

    def get_related(self, entity_id: str, relation_type: str | None = None) -> list[KGEntityType]:
        entity_model = self._session.query(KGEntityModel).filter(KGEntityModel.entity_id == entity_id).first()
        if entity_model is None:
            return []
        query = self._session.query(KGRelationModel).filter(KGRelationModel.from_entity_id == entity_model.id)
        if relation_type:
            query = query.filter(KGRelationModel.relation_type == relation_type)
        relations = query.all()

        to_entity_ids = [rel.to_entity_id for rel in relations]
        if not to_entity_ids:
            return []

        related_entities = self._session.query(KGEntityModel).filter(KGEntityModel.id.in_(to_entity_ids)).all()
        related_dict = {entity.id: entity for entity in related_entities}

        results = []
        for rel in relations:
            related = related_dict.get(rel.to_entity_id)
            if related:
                results.append(KGEntityType(
                    entity_type=related.entity_type,
                    entity_id=related.entity_id,
                    properties=related.properties or {},
                ))
        return results

    def find_pattern(self, pattern: str) -> list[KGEntityType]:
        parts = pattern.split("_")
        if len(parts) < 2:
            return []
        relation_type = "_".join(parts[:-1]) if len(parts) > 2 else parts[0]
        target_name = parts[-1]
        target = self._session.query(KGEntityModel).filter(
            KGEntityModel.entity_id.ilike(f"%{target_name}%")
        ).first()
        if target is None:
            return []
        relations = self._session.query(KGRelationModel).filter(
            KGRelationModel.to_entity_id == target.id,
            KGRelationModel.relation_type == relation_type,
        ).all()

        # ⚡ Bolt Optimization: Replace N+1 queries with bulk fetch
        source_entity_ids = [rel.from_entity_id for rel in relations]
        if not source_entity_ids:
            return []

        sources = self._session.query(KGEntityModel).filter(KGEntityModel.id.in_(source_entity_ids)).all()
        source_dict = {source.id: source for source in sources}

        results = []
        for rel in relations:
            source = source_dict.get(rel.from_entity_id)
            if source:
                results.append(KGEntityType(
                    entity_type=source.entity_type,
                    entity_id=source.entity_id,
                    properties=source.properties or {},
                ))
        return results

    def get_strategies_for_regime(self, regime: MarketRegime) -> list[KGEntityType]:
        regime_entity = self._session.query(KGEntityModel).filter(
            KGEntityModel.entity_type == "regime",
            KGEntityModel.entity_id.ilike(f"%{regime.value}%"),
        ).first()
        if regime_entity is None:
            return []
        relations = self._session.query(KGRelationModel).filter(
            KGRelationModel.to_entity_id == regime_entity.id,
            KGRelationModel.relation_type == "performs_well_in",
        ).all()

        # ⚡ Bolt Optimization: Replace N+1 queries with bulk fetch
        strategy_ids = [rel.from_entity_id for rel in relations]
        if not strategy_ids:
            return []

        strategies = self._session.query(KGEntityModel).filter(KGEntityModel.id.in_(strategy_ids)).all()
        strategy_dict = {strat.id: strat for strat in strategies}

        results = []
        for rel in relations:
            strategy = strategy_dict.get(rel.from_entity_id)
            if strategy:
                results.append(KGEntityType(
                    entity_type=strategy.entity_type,
                    entity_id=strategy.entity_id,
                    properties=strategy.properties or {},
                ))
        return results

    def get_regime_performance(self, strategy: str) -> dict[str, dict[str, Any]]:
        strategy_entity = self._session.query(KGEntityModel).filter(
            KGEntityModel.entity_id == strategy,
        ).first()
        if strategy_entity is None:
            return {}
        relations = self._session.query(KGRelationModel).filter(
            KGRelationModel.from_entity_id == strategy_entity.id,
        ).all()

        # ⚡ Bolt Optimization: Replace N+1 queries with bulk fetch
        regime_ids = [rel.to_entity_id for rel in relations]
        if not regime_ids:
            return {}

        regimes = self._session.query(KGEntityModel).filter(KGEntityModel.id.in_(regime_ids)).all()
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

    def rollback_to(self, timestamp: datetime) -> int:
        relations_deleted = self._session.query(KGRelationModel).filter(
            KGRelationModel.created_at > timestamp,
        ).delete()
        entities_deleted = self._session.query(KGEntityModel).filter(
            KGEntityModel.created_at > timestamp,
        ).delete()
        self._session.commit()
        return relations_deleted + entities_deleted

    def validate_entity(self, entity_type: str, entity_id: str, properties: dict[str, Any] | None = None) -> list[str]:
        errors = []
        if not entity_type or not entity_type.strip():
            errors.append("entity_type is required")
        if not entity_id or not entity_id.strip():
            errors.append("entity_id is required")
        if properties is not None and not isinstance(properties, dict):
            errors.append("properties must be a dict")
        return errors

    def validate_relation(
        self,
        from_entity_id: str,
        to_entity_id: str,
        relation_type: str,
        weight: float,
        confidence: float,
    ) -> list[str]:
        errors = []
        if not from_entity_id or not from_entity_id.strip():
            errors.append("from_entity_id is required")
        if not to_entity_id or not to_entity_id.strip():
            errors.append("to_entity_id is required")
        if not relation_type or not relation_type.strip():
            errors.append("relation_type is required")
        if not (0.0 <= weight <= 1.0):
            errors.append("weight must be between 0 and 1")
        if not (0.0 <= confidence <= 1.0):
            errors.append("confidence must be between 0 and 1")
        if confidence < 0.1:
            errors.append("confidence must be >= 0.1 (minimum evidence threshold)")
        if from_entity_id == to_entity_id:
            errors.append("self-loops are not allowed (from_entity == to_entity)")
        from_exists = self._session.query(KGEntityModel).filter(KGEntityModel.entity_id == from_entity_id).first()
        if not from_exists:
            errors.append(f"from_entity '{from_entity_id}' does not exist")
        to_exists = self._session.query(KGEntityModel).filter(KGEntityModel.entity_id == to_entity_id).first()
        if not to_exists:
            errors.append(f"to_entity '{to_entity_id}' does not exist")
        return errors

    def create_snapshot(self) -> str:
        snapshot_id = f"snap_{uuid.uuid4().hex[:16]}"
        entities = self._session.query(KGEntityModel).all()
        relations = self._session.query(KGRelationModel).all()
        entity_count = len(entities)
        relation_count = len(relations)
        snapshot_data = {
            "snapshot_id": snapshot_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "entity_count": entity_count,
            "relation_count": relation_count,
            "entities": [{"id": e.entity_id, "type": e.entity_type} for e in entities],
            "relations": [{"from": r.from_entity_id, "to": r.to_entity_id, "type": r.relation_type} for r in relations],
        }
        audit_entry = DecisionAuditLog(
            timestamp=datetime.now(timezone.utc),
            agent_name="KnowledgeGraph",
            decision_type="kg_snapshot",
            input_data={"snapshot_id": snapshot_id},
            output_data=snapshot_data,
            confidence=1.0,
            reasoning=f"Created snapshot with {entity_count} entities and {relation_count} relations",
        )
        self._session.add(audit_entry)
        self._session.commit()
        return snapshot_id

    def rollback_to_snapshot(self, snapshot_id: str) -> int:
        snapshot_entry = (
            self._session.query(DecisionAuditLog)
            .filter(
                DecisionAuditLog.decision_type == "kg_snapshot",
                DecisionAuditLog.input_data.contains({"snapshot_id": snapshot_id}),
            )
            .first()
        )
        if not snapshot_entry:
            return 0
        snapshot_time = snapshot_entry.timestamp
        if isinstance(snapshot_time, str):
            snapshot_time = datetime.fromisoformat(snapshot_time)
        relations_deleted = self._session.query(KGRelationModel).filter(
            KGRelationModel.created_at > snapshot_time
        ).delete()
        entities_deleted = self._session.query(KGEntityModel).filter(
            KGEntityModel.created_at > snapshot_time
        ).delete()
        rollback_audit = DecisionAuditLog(
            timestamp=datetime.now(timezone.utc),
            decision_type="kg_rollback",
            input_data={"snapshot_id": snapshot_id, "snapshot_time": snapshot_time.isoformat() if isinstance(snapshot_time, datetime) else snapshot_time},
            output_data={"relations_deleted": relations_deleted, "entities_deleted": entities_deleted},
            confidence=1.0,
            reasoning=f"Rolled back to snapshot {snapshot_id}",
        )
        self._session.add(rollback_audit)
        self._session.commit()
        return relations_deleted + entities_deleted

    def persist_entity(self, entity: KGEntityType, db: Optional[Session] = None) -> KGEntityType:
        session = db or self._session
        errors = self.validate_entity(entity.entity_type, entity.entity_id, entity.properties)
        if errors:
            raise ValueError(f"Entity validation failed: {errors}")
        existing = session.query(KGEntityModel).filter(KGEntityModel.entity_id == entity.entity_id).first()
        if existing:
            existing.properties = entity.properties
            existing.updated_at = datetime.now(timezone.utc)
        else:
            existing = KGEntityModel(
                entity_type=entity.entity_type,
                entity_id=entity.entity_id,
                properties=entity.properties or {},
            )
            session.add(existing)
        audit = DecisionAuditLog(
            timestamp=datetime.now(timezone.utc),
            agent_name="KnowledgeGraph",
            decision_type="kg_persist_entity",
            input_data={"entity_id": entity.entity_id, "entity_type": entity.entity_type},
            output_data={"status": "persisted"},
            confidence=1.0,
            reasoning=f"Persisted entity {entity.entity_id}",
        )
        session.add(audit)
        session.commit()
        return entity

    def persist_relation(self, relation: KGRelationType, db: Optional[Session] = None) -> KGRelationType:
        session = db or self._session
        errors = self.validate_relation(
            relation.from_entity, relation.to_entity, relation.relation_type, relation.weight, relation.confidence
        )
        if errors:
            raise ValueError(f"Relation validation failed: {errors}")
        from_model = session.query(KGEntityModel).filter(KGEntityModel.entity_id == relation.from_entity).first()
        to_model = session.query(KGEntityModel).filter(KGEntityModel.entity_id == relation.to_entity).first()
        if not from_model or not to_model:
            raise ValueError("From/to entities must exist before persisting relation")
        model = KGRelationModel(
            from_entity_id=from_model.id,
            to_entity_id=to_model.id,
            relation_type=relation.relation_type,
            weight=relation.weight,
            confidence=relation.confidence,
        )
        session.add(model)
        audit = DecisionAuditLog(
            timestamp=datetime.now(timezone.utc),
            agent_name="KnowledgeGraph",
            decision_type="kg_persist_relation",
            input_data={"from": relation.from_entity, "to": relation.to_entity, "type": relation.relation_type},
            output_data={"status": "persisted"},
            confidence=relation.confidence,
            reasoning=f"Persisted relation {relation.from_entity} -> {relation.to_entity}",
        )
        session.add(audit)
        session.commit()
        return relation

    def load_entity(self, entity_id: str, db: Optional[Session] = None) -> Optional[KGEntityType]:
        session = db or self._session
        model = session.query(KGEntityModel).filter(KGEntityModel.entity_id == entity_id).first()
        if not model:
            return None
        return KGEntityType(
            entity_type=model.entity_type,
            entity_id=model.entity_id,
            properties=model.properties or {},
        )

    def load_relations(
        self, entity_id: str, relation_type: Optional[str] = None, db: Optional[Session] = None
    ) -> list[KGRelationType]:
        session = db or self._session
        entity_model = session.query(KGEntityModel).filter(KGEntityModel.entity_id == entity_id).first()
        if not entity_model:
            return []
        query = session.query(KGRelationModel).filter(KGRelationModel.from_entity_id == entity_model.id)
        if relation_type:
            query = query.filter(KGRelationModel.relation_type == relation_type)
        relations = query.all()

        # ⚡ Bolt Optimization: Replace N+1 queries with bulk fetch
        to_entity_ids = [rel.to_entity_id for rel in relations]
        if not to_entity_ids:
            return []

        to_models = session.query(KGEntityModel).filter(KGEntityModel.id.in_(to_entity_ids)).all()
        to_model_dict = {model.id: model for model in to_models}

        results = []
        for rel in relations:
            to_model = to_model_dict.get(rel.to_entity_id)
            if to_model:
                results.append(KGRelationType(
                    from_entity=entity_id,
                    to_entity=to_model.entity_id,
                    relation_type=rel.relation_type,
                    weight=rel.weight,
                    confidence=rel.confidence,
                    timestamp=rel.created_at,
                ))
        return results

    def query_regime_performance(
        self, strategy: str, db: Optional[Session] = None
    ) -> dict[MarketRegime, dict[str, Any]]:
        session = db or self._session
        strategy_model = session.query(KGEntityModel).filter(KGEntityModel.entity_id == strategy).first()
        if not strategy_model:
            return {}
        relations = session.query(KGRelationModel).filter(
            KGRelationModel.from_entity_id == strategy_model.id
        ).all()

        # ⚡ Bolt Optimization: Replace N+1 queries with bulk fetch
        regime_ids = [rel.to_entity_id for rel in relations]
        if not regime_ids:
            return {}

        regimes = session.query(KGEntityModel).filter(KGEntityModel.id.in_(regime_ids)).all()
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
                    pass
        return result

    def query_best_strategies(
        self, regime: MarketRegime, db: Optional[Session] = None, limit: int = 10
    ) -> list[KGEntityType]:
        session = db or self._session
        regime_id = regime.value if isinstance(regime, MarketRegime) else str(regime)
        regime_model = session.query(KGEntityModel).filter(
            KGEntityModel.entity_type == "regime",
            KGEntityModel.entity_id == regime_id,
        ).first()
        if not regime_model:
            return []
        relations = session.query(KGRelationModel).filter(
            KGRelationModel.to_entity_id == regime_model.id,
            KGRelationModel.relation_type == "performs_well_in",
        ).order_by(KGRelationModel.weight.desc()).limit(limit).all()

        # ⚡ Bolt Optimization: Replace N+1 queries with bulk fetch
        strategy_ids = [rel.from_entity_id for rel in relations]
        if not strategy_ids:
            return []

        strategies = session.query(KGEntityModel).filter(KGEntityModel.id.in_(strategy_ids)).all()
        strategy_dict = {strat.id: strat for strat in strategies}

        results = []
        for rel in relations:
            strategy_model = strategy_dict.get(rel.from_entity_id)
            if strategy_model:
                results.append(KGEntityType(
                    entity_type=strategy_model.entity_type,
                    entity_id=strategy_model.entity_id,
                    properties=strategy_model.properties or {},
                ))
        return results

    def store_trade_memory(self, trade_id, strategy, market_id, signal_reasoning, outcome_pnl, outcome_correct):
        try:
            trade_entity_id = f"trade:{trade_id}"
            self.add_entity("trade_memory", trade_entity_id, {
                "trade_id": trade_id,
                "strategy": strategy,
                "market_id": str(market_id),
                "reasoning": str(signal_reasoning)[:500],
                "pnl": float(outcome_pnl or 0),
                "correct": bool(outcome_correct),
            })
            self.add_relation(trade_entity_id, f"strategy:{strategy}", "executed_by", weight=1.0, confidence=1.0)
        except Exception as e:
            import logging
            logging.getLogger("trading_bot.knowledge_graph").error(
                f"store_trade_memory failed for trade {trade_id}: {e}"
            )

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
            import logging
            logging.getLogger("trading_bot.knowledge_graph").error(
                "query_by_type failed for type '%s': %s", entity_type, e
            )
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
            import logging
            logging.getLogger("trading_bot.knowledge_graph").error(
                "query_relations failed for entity '%s': %s", from_entity_id, e
            )
            return []

    def retrieve_similar_trades(self, strategy: str, market_context: str = "", limit: int = 5) -> list:
        try:
            from backend.models.kg_models import KGEntity
            entities = self._session.query(KGEntity).filter(
                KGEntity.entity_type == "trade_memory"
            ).order_by(KGEntity.created_at.desc()).limit(limit * 3).all()
            results = []
            for e in entities:
                props = e.properties or {}
                if props.get("strategy") == strategy:
                    results.append(props)
                    if len(results) >= limit:
                        break
            return results
        except Exception as e:
            import logging
            logging.getLogger("trading_bot.knowledge_graph").error(
                f"retrieve_similar_trades failed for strategy {strategy}: {e}"
            )
            return []
