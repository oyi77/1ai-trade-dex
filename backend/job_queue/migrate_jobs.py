"""Migrate existing APScheduler jobs into the persistent JobQueue.

Usage:
    python -m backend.job_queue.migrate_jobs
"""

import asyncio
from typing import List, Dict, Any

from backend.job_queue.sqlite_queue import AsyncSQLiteQueue

from loguru import logger

# Canonical jobs that the scheduler runs (mirrors backend/core/scheduler.py)
DEFAULT_JOBS: List[Dict[str, Any]] = [
    {"job_type": "market_scan", "priority": "high", "payload": {"source": "btc_5m"}},
    {"job_type": "settlement_check", "priority": "medium", "payload": {}},
    {"job_type": "signal_generation", "priority": "high", "payload": {}},
]


async def migrate_apjobs_to_queue() -> Dict[str, int]:
    """Enqueue the canonical scheduler jobs into the persistent queue.

    Returns:
        Dict with keys: migrated, failed.
    """
    queue = AsyncSQLiteQueue()
    migrated = 0
    failed = 0
    try:
        for job in DEFAULT_JOBS:
            try:
                job_id = await queue.enqueue(
                    job_type=job["job_type"],
                    payload=job["payload"],
                    priority=job["priority"],
                    idempotency_key=f"migrate:{job['job_type']}",
                )
                logger.info(f"Migrated job {job['job_type']} -> id={job_id}")
                migrated += 1
            except Exception as e:
                logger.error(f"Failed to migrate {job['job_type']}: {e}")
                failed += 1
    finally:
        queue.shutdown()
    logger.info(f"Migration complete: migrated={migrated} failed={failed}")
    return {"migrated": migrated, "failed": failed}


def main() -> None:
    asyncio.run(migrate_apjobs_to_queue())


if __name__ == "__main__":
    main()
