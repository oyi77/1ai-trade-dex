"""Tests for backend/queue/migrate_to_redis.py (RQ-017)."""
import pytest
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models.database import Base, JobQueue
from backend.job_queue.migrate_to_redis import rollback_redis_to_sqlite, migrate_sqlite_to_redis


# ---------------------------------------------------------------------------
# In-memory SQLite fixture isolated from the global test DB
# ---------------------------------------------------------------------------
@pytest.fixture()
def isolated_session(monkeypatch):
    """Create a fresh in-memory DB and patch SessionLocal for migration functions."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    import backend.models.database as _db_mod
    import backend.job_queue.migrate_to_redis as _mig_mod
    monkeypatch.setattr(_db_mod, "SessionLocal", Session)
    monkeypatch.setattr(_mig_mod, "SessionLocal", Session)

    session = Session()
    yield session
    session.close()


def test_rollback_marks_migrated_as_pending(isolated_session):
    # Insert a migrated job
    job = JobQueue(
        job_type="market_scan",
        payload={"market": "BTC-1m"},
        priority="medium",
        status="migrated",
    )
    isolated_session.add(job)
    isolated_session.commit()

    import asyncio
    result = asyncio.run(rollback_redis_to_sqlite())

    assert result["restored"] == 1

    isolated_session.expire_all()
    refreshed = isolated_session.query(JobQueue).filter_by(id=job.id).one()
    assert refreshed.status == "pending"


def test_migrate_handles_no_redis_gracefully():
    """When redis_queue module is unavailable, migrate should return gracefully."""
    import asyncio

    # Patch the import inside migrate_sqlite_to_redis to raise ImportError
    original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

    def _blocking_import(name, *args, **kwargs):
        if name == "backend.job_queue.redis_queue":
            raise ImportError("No module named 'backend.job_queue.redis_queue'")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=_blocking_import):
        result = asyncio.run(migrate_sqlite_to_redis())

    assert isinstance(result, dict)
    assert "migrated" in result
    assert result["migrated"] == 0
