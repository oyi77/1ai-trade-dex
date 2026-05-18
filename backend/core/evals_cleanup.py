"""G-36: Cleanup old eval reports to prevent unbounded disk growth.

Removes eval report files older than EVALS_REPORT_MAX_AGE_DAYS (default 30).
"""
import time
from pathlib import Path

from backend.config import settings
from loguru import logger

EVALS_REPORT_DIR = Path("backend/evals/reports")


def evals_cleanup_job() -> None:
    """Remove eval reports older than the configured max age."""
    max_age_days = int(getattr(settings, "EVALS_REPORT_MAX_AGE_DAYS", 30))
    if max_age_days <= 0:
        return

    if not EVALS_REPORT_DIR.exists():
        return

    cutoff = time.time() - (max_age_days * 86400)
    removed = 0
    try:
        for f in EVALS_REPORT_DIR.iterdir():
            if f.is_file() and f.stat().st_mtime < cutoff:
                try:
                    f.unlink()
                    removed += 1
                except OSError as e:
                    logger.debug(f"[evals_cleanup] Failed to remove {f.name}: {e}")
        if removed > 0:
            logger.info(f"[evals_cleanup] Removed {removed} reports older than {max_age_days}d")
    except Exception as e:
        logger.opt(exception=True).error(f"[evals_cleanup] Job failed: {e}")
