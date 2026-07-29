# reschedule.py — extracted from _scheduler_core.py
"""Job rescheduling: update APScheduler intervals when settings change."""

from apscheduler.triggers.interval import IntervalTrigger
from backend.config import settings
from loguru import logger

from .event_log import log_event
from .state import _get_scheduler


def reschedule_jobs() -> list[dict]:
    """Reschedule jobs with current settings values. Call after settings update."""
    from apscheduler.jobstores.base import JobLookupError as _JobLookupError

    sched = _get_scheduler()
    if sched is None or not sched.running:
        return []

    results = []

    # Reschedule scan job
    try:
        sched.reschedule_job(
            "market_scan",
            trigger=IntervalTrigger(seconds=settings.SCAN_INTERVAL_SECONDS),
        )
        job = sched.get_job("market_scan")
        results.append(
            {
                "job_id": "market_scan",
                "next_run": str(job.next_run_time) if job else None,
            }
        )
    except _JobLookupError:
        logger.warning("market_scan job not registered, skipping reschedule")
    except Exception as e:
        logger.warning(f"Failed to reschedule market_scan: {e}")

    # Reschedule settlement job
    try:
        sched.reschedule_job(
            "settlement_check",
            trigger=IntervalTrigger(seconds=settings.SETTLEMENT_INTERVAL_SECONDS),
        )
        job = sched.get_job("settlement_check")
        results.append(
            {
                "job_id": "settlement_check",
                "next_run": str(job.next_run_time) if job else None,
            }
        )
    except _JobLookupError:
        logger.warning("settlement_check job not registered, skipping reschedule")
    except Exception as e:
        logger.warning(f"Failed to reschedule settlement_check: {e}")

    # Reschedule weather scan if enabled
    if settings.WEATHER_ENABLED:
        try:
            sched.reschedule_job(
                "weather_scan",
                trigger=IntervalTrigger(seconds=settings.WEATHER_SCAN_INTERVAL_SECONDS),
            )
            job = sched.get_job("weather_scan")
            results.append(
                {
                    "job_id": "weather_scan",
                    "next_run": str(job.next_run_time) if job else None,
                }
            )
        except _JobLookupError:
            logger.warning("weather_scan job not registered, skipping reschedule")
        except Exception as e:
            logger.warning(f"Failed to reschedule weather_scan: {e}")

    log_event("info", f"Scheduler jobs rescheduled: {[r['job_id'] for r in results]}")
    return results
