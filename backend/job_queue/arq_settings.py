"""
arq Worker configuration for PolyEdge job queue.

Start the worker with:
    arq backend.job_queue.arq_settings.WorkerSettings

RQ-015: arq-based Redis queue
"""
from arq.connections import RedisSettings

from backend.config import settings
from backend.job_queue import handlers as h


async def market_scan(ctx, payload):
    """arq task wrapper for market_scan handler."""
    return await h.market_scan(payload)


async def settlement_check(ctx, payload):
    """arq task wrapper for settlement_check handler."""
    return await h.settlement_check(payload)


async def signal_generation(ctx, payload):
    """arq task wrapper for signal_generation handler."""
    return await h.signal_generation(payload)


class WorkerSettings:
    """arq Worker configuration."""

    functions = [market_scan, settlement_check, signal_generation]
    redis_settings = RedisSettings.from_dsn(settings.JOB_QUEUE_URL)
    max_jobs = settings.MAX_CONCURRENT_JOBS
    job_timeout = settings.JOB_TIMEOUT_SECONDS
