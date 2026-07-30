from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import create_engine

from .entity import KnowledgeGraphEntityMixin
from .query import KnowledgeGraphQueryMixin
from .snapshot import KnowledgeGraphSnapshotMixin
from .graph_api import KnowledgeGraphGraphMixin


class KnowledgeGraph(
    KnowledgeGraphEntityMixin,
    KnowledgeGraphQueryMixin,
    KnowledgeGraphSnapshotMixin,
    KnowledgeGraphGraphMixin,
):
    """Knowledge graph for strategy persistence and query."""

    def __init__(
        self,
        session: Optional[Session] = None,
        db_url: str = "sqlite:///:memory:",
        cognitive_core: Optional[Any] = None,
        autocommit: bool = True,
    ):
        if session is not None:
            self._session = session
            self._owns_session = False
        else:
            from backend.models.database import Base

            self._engine = create_engine(db_url)
            Base.metadata.create_all(self._engine)
            self._session = sessionmaker(bind=self._engine)()
            self._owns_session = True
        self._autocommit = autocommit
        self._core = cognitive_core

    def close(self):
        if self._owns_session:
            self._session.close()


__all__ = ["KnowledgeGraph"]
