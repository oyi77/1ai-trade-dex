from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from backend.core.agi_types import KGEntity
from backend.models.kg_models import Base, KGEntity as KGEntityModel, KGRelation as KGRelationModel


class PromptVersion:
    def __init__(
        self,
        template_id: str,
        version: str,
        prompt_text: str,
        win_rate: float = 0.0,
        trade_count: int = 0,
        promoted_at: Optional[datetime] = None,
    ):
        self.template_id = template_id
        self.version = version
        self.prompt_text = prompt_text
        self.win_rate = win_rate
        self.trade_count = trade_count
        self.created_at = datetime.now(timezone.utc)
        self.promoted_at = promoted_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "version": self.version,
            "prompt_text": self.prompt_text,
            "win_rate": self.win_rate,
            "trade_count": self.trade_count,
            "created_at": self.created_at.isoformat(),
            "promoted_at": self.promoted_at.isoformat() if self.promoted_at else None,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PromptVersion:
        return cls(
            template_id=d["template_id"],
            version=d["version"],
            prompt_text=d["prompt_text"],
            win_rate=d.get("win_rate", 0.0),
            trade_count=d.get("trade_count", 0),
            promoted_at=datetime.fromisoformat(d["promoted_at"]) if d.get("promoted_at") else None,
        )


class PromptComparison:
    def __init__(self, version_a: str, version_b: str, winner: Optional[str] = None, confidence: float = 0.0):
        self.version_a = version_a
        self.version_b = version_b
        self.winner = winner
        self.confidence = confidence


class DynamicPromptEngine:
    def __init__(self, session: Optional[Session] = None, db_url: str = "sqlite:///:memory:"):
        if session is not None:
            self._session = session
            self._owns_session = False
        else:
            self._engine = create_engine(db_url)
            Base.metadata.create_all(self._engine)
            self._session = sessionmaker(bind=self._engine)()
            self._owns_session = True

    def close(self):
        if self._owns_session:
            self._session.close()

    def get_prompt(self, template_id: str, context: dict[str, Any] | None = None) -> str:
        entity = (
            self._session.query(KGEntityModel)
            .filter(
                KGEntityModel.entity_type == "prompt_version",
                KGEntityModel.entity_id.startswith(f"prompt:{template_id}:"),
            )
            .order_by(KGEntityModel.created_at.desc())
            .first()
        )
        if not entity:
            return ""
        prompt_text = entity.properties.get("prompt_text", "")
        if context:
            for key, value in context.items():
                prompt_text = prompt_text.replace(f"{{{key}}}", str(value))
        return prompt_text

    def evolve_prompt(self, template_id: str, outcomes: list[dict[str, Any]]) -> PromptVersion:
        old_version = self.get_prompt(template_id)
        new_version_str = f"v{int(datetime.now(timezone.utc).timestamp())}"
        new_prompt_text = old_version + "\n# Evolved based on outcomes"

        wins = sum(1 for o in outcomes if o.get("result") == "win")
        total = len(outcomes)
        new_win_rate = wins / total if total > 0 else 0.0

        new_version = PromptVersion(
            template_id=template_id,
            version=new_version_str,
            prompt_text=new_prompt_text,
            win_rate=new_win_rate,
            trade_count=total,
        )

        entity = KGEntity(
            entity_type="prompt_version",
            entity_id=f"prompt:{template_id}:{new_version_str}",
            properties=new_version.to_dict(),
        )
        entity_model = KGEntityModel(
            entity_type=entity.entity_type,
            entity_id=entity.entity_id,
            properties=entity.properties,
        )
        self._session.add(entity_model)

        if old_version:
            old_entity = (
                self._session.query(KGEntityModel)
                .filter(
                    KGEntityModel.entity_type == "prompt_version",
                    KGEntityModel.entity_id.startswith(f"prompt:{template_id}:"),
                )
                .order_by(KGEntityModel.created_at.desc())
                .offset(1)
                .first()
            )
            if old_entity:
                rel = KGRelationModel(
                    from_entity_id=entity_model.id,
                    to_entity_id=old_entity.id,
                    relation_type="evolved_from",
                    weight=1.0,
                    confidence=0.9,
                )
                self._session.add(rel)

        self._session.commit()
        return new_version

    def compare_prompts(
        self, template_id: str, version_a: str, version_b: str
    ) -> PromptComparison:
        entity_a = (
            self._session.query(KGEntityModel)
            .filter(KGEntityModel.entity_id == f"prompt:{template_id}:{version_a}")
            .first()
        )
        entity_b = (
            self._session.query(KGEntityModel)
            .filter(KGEntityModel.entity_id == f"prompt:{template_id}:{version_b}")
            .first()
        )
        if not entity_a or not entity_b:
            return PromptComparison(version_a, version_b)

        win_rate_a = entity_a.properties.get("win_rate", 0.0)
        win_rate_b = entity_b.properties.get("win_rate", 0.0)
        trade_count_a = entity_a.properties.get("trade_count", 0)

        if trade_count_a >= 50 and win_rate_b > win_rate_a + 0.05:
            winner = version_b
            confidence = min((win_rate_b - win_rate_a) * 2, 1.0)
        else:
            winner = version_a
            confidence = 1.0 - min((win_rate_a - win_rate_b) * 2, 1.0)

        return PromptComparison(
            version_a=version_a,
            version_b=version_b,
            winner=winner,
            confidence=confidence,
        )

    def rollback_prompt(self, template_id: str, to_version: str) -> int:
        target_entity = (
            self._session.query(KGEntityModel)
            .filter(KGEntityModel.entity_id == f"prompt:{template_id}:{to_version}")
            .first()
        )
        if not target_entity:
            return 0

        newer_entities = (
            self._session.query(KGEntityModel)
            .filter(
                KGEntityModel.entity_type == "prompt_version",
                KGEntityModel.entity_id.startswith(f"prompt:{template_id}:"),
                KGEntityModel.created_at > target_entity.created_at,
            )
            .all()
        )

        deleted = 0
        for entity in newer_entities:
            self._session.query(KGRelationModel).filter(
                (KGRelationModel.from_entity_id == entity.id)
                | (KGRelationModel.to_entity_id == entity.id)
            ).delete()
            self._session.delete(entity)
            deleted += 1

        self._session.commit()
        return deleted
