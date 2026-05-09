<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-10 | Updated: 2026-05-09 -->

# test_queue

## Purpose
Unit and integration tests for the backend/queue/ module. Validates job queue implementations (SQLite and Redis), worker process lifecycle, crash recovery behavior, cache layer with circuit-breaker fallback, Redis migration scripts, and Prometheus queue metrics collection. Tests cover CRUD operations on job queues, worker spawning and job execution, multi-instance crash recovery via persistent storage, Redis availability detection and circuit-breaker state transitions, and queue depth metrics with latency percentiles.

## Key Files

| File | Description |
|------|-------------|
| `test_sqlite_queue.py` | AsyncSQLiteQueue CRUD tests: enqueue, dequeue, mark_complete, fail, get_pending_count. Isolated on-disk temp DB per test with NullPool to avoid thread connection sharing. |
| `test_redis_queue.py` | Factory routing tests: create_queue() selects AsyncSQLiteQueue or RedisQueue based on JOB_QUEUE_URL scheme (sqlite:// vs redis://). Skipped if arq not installed. |
| `test_worker.py` | Worker spawning, job processing, timeout handling, and pending count polling. Uses AsyncSQLiteQueue fixture with per-test temp DB and async event loop waits. |
| `test_crash_recovery.py` | Simulates process restart by creating two AsyncSQLiteQueue instances sharing the same on-disk DB file. Validates enqueued jobs survive crashes and are visible to new queue instance. |
| `test_redis_cache.py` | Redis cache with CircuitBreaker fallback to SQLite. Tests CircuitBreaker state machine (closed → open → half-open), cache get/set/expire, fallback behavior when Redis unavailable. Skipped if Redis not running. |
| `test_queue_metrics.py` | Prometheus metrics: job latency percentiles (p50, p95, p99), timeout/error rate calculation, queue depth tracking, JobTimer context manager integration. |
| `test_migrate_to_redis.py` | Migration script tests: rollback_redis_to_sqlite() marks migrated jobs as pending, migrate_sqlite_to_redis() moves pending jobs to Redis and marks status as migrated. Uses isolated in-memory DB per test. |
| `__init__.py` | Package marker (empty). |

## For AI Agents

### Working In This Directory

1. **SQLite Queue Isolation Pattern**:
   - Each test gets a fresh on-disk temp file via `tmp_path` fixture
   - Use `NullPool` to avoid "bad parameter" errors from shared in-memory SQLite connections
   - Use `monkeypatch` to redirect module-level `SessionLocal` globals before queue import
   - Example fixture:
   ```python
   @pytest.fixture()
   def queue(monkeypatch, tmp_path):
       db_file = tmp_path / "test.db"
       db_url = f"sqlite:///{db_file}"
       engine = create_engine(db_url, connect_args={"check_same_thread": False}, poolclass=NullPool)
       TestSession = sessionmaker(bind=engine)
       Base.metadata.create_all(bind=engine)
       import backend.queue.sqlite_queue as sq_mod
       monkeypatch.setattr(sq_mod, "SessionLocal", TestSession)
       q = AsyncSQLiteQueue()
       yield q, TestSession
       q.shutdown()
       engine.dispose()
   ```

2. **Redis Availability Checks**:
   - Use `_redis_available()` helper to skip Redis tests if server not running
   - Check socket connection to `127.0.0.1:6379` with short timeout (0.1-0.3 seconds)
   - Mark tests with `@pytest.mark.skipif(not _redis_available(), reason="Redis not running")`

3. **Async Test Pattern**:
   - Use `@pytest.mark.asyncio` for async test functions
   - Use `asyncio.run()` in sync test functions to call async code
   - Use `_wait_for_pending_zero(q, timeout=5.0)` helper to poll queue state with deadline

4. **Crash Recovery Simulation**:
   - Create two separate queue instances with same DB file path
   - Enqueue jobs with queue #1, optionally complete some
   - Shutdown queue #1
   - Create queue #2 from same DB file
   - Verify enqueued jobs are still visible to queue #2

5. **Factory Routing Tests**:
   - Mock `settings.JOB_QUEUE_URL` with sqlite:// or redis:// scheme
   - Call `create_queue()` and check instance type
   - Do NOT hardcode queue type; rely on factory to choose based on URL

6. **CircuitBreaker State Machine**:
   - States: `STATE_CLOSED` (normal), `STATE_OPEN` (failing), `STATE_HALF_OPEN` (testing recovery)
   - Methods: `is_open()`, `can_attempt()`, `record_success()`, `record_failure()`
   - Threshold and timeout are configurable; typical: threshold=3, timeout=60 seconds
   - Example:
   ```python
   cb = CircuitBreaker(threshold=3, timeout=60)
   assert cb.state == CircuitBreaker.STATE_CLOSED
   for _ in range(3):
       cb.record_failure()
   assert cb.is_open()
   ```

7. **Queue Metrics Recording**:
   - Call `m.record_job_completion(job_type, latency_seconds, status)` for each completed job
   - Status: "success", "error", "timeout"
   - Retrieve metrics: `m.percentiles(job_type)` for p50/p95/p99 latencies
   - Retrieve snapshot: `m.get_metrics_snapshot()` for full report with error/timeout rates

### Testing Requirements

1. **Run All Queue Tests**:
   ```bash
   pytest backend/tests/test_queue/ -v
   ```

2. **Run Specific Test File**:
   ```bash
   pytest backend/tests/test_queue/test_sqlite_queue.py -v
   pytest backend/tests/test_queue/test_worker.py -v
   ```

3. **Skip Redis Tests** (if Redis unavailable):
   ```bash
   pytest backend/tests/test_queue/ -v -m "not requires_redis"
   ```

4. **Run with Coverage**:
   ```bash
   pytest backend/tests/test_queue/ --cov=backend.queue --cov=backend.cache --cov-report=html
   ```

5. **Run Async Tests Only**:
   ```bash
   pytest backend/tests/test_queue/ -k "asyncio" -v
   ```

6. **Crash Recovery Test** (takes ~5-10 seconds):
   ```bash
   pytest backend/tests/test_queue/test_crash_recovery.py -v -s
   ```

### Common Patterns

1. **Monkeypatch SessionLocal Before Queue Import**:
   ```python
   import backend.queue.sqlite_queue as sq_mod
   monkeypatch.setattr(sq_mod, "SessionLocal", TestSession)
   q = AsyncSQLiteQueue()  # Now uses TestSession
   ```

2. **Async Job Enqueue + Dequeue**:
   ```python
   @pytest.mark.asyncio
   async def test_enqueue_dequeue(queue):
       q, session = queue
       job_id = await q.enqueue("market_scan", {"market": "BTC"})
       assert job_id is not None
       
       job = await q.dequeue()
       assert job.job_type == "market_scan"
       
       await q.mark_complete(job.id, {"result": "done"})
       assert await q.get_pending_count() == 0
   ```

3. **Polling with Timeout**:
   ```python
   async def _wait_for_condition(check_fn, timeout=5.0):
       deadline = asyncio.get_event_loop().time() + timeout
       while asyncio.get_event_loop().time() < deadline:
           if check_fn():
               return True
           await asyncio.sleep(0.1)
       return False
   ```

4. **Factory Selection by URL**:
   ```python
   def test_factory(monkeypatch):
       monkeypatch.setenv("JOB_QUEUE_URL", "sqlite:///./queue.db")
       q = create_queue()
       assert isinstance(q, AsyncSQLiteQueue)
   ```

5. **CircuitBreaker Fallback**:
   ```python
   cache = RedisCache(redis_url="redis://localhost:6379", fallback_cache=sqlite_cache)
   value = cache.get("key")  # Try Redis; on timeout, use fallback
   ```

6. **Metrics Snapshot**:
   ```python
   m = QueueMetrics()
   for i in range(100):
       m.record_job_completion("scan", float(i), "success")
   snap = m.get_metrics_snapshot()
   assert snap["depth"] >= 0
   assert "by_type" in snap and "scan" in snap["by_type"]
   ```

## Dependencies

### Internal
- `backend.models.database` — JobQueue ORM model, Base metadata
- `backend.queue.abstract` — create_queue() factory function
- `backend.queue.sqlite_queue` — AsyncSQLiteQueue implementation
- `backend.queue.redis_queue` — RedisQueue implementation (if arq installed)
- `backend.queue.worker` — Worker process lifecycle
- `backend.queue.migrate_to_redis` — Migration scripts
- `backend.cache.redis_cache` — RedisCache with CircuitBreaker
- `backend.queue.sqlite_cache` — SQLiteCache fallback
- `backend.monitoring.queue_metrics` — QueueMetrics and JobTimer

### External
- `pytest` — Test framework
- `pytest-asyncio` — Async test support
- `sqlalchemy` — ORM (in-memory + on-disk SQLite)
- `arq` — Redis async queue library (optional; tests skip if unavailable)
- `redis` — Redis client (optional; tests skip if server not running)
- `asyncio` — Async event loop
- `unittest.mock` — Mocking (patch, MagicMock)
- `socket` — Redis server availability check

<!-- MANUAL: -->
