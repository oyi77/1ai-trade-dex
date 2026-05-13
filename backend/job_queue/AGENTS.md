<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-10 | Updated: 2026-05-09 -->

# queue

## Purpose

Async job queue abstraction with pluggable backends (SQLite Phase 1, Redis Phase 2). Enables decoupling of background tasks (market scanning, strategy execution, data fetching, settlements) from the main event loop. Abstract interface ensures code is backend-agnostic; implementations handle enqueueing, dequeueing, retry logic, and job lifecycle tracking.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker; exports factory functions `create_queue()`, `create_cache()` |
| `abstract.py` | AbstractQueue base class and Job dataclass; defines contract for enqueue/dequeue/complete/fail with priority, idempotency, retry tracking |
| `sqlite_queue.py` | AsyncSQLiteQueue: async SQLite-backed queue using ThreadPoolExecutor for sync DB operations; stores jobs in JobQueue table; PRIORITY_MAP for ordering |
| `redis_queue.py` | RedisQueue: arq-based Redis job queue for Phase 2; enqueue via Redis, workers managed by arq framework |
| `sqlite_cache.py` | SQLiteCache: TTL-based cache for idempotency keys and dedup; async interface wrapping SQLite in thread pool |
| `handlers.py` | Job handlers (async functions): market_scan, weather_scan, settlement, signal_generation, backtest_run; wrap existing scheduler logic for queue execution |
| `worker.py` | Worker class: continuous loop polling queue, enforcing max_concurrent limit, dispatching market/weather/settlement/signal jobs to handlers, tracking timeouts/failures, metrics recording |
| `arq_settings.py` | arq settings (job timeout, max retries, queue name prefixes) for Redis worker configuration |
| `migrate_jobs.py` | Migration utility: transfer pending/failed jobs from old queue system to new one |
| `migrate_to_redis.py` | Migration script: bulk migration from SQLite to Redis (one-time operation for Phase 2) |

## For AI Agents

### Working In This Directory

1. **Enqueue a job** (from any module):
   ```python
   from backend.queue.abstract import create_queue
   
   queue = create_queue()  # Returns AsyncSQLiteQueue or RedisQueue based on config
   job_id = await queue.enqueue(
       job_type="market_scan",
       payload={"market_symbols": ["BTC-USD", "ETH-USD"]},
       priority="high",
       idempotency_key="scan_2026_04_10_1000"  # Prevent duplicate scans
   )
   print(f"Enqueued job {job_id}")
   ```

2. **Start the worker** (main process):
   ```python
   from backend.queue.worker import Worker
   from backend.queue.abstract import create_queue
   
   queue = create_queue()
   worker = Worker(queue, max_concurrent=5)
   
   # Run until stopped (SIGTERM/SIGINT)
   try:
       await worker.run()
   except KeyboardInterrupt:
       await worker.stop()  # 10s grace period for in-flight jobs
   ```

3. **Register a handler** (optional, for custom jobs):
   ```python
   # handlers.py: add new async function
   async def custom_job(payload: Dict[str, Any]) -> Dict[str, Any]:
       try:
           result = await do_something(payload)
           return {"success": True, "data": result}
       except Exception as e:
           return {"success": False, "error": str(e)}
   
   # In worker.py run() method, add to handler dispatch
   ```

4. **Job lifecycle**:
   ```python
   # After dequeue
   job = await queue.dequeue()  # Returns Job with status="pending"
   
   # Attempt execution
   try:
       result = await handlers[job.job_type](job.payload)
       await queue.complete(job.job_id, result)  # status → "completed"
   except TimeoutError:
       await queue.fail(job.job_id, "timeout")  # Increment retry_count, requeue if < max_retries
   except Exception as e:
       await queue.fail(job.job_id, str(e))  # status → "failed"
   ```

5. **Idempotency**: Use idempotency_key to prevent duplicate execution:
   ```python
   # First call
   await queue.enqueue("market_scan", {}, idempotency_key="scan_daily")
   
   # Retry with same key → queue deduplicates, returns same job_id
   await queue.enqueue("market_scan", {}, idempotency_key="scan_daily")
   ```

6. **Priority ordering** (CRITICAL > HIGH > MEDIUM > LOW):
   ```python
   # Critical tasks (e.g., risk management, halt signal) enqueue as "critical"
   await queue.enqueue("risk_check", {}, priority="critical")
   
   # Worker dequeues critical before low-priority scanning jobs
   ```

