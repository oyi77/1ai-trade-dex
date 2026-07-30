from __future__ import annotations

import uuid
from datetime import datetime, timezone

from backend.models.kg_models import (
    KGEntity as KGEntityModel,
    KGRelation as KGRelationModel,
    DecisionAuditLog,
)


class KnowledgeGraphSnapshotMixin:
    """Snapshot and rollback mixin for KnowledgeGraph."""

    def rollback_to(self, timestamp: datetime) -> int:
        relations_deleted = (
            self._session.query(KGRelationModel)
            .filter(
                KGRelationModel.created_at > timestamp,
            )
            .delete()
        )
        entities_deleted = (
            self._session.query(KGEntityModel)
            .filter(
                KGEntityModel.created_at > timestamp,
            )
            .delete()
        )
        self._session.commit()
        return relations_deleted + entities_deleted

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
            "relations": [
                {
                    "from": r.from_entity_id,
                    "to": r.to_entity_id,
                    "type": r.relation_type,
                }
                for r in relations
            ],
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
        relations_deleted = (
            self._session.query(KGRelationModel)
            .filter(KGRelationModel.created_at > snapshot_time)
            .delete()
        )
        entities_deleted = (
            self._session.query(KGEntityModel)
            .filter(KGEntityModel.created_at > snapshot_time)
            .delete()
        )
        rollback_audit = DecisionAuditLog(
            timestamp=datetime.now(timezone.utc),
            decision_type="kg_rollback",
            input_data={
                "snapshot_id": snapshot_id,
                "snapshot_time": (
                    snapshot_time.isoformat()
                    if isinstance(snapshot_time, datetime)
                    else snapshot_time
                ),
            },
            output_data={
                "relations_deleted": relations_deleted,
                "entities_deleted": entities_deleted,
            },
            confidence=1.0,
            reasoning=f"Rolled back to snapshot {snapshot_id}",
        )
        self._session.add(rollback_audit)
        self._session.commit()
        return relations_deleted + entities_deleted
