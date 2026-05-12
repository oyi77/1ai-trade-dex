from datetime import datetime, timedelta, timezone

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from backend.models.database import SessionLocal, engine, Base, ResearchItemDB
from backend.research.models import ResearchItem
from backend.clients.bigbrain import BigBrainClient

from loguru import logger


class ResearchStorage:
    def __init__(self):
        Base.metadata.create_all(engine)

    def _to_db(self, item: ResearchItem) -> ResearchItemDB:
        return ResearchItemDB(
            title=item.title,
            source=item.source,
            url=item.url,
            content_summary=item.content,
            relevance_score=item.relevance_score,
            fingerprint=item.fingerprint,
            created_at=item.timestamp,
        )

    def _to_dataclass(self, row: ResearchItemDB) -> ResearchItem:
        return ResearchItem(
            id=row.id,
            title=row.title,
            source=row.source,
            content=row.content_summary or "",
            relevance_score=row.relevance_score,
            url=row.url,
            fingerprint=row.fingerprint,
            timestamp=row.created_at,
        )

    async def store_items(self, items: list[ResearchItem]) -> int:
        inserted = 0
        brain = BigBrainClient()
        with SessionLocal() as db:
            for item in items:
                try:
                    row = self._to_db(item)
                    db.add(row)
                    db.flush()
                    inserted += 1
                except IntegrityError:
                    db.rollback()
                    continue

                if item.relevance_score > 0.6:
                    try:
                        await brain._write_memory(
                            wing="trading",
                            room="research",
                            content=item.content,
                        )
                    except Exception:
                        logger.exception("BigBrain write failed for %s", item.fingerprint)

            db.commit()
        return inserted

    async def get_recent(
        self, hours: int = 24, min_relevance: float = 0.3
    ) -> list[ResearchItem]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        with SessionLocal() as db:
            rows = (
                db.query(ResearchItemDB)
                .filter(
                    ResearchItemDB.created_at >= cutoff,
                    ResearchItemDB.relevance_score >= min_relevance,
                )
                .order_by(ResearchItemDB.created_at.desc())
                .all()
            )
            return [self._to_dataclass(r) for r in rows]

    async def get_for_market(
        self, market_query: str, limit: int = 5
    ) -> list[ResearchItem]:
        pattern = f"%{market_query}%"
        with SessionLocal() as db:
            rows = (
                db.query(ResearchItemDB)
                .filter(
                    or_(
                        ResearchItemDB.title.ilike(pattern),
                        ResearchItemDB.content_summary.ilike(pattern),
                    )
                )
                .order_by(ResearchItemDB.relevance_score.desc())
                .limit(limit)
                .all()
            )
            return [self._to_dataclass(r) for r in rows]

    async def mark_used(self, item_ids: list[int]) -> None:
        if not item_ids:
            return
        with SessionLocal() as db:
            db.query(ResearchItemDB).filter(ResearchItemDB.id.in_(item_ids)).update(
                {ResearchItemDB.used_in_decision: True}, synchronize_session=False
            )
            db.commit()