### Testing Requirements

1. **In-memory SQLite queue for tests**:
   ```python
   from backend.queue.sqlite_queue import AsyncSQLiteQueue
   
   @pytest.fixture
   async def test_queue():
       queue = AsyncSQLiteQueue(db_path=":memory:")
       yield queue
   ```

2. **Mock handlers** (don't execute real strategies):
   ```python
   @pytest.fixture
   async def mock_handlers(monkeypatch):
       async def mock_market_scan(payload):
           return {"success": True, "data": {"signals": []}}
       
       monkeypatch.setattr("backend.queue.handlers.market_scan", mock_market_scan)
       yield
   ```

3. **Test job retry logic**:
   ```python
   async def test_job_retry():
       queue = AsyncSQLiteQueue()
       job_id = await queue.enqueue("test_job", {})
       
       # Mark as failed
       await queue.fail(job_id, "temporary error")
       
       # Verify retry_count incremented and status still pending
       job = await queue.dequeue()
       assert job.retry_count == 1
       assert job.status == "pending"
   ```

4. **Test max concurrent limit**:
   ```python
   async def test_max_concurrent():
       queue = AsyncSQLiteQueue()
       worker = Worker(queue, max_concurrent=2)
       
       # Enqueue 5 jobs
       for i in range(5):
           await queue.enqueue("slow_job", {})
       
       # Worker enforces max 2 running at once (verified via semaphore)
   ```

5. **Run tests**:
   ```bash
   pytest backend/tests/test_queue.py -v
   pytest backend/tests/test_worker.py -v
   pytest backend/tests/test_sqlite_queue.py -v
   ```

### Common Patterns

1. **Factory for queue/cache selection** (based on config):
   ```python
   # In __init__.py
   def create_queue():
       if settings.QUEUE_BACKEND == "redis":
           return RedisQueue(settings.REDIS_URL)
       else:
           return AsyncSQLiteQueue()
   ```

2. **Market scan job** (async scheduled task):
   ```python
   # From scheduler.py, enqueue instead of direct call
   from backend.queue.abstract import create_queue
   
   queue = create_queue()
   await queue.enqueue(
       job_type="market_scan",
       payload={"limit": 200},
       priority="medium"
   )
   # Worker picks it up and calls handlers.market_scan()
   ```

3. **Settlement job** (on trade completion):
   ```python
   # From trade execution logic
   await queue.enqueue(
       job_type="settlement",
       payload={"trade_id": trade.id},
       priority="high"
   )
   # Worker will call handlers.settlement() with {trade_id: ...}
   ```

4. **Backtest result persistence** (long-running):
   ```python
   # Strategy backtest enqueues result storage
   await queue.enqueue(
       job_type="backtest_run",
       payload={
           "strategy_name": "btc_oracle",
           "results": results_dict,
           "completed_at": datetime.utcnow().isoformat()
       },
       priority="low"  # Not urgent
   )
   ```

5. **Error handling in worker**:
   ```python
   # Worker catches and logs errors
   except asyncio.TimeoutError:
       logger.warning(f"Job {job.job_id} timeout after {job.max_retries} retries")
       # Mark as permanently failed
       await queue.fail(job.job_id, "max_retries_exceeded")
   except Exception as e:
       logger.error(f"Job {job.job_id} error: {e}")
       await queue.fail(job.job_id, str(e))
   ```

## Dependencies

### Internal

- `backend.config` — QUEUE_BACKEND, REDIS_URL, MAX_CONCURRENT_JOBS settings
- `backend.models.database` — JobQueue table (for SQLite backend); SessionLocal
- `backend.monitoring.queue_metrics` — JobTimer, get_queue_metrics() for latency tracking
- `backend.queue.handlers` — Job handler functions (market_scan, settlement, etc.)

### External

- **sqlalchemy** (2.0+) — SQLAlchemy ORM for SQLite queue table
- **redis** (optional) — Redis client for Phase 2 RedisQueue
- **arq** (optional) — arq job queue framework for Redis
- **asyncio** (stdlib) — Async/await, Task, TimeoutError, CancelledError
- **concurrent.futures** (stdlib) — ThreadPoolExecutor for sync→async wrapping
- **logging** (stdlib) — Worker logging

<!-- MANUAL: -->
