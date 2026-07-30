from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.core.agi_types import (
    KGEntity as KGEntityType,
    KGRelation as KGRelationType,
)
from loguru import logger
from backend.models.kg_models import (
    KGEntity as KGEntityModel,
    KGRelation as KGRelationModel,
    DecisionAuditLog,
)
from backend.db.utils import utcnow


class KnowledgeGraphEntityMixin:
    """Entity CRUD, validation, and persistence mixin for KnowledgeGraph."""

    def add_entity(
        self, entity_type: str, entity_id: str, properties: dict[str, Any] | None = None
    ) -> KGEntityType:
        existing = (
            self._session.query(KGEntityModel)
            .filter(KGEntityModel.entity_id == entity_id)
            .first()
        )
        if existing:
            if properties:
                existing.properties = properties
                existing.updated_at = utcnow()
            if self._autocommit:
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
        if self._autocommit:
            self._session.commit()
        return KGEntityType(
            entity_type=model.entity_type,
            entity_id=model.entity_id,
            properties=model.properties or {},
        )

    def get_entity(self, entity_id: str) -> KGEntityType | None:
        model = (
            self._session.query(KGEntityModel)
            .filter(KGEntityModel.entity_id == entity_id)
            .first()
        )
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
        from_model = (
            self._session.query(KGEntityModel)
            .filter(KGEntityModel.entity_id == from_entity_id)
            .first()
        )
        to_model = (
            self._session.query(KGEntityModel)
            .filter(KGEntityModel.entity_id == to_entity_id)
            .first()
        )
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

    def get_related(
        self, entity_id: str, relation_type: str | None = None
    ) -> list[KGEntityType]:
        entity_model = (
            self._session.query(KGEntityModel)
            .filter(KGEntityModel.entity_id == entity_id)
            .first()
        )
        if entity_model is None:
            return []
        query = self._session.query(KGRelationModel).filter(
            KGRelationModel.from_entity_id == entity_model.id
        )
        if relation_type:
            query = query.filter(KGRelationModel.relation_type == relation_type)
        relations = query.all()

        to_entity_ids = [rel.to_entity_id for rel in relations]
        if not to_entity_ids:
            return []

        related_entities = (
            self._session.query(KGEntityModel)
            .filter(KGEntityModel.id.in_(to_entity_ids))
            .all()
        )
        related_dict = {entity.id: entity for entity in related_entities}

        results = []
        for rel in relations:
            related = related_dict.get(rel.to_entity_id)
            if related:
                results.append(
                    KGEntityType(
                        entity_type=related.entity_type,
                        entity_id=related.entity_id,
                        properties=related.properties or {},
                    )
                )
        return results

    def find_pattern(self, pattern: str) -> list[KGEntityType]:
        parts = pattern.split("_")
        if len(parts) < 2:
            return []
        relation_type = "_".join(parts[:-1]) if len(parts) > 2 else parts[0]
        target_name = parts[-1]
        target = (
            self._session.query(KGEntityModel)
            .filter(KGEntityModel.entity_id.ilike(f"%{target_name}%"))
            .first()
        )
        if target is None:
            return []
        relations = (
            self._session.query(KGRelationModel)
            .filter(
                KGRelationModel.to_entity_id == target.id,
                KGRelationModel.relation_type == relation_type,
            )
            .all()
        )

        # ⚡ Bolt Optimization: Replace N+1 queries with bulk fetch
        source_entity_ids = [rel.from_entity_id for rel in relations]
        if not source_entity_ids:
            return []

        sources = (
            self._session.query(KGEntityModel)
            .filter(KGEntityModel.id.in_(source_entity_ids))
            .all()
        )
        source_dict = {source.id: source for source in sources}

        results = []
        for rel in relations:
            source = source_dict.get(rel.from_entity_id)
            if source:
                results.append(
                    KGEntityType(
                        entity_type=source.entity_type,
                        entity_id=source.entity_id,
                        properties=source.properties or {},
                    )
                )
        return results

    def validate_entity(
        self, entity_type: str, entity_id: str, properties: dict[str, Any] | None = None
    ) -> list[str]:
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
        from_exists = (
            self._session.query(KGEntityModel)
            .filter(KGEntityModel.entity_id == from_entity_id)
            .first()
        )
        if not from_exists:
            errors.append(f"from_entity '{from_entity_id}' does not exist")
        to_exists = (
            self._session.query(KGEntityModel)
            .filter(KGEntityModel.entity_id == to_entity_id)
            .first()
        )
        if not to_exists:
            errors.append(f"to_entity '{to_entity_id}' does not exist")
        return errors

    def persist_entity(
        self, entity: KGEntityType, db: Optional[Session] = None
    ) -> KGEntityType:
        session = db or self._session
        errors = self.validate_entity(
            entity.entity_type, entity.entity_id, entity.properties
        )
        if errors:
            raise ValueError(f"Entity validation failed: {errors}")
        existing = (
            session.query(KGEntityModel)
            .filter(KGEntityModel.entity_id == entity.entity_id)
            .first()
        )
        if existing:
            existing.properties = entity.properties
            existing.updated_at = utcnow()
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
            input_data={
                "entity_id": entity.entity_id,
                "entity_type": entity.entity_type,
            },
            output_data={"status": "persisted"},
            confidence=1.0,
            reasoning=f"Persisted entity {entity.entity_id}",
        )
        session.add(audit)
        session.commit()
        return entity

    def persist_relation(
        self, relation: KGRelationType, db: Optional[Session] = None
    ) -> KGRelationType:
        session = db or self._session
        errors = self.validate_relation(
            relation.from_entity,
            relation.to_entity,
            relation.relation_type,
            relation.weight,
            relation.confidence,
        )
        if errors:
            raise ValueError(f"Relation validation failed: {errors}")
        from_model = (
            session.query(KGEntityModel)
            .filter(KGEntityModel.entity_id == relation.from_entity)
            .first()
        )
        to_model = (
            session.query(KGEntityModel)
            .filter(KGEntityModel.entity_id == relation.to_entity)
            .first()
        )
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
            input_data={
                "from": relation.from_entity,
                "to": relation.to_entity,
                "type": relation.relation_type,
            },
            output_data={"status": "persisted"},
            confidence=relation.confidence,
            reasoning=f"Persisted relation {relation.from_entity} -> {relation.to_entity}",
        )
        session.add(audit)
        session.commit()
        return relation

    def load_entity(
        self, entity_id: str, db: Optional[Session] = None
    ) -> Optional[KGEntityType]:
        session = db or self._session
        model = (
            session.query(KGEntityModel)
            .filter(KGEntityModel.entity_id == entity_id)
            .first()
        )
        if not model:
            return None
        return KGEntityType(
            entity_type=model.entity_type,
            entity_id=model.entity_id,
            properties=model.properties or {},
        )

    def load_relations(
        self,
        entity_id: str,
        relation_type: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> list[KGRelationType]:
        session = db or self._session
        entity_model = (
            session.query(KGEntityModel)
            .filter(KGEntityModel.entity_id == entity_id)
            .first()
        )
        if not entity_model:
            return []
        query = session.query(KGRelationModel).filter(
            KGRelationModel.from_entity_id == entity_model.id
        )
        if relation_type:
            query = query.filter(KGRelationModel.relation_type == relation_type)
        relations = query.all()

        # ⚡ Bolt Optimization: Replace N+1 queries with bulk fetch
        to_entity_ids = [rel.to_entity_id for rel in relations]
        if not to_entity_ids:
            return []

        to_models = (
            session.query(KGEntityModel)
            .filter(KGEntityModel.id.in_(to_entity_ids))
            .all()
        )
        to_model_dict = {model.id: model for model in to_models}

        results = []
        for rel in relations:
            to_model = to_model_dict.get(rel.to_entity_id)
            if to_model:
                results.append(
                    KGRelationType(
                        from_entity=entity_id,
                        to_entity=to_model.entity_id,
                        relation_type=rel.relation_type,
                        weight=rel.weight,
                        confidence=rel.confidence,
                        timestamp=rel.created_at,
                    )
                )
        return results
