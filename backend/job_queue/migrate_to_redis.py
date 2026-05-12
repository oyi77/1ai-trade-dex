"""Drain SQLite job queue and migrate to Redis arq queue.

Usage:
    python -m backend.job_queue.migrate_to_redis           # SQLite -> Redis
    python -m backend.job_queue.migrate_to_redis --reverse # Redis -> SQLite (rollback)
"""
import argparse
import asyncio
from typing import Dict

from backend.job_queue.sqlite_queue import AsyncSQLiteQueue
from backend.models.database import SessionLocal, JobQueue

from loguru import logger


async def migrate_sqlite_to_redis() -> Dict[str, int]:
    """Drain pending SQLite jobs and enqueue them into Redis via arq."""
    try:
        from backend.job_queue.redis_queue import RedisQueue
        from backend.config import settings
    except ImportError as e:
        logger.error(f"RedisQueue unavailable: {e}")
        return {"migrated": 0, "failed": 0, "skipped": 0}

    redis_queue = RedisQueue(settings.JOB_QUEUE_URL if settings.JOB_QUEUE_URL.startswith("redis://") else settings.REDIS_URL)

    migrated = 0
    failed = 0

    session = SessionLocal()
    try:
        pending = session.query(JobQueue).filter(JobQueue.status == "pending").all()
        logger.info(f"Found {len(pending)} pending SQLite jobs to migrate")
        for job in pending:
            try:
                await redis_queue.enqueue(
                    job_type=job.job_type,
                    payload=job.payload or {},
                    priority=job.priority,
                    idempotency_key=job.idempotency_key,
                )
                # Mark as migrated (removed from active SQLite queue)
                job.status = "migrated"
                migrated += 1
            except Exception as e:
                logger.error(f"Failed to migrate job {job.id}: {e}")
                failed += 1
        session.commit()
    finally:
        session.close()

    logger.info(f"Migration complete: migrated={migrated} failed={failed}")
    return {"migrated": migrated, "failed": failed}


async def rollback_redis_to_sqlite() -> Dict[str, int]:
    """Restore migrated jobs back to pending state in SQLite (rollback)."""
    sqlite_queue = AsyncSQLiteQueue()
    restored = 0
    session = SessionLocal()
    try:
        migrated_jobs = session.query(JobQueue).filter(JobQueue.status == "migrated").all()
        logger.info(f"Restoring {len(migrated_jobs)} migrated jobs to pending")
        for job in migrated_jobs:
            job.status = "pending"
            restored += 1
        session.commit()
    finally:
        session.close()
        sqlite_queue.shutdown()
    logger.info(f"Rollback complete: restored={restored}")
    return {"restored": restored}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reverse", action="store_true", help="Rollback Redis -> SQLite")
    args = parser.parse_args()
    if args.reverse:
        asyncio.run(rollback_redis_to_sqlite())
    else:
        asyncio.run(migrate_sqlite_to_redis())


if __name__ == "__main__":
    main()
