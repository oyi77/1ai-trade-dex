"""
Tests for Worker — RQ-011.

Uses small timeouts (1-2 s) to keep the suite fast.

Note on DB isolation: AsyncSQLiteQueue uses a ThreadPoolExecutor internally.
In-memory SQLite with StaticPool shares one connection across threads causing
"bad parameter" errors; with NullPool each new connection gets an empty DB.
Using a per-test on-disk temp file lets every thread open the same schema.
"""

import asyncio
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from backend.models.database import Base, JobQueue
from backend.job_queue.sqlite_queue import AsyncSQLiteQueue
from backend.job_queue.worker import Worker


# ---------------------------------------------------------------------------
# Fixture: isolated on-disk temp DB + queue + monkeypatched SessionLocal
# ---------------------------------------------------------------------------


@pytest.fixture()
def queue(monkeypatch, tmp_path):
    db_file = tmp_path / "test_worker.db"
    db_url = f"sqlite:///{db_file}"
    engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    import backend.models.database as db_mod

    monkeypatch.setattr(db_mod, "SessionLocal", TestSession)
    import backend.job_queue.sqlite_queue as sq_mod

    monkeypatch.setattr(sq_mod, "SessionLocal", TestSession)

    q = AsyncSQLiteQueue()
    yield q, TestSession
    q.shutdown()
    engine.dispose()


async def _wait_for_pending_zero(q, timeout=5.0):
    """Poll until pending count reaches 0 or timeout expires."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if await q.get_pending_count() == 0:
            return True
        await asyncio.sleep(0.1)
    return False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_processes_job(queue, monkeypatch):
    """Worker calls handler, marks job completed."""
    q, Session = queue

    async def _fake_dispatch(job):
        return {"success": True, "message": "ok"}

    job_id = await q.enqueue("market_scan", {"ticker": "BTC"})

    worker = Worker(q, max_concurrent=1)
    monkeypatch.setattr(worker, "dispatch_job", _fake_dispatch)

    task = asyncio.create_task(worker.start())
    # Wait until the job leaves the pending state (processing or completed)
    _reached_zero = await _wait_for_pending_zero(q, timeout=5.0)
    # Give a moment for _process_job to finish after dequeue
    await asyncio.sleep(0.3)
    await worker.stop()
    await asyncio.wait_for(task, timeout=3.0)

    db = Session()
    try:
        row = db.query(JobQueue).filter(JobQueue.id == int(job_id)).first()
        assert row.status == "completed"
    finally:
        db.close()


@pytest.mark.asyncio
async def test_worker_dispatches_weather_scan(queue, monkeypatch):
    """Worker dispatches weather_scan jobs to the registered handler."""
    q, Session = queue
    seen_payloads = []

    async def _fake_weather_scan(payload):
        seen_payloads.append(payload)
        return {"success": True, "message": "weather ok"}

    import backend.job_queue.handlers as handlers_mod

    monkeypatch.setattr(handlers_mod, "weather_scan", _fake_weather_scan)
    job_id = await q.enqueue("weather_scan", {"mode": "paper"})

    worker = Worker(q, max_concurrent=1)
    task = asyncio.create_task(worker.start())
    _reached_zero = await _wait_for_pending_zero(q, timeout=5.0)
    await asyncio.sleep(0.3)
    await worker.stop()
    await asyncio.wait_for(task, timeout=3.0)

    db = Session()
    try:
        row = db.query(JobQueue).filter(JobQueue.id == int(job_id)).first()
        assert row.status == "completed"
        assert seen_payloads == [{"mode": "paper"}]
    finally:
        db.close()


@pytest.mark.asyncio
async def test_worker_handles_timeout(queue, monkeypatch):
    """Worker marks job failed/pending with 'timed out' in error_message."""
    q, Session = queue

    # Patch timeout to 1 second
    import backend.config as cfg_mod

    monkeypatch.setattr(cfg_mod.settings, "JOB_TIMEOUT_SECONDS", 1)
    import backend.job_queue.worker as wk_mod

    monkeypatch.setattr(wk_mod.settings, "JOB_TIMEOUT_SECONDS", 1)

    async def _slow_handler(job):
        await asyncio.sleep(5)
        return {"success": True, "message": "should not reach here"}

    job_id = await q.enqueue("market_scan", {"market": "test"})

    worker = Worker(q, max_concurrent=1)
    monkeypatch.setattr(worker, "dispatch_job", _slow_handler)

    task = asyncio.create_task(worker.start())
    # Wait long enough for timeout to fire (>1s) plus some processing margin
    await asyncio.sleep(3.0)
    await worker.stop()
    await asyncio.wait_for(task, timeout=3.0)
    # Give the thread pool a moment to flush the final fail() DB write
    await asyncio.sleep(0.3)

    db = Session()
    try:
        row = db.query(JobQueue).filter(JobQueue.id == int(job_id)).first()
        # Either retried (pending) or permanently failed — error message must contain "timed out"
        assert row.status in ("pending", "failed")
        assert row.error_message is not None
        assert "timed out" in row.error_message.lower()
    finally:
        db.close()


@pytest.mark.asyncio
async def test_worker_continues_after_timeout(queue, monkeypatch):
    """Worker processes second job even after first job times out."""
    q, Session = queue

    import backend.config as cfg_mod

    monkeypatch.setattr(cfg_mod.settings, "JOB_TIMEOUT_SECONDS", 1)
    import backend.job_queue.worker as wk_mod

    monkeypatch.setattr(wk_mod.settings, "JOB_TIMEOUT_SECONDS", 1)

    call_log = []

    async def _selective_handler(job):
        payload = job.payload
        if payload.get("slow"):
            await asyncio.sleep(5)  # will time out
            return {"success": True, "message": "slow done"}
        else:
            call_log.append(job.job_id)
            return {"success": True, "message": "fast done"}

    _slow_id = await q.enqueue("market_scan", {"slow": True}, priority="high")
    fast_id = await q.enqueue("market_scan", {"slow": False}, priority="low")

    worker = Worker(q, max_concurrent=2)
    monkeypatch.setattr(worker, "dispatch_job", _selective_handler)

    task = asyncio.create_task(worker.start())
    # Wait for: slow timeout (1s) + fast completion + some margin
    await asyncio.sleep(4.0)
    await worker.stop()
    await asyncio.wait_for(task, timeout=3.0)

    db = Session()
    try:
        fast_row = db.query(JobQueue).filter(JobQueue.id == int(fast_id)).first()
        assert fast_row.status == "completed", (
            f"Fast job should be completed, got {fast_row.status}"
        )
    finally:
        db.close()


@pytest.mark.asyncio
async def test_worker_graceful_shutdown(queue):
    """stop() sets _running=False and shuts down executor."""
    q, _ = queue
    worker = Worker(q, max_concurrent=1)

    task = asyncio.create_task(worker.start())
    await asyncio.sleep(0.2)  # let it start

    assert worker._running is True
    await worker.stop()
    await asyncio.wait_for(task, timeout=3.0)

    assert worker._running is False
    import pytest as _pytest

    with _pytest.raises(RuntimeError):
        worker._db_executor.submit(lambda: None)
