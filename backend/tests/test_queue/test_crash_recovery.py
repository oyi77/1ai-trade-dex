"""
Tests for crash recovery via on-disk SQLite — RQ-010.

Simulates a process restart by creating two separate AsyncSQLiteQueue instances
that share the same on-disk database file.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models.database import Base, JobQueue
from backend.job_queue.sqlite_queue import AsyncSQLiteQueue


# ---------------------------------------------------------------------------
# Helper: build an engine + session factory for a given file path
# ---------------------------------------------------------------------------

def _make_engine_and_session(db_url: str):
    engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False},
    )
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return engine, Session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_jobs_survive_simulated_crash(tmp_path, monkeypatch):
    """
    Jobs enqueued by queue #1 are still visible to queue #2 after shutdown.
    """
    db_file = tmp_path / "test_recovery.db"
    db_url = f"sqlite:///{db_file}"

    # --- Session #1 ---
    engine1, Session1 = _make_engine_and_session(db_url)

    import backend.models.database as db_mod
    import backend.job_queue.sqlite_queue as sq_mod
    monkeypatch.setattr(db_mod, "SessionLocal", Session1)
    monkeypatch.setattr(sq_mod, "SessionLocal", Session1)

    queue1 = AsyncSQLiteQueue()

    # Enqueue 10 jobs
    job_ids = []
    for i in range(10):
        jid = await queue1.enqueue("market_scan", {"i": i})
        job_ids.append(jid)

    # Dequeue and complete 3
    for _ in range(3):
        job = await queue1.dequeue()
        assert job is not None
        await queue1.complete(job.job_id)

    # Simulate crash / process shutdown
    queue1.shutdown()
    engine1.dispose()

    # --- Session #2 (fresh restart) ---
    engine2, Session2 = _make_engine_and_session(db_url)
    monkeypatch.setattr(db_mod, "SessionLocal", Session2)
    monkeypatch.setattr(sq_mod, "SessionLocal", Session2)

    queue2 = AsyncSQLiteQueue()

    pending = await queue2.get_pending_count()
    assert pending == 7, f"Expected 7 pending jobs after restart, got {pending}"

    # Dequeue and complete the remaining 7
    for _ in range(7):
        job = await queue2.dequeue()
        assert job is not None
        await queue2.complete(job.job_id)

    # Verify all 10 are completed via direct DB query
    db = Session2()
    try:
        completed_count = db.query(JobQueue).filter(
            JobQueue.status == "completed"
        ).count()
        assert completed_count == 10, f"Expected 10 completed, got {completed_count}"
    finally:
        db.close()

    queue2.shutdown()
    engine2.dispose()


@pytest.mark.asyncio
async def test_jobs_processed_in_order_after_restart(tmp_path, monkeypatch):
    """
    After restart, dequeue still returns jobs in priority order.
    """
    db_file = tmp_path / "test_order_recovery.db"
    db_url = f"sqlite:///{db_file}"

    # --- Session #1: enqueue jobs ---
    engine1, Session1 = _make_engine_and_session(db_url)

    import backend.models.database as db_mod
    import backend.job_queue.sqlite_queue as sq_mod
    monkeypatch.setattr(db_mod, "SessionLocal", Session1)
    monkeypatch.setattr(sq_mod, "SessionLocal", Session1)

    queue1 = AsyncSQLiteQueue()
    await queue1.enqueue("market_scan", {"order": 1}, priority="low")
    await queue1.enqueue("market_scan", {"order": 2}, priority="medium")
    await queue1.enqueue("market_scan", {"order": 3}, priority="critical")
    await queue1.enqueue("market_scan", {"order": 4}, priority="high")

    # Simulate crash
    queue1.shutdown()
    engine1.dispose()

    # --- Session #2: verify order ---
    engine2, Session2 = _make_engine_and_session(db_url)
    monkeypatch.setattr(db_mod, "SessionLocal", Session2)
    monkeypatch.setattr(sq_mod, "SessionLocal", Session2)

    queue2 = AsyncSQLiteQueue()

    priorities = []
    for _ in range(4):
        job = await queue2.dequeue()
        assert job is not None
        priorities.append(job.priority)

    assert priorities == ["critical", "high", "medium", "low"], (
        f"Wrong priority order after restart: {priorities}"
    )

    queue2.shutdown()
    engine2.dispose()
