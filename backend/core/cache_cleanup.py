"""Cache and storage cleanup jobs for maintenance.

Handles:
- Expired cache entries (hourly)
- Old WebSocket messages (>24h)
- Old logs (>7 days)
- Old backups (>30 days, keep weekly)
- Disk space monitoring
"""

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any

from loguru import logger


class CleanupStats:
    """Track cleanup operation statistics."""

    def __init__(self):
        self.cache_entries_removed = 0
        self.websocket_messages_removed = 0
        self.log_files_removed = 0
        self.backup_files_removed = 0
        self.space_freed_mb = 0.0
        self.disk_free_percent = 0.0
        self.timestamp = utcnow().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "cache_entries_removed": self.cache_entries_removed,
            "websocket_messages_removed": self.websocket_messages_removed,
            "log_files_removed": self.log_files_removed,
            "backup_files_removed": self.backup_files_removed,
            "space_freed_mb": round(self.space_freed_mb, 2),
            "disk_free_percent": round(self.disk_free_percent, 1),
            "timestamp": self.timestamp,
        }


async def cleanup_cache_entries() -> int:
    """Clean expired cache entries from SQLite cache.

    Returns:
        Number of entries removed
    """
    try:
        from backend.cache.abstract import create_cache

        cache = create_cache()
        if not hasattr(cache, "cleanup_expired"):
            logger.debug("Cache backend does not support cleanup_expired")
            return 0

        removed = await cache.cleanup_expired()
        logger.info(f"Cache cleanup: removed {removed} expired entries")
        return removed
    except Exception as e:
        logger.error(f"Cache cleanup failed: {e}")
        return 0


async def cleanup_websocket_messages(max_age_hours: int = 24) -> int:
    """Clean old WebSocket messages from database.

    Args:
        max_age_hours: Remove messages older than this many hours

    Returns:
        Number of messages removed
    """
    try:
        from backend.models.database import WebSocketMessage

        from backend.db.utils import get_db_session

        with get_db_session() as db:
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

            # Query old messages
            old_messages = (
                db.query(WebSocketMessage)
                .filter(WebSocketMessage.created_at < cutoff_time)
                .all()
            )

            count = len(old_messages)
            if count > 0:
                for msg in old_messages:
                    db.delete(msg)
                db.commit()
                logger.info(
                    f"WebSocket cleanup: removed {count} messages older than {max_age_hours}h"
                )

            return count
    except Exception as e:
        logger.error(f"WebSocket message cleanup failed: {e}")
        return 0


async def cleanup_log_files(max_age_days: int = 7, log_dir: str = "logs") -> int:
    """Clean old log files from disk.

    Args:
        max_age_days: Remove files older than this many days
        log_dir: Directory containing log files

    Returns:
        Number of files removed
    """
    try:
        log_path = Path(log_dir)
        if not log_path.exists():
            logger.debug(f"Log directory does not exist: {log_dir}")
            return 0

        cutoff_time = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        cutoff_timestamp = cutoff_time.timestamp()

        removed = 0
        for log_file in log_path.glob("*.log"):
            try:
                file_mtime = log_file.stat().st_mtime
                if file_mtime < cutoff_timestamp:
                    log_file.unlink()
                    removed += 1
                    logger.debug(f"Removed old log file: {log_file.name}")
            except Exception as e:
                logger.warning(f"Failed to remove log file {log_file.name}: {e}")

        if removed > 0:
            logger.info(
                f"Log cleanup: removed {removed} files older than {max_age_days} days"
            )

        return removed
    except Exception as e:
        logger.error(f"Log file cleanup failed: {e}")
        return 0


async def cleanup_backup_files(
    max_age_days: int = 30, backup_dir: str = "backups", keep_weekly: bool = True
) -> int:
    """Clean old backup files, keeping weekly backups.

    Args:
        max_age_days: Remove files older than this many days
        backup_dir: Directory containing backup files
        keep_weekly: If True, keep one backup per week

    Returns:
        Number of files removed
    """
    try:
        backup_path = Path(backup_dir)
        if not backup_path.exists():
            logger.debug(f"Backup directory does not exist: {backup_dir}")
            return 0

        cutoff_time = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        cutoff_timestamp = cutoff_time.timestamp()

        # Group backups by week if keeping weekly
        backups_by_week: Dict[int, list] = {}
        old_backups = []

        for backup_file in sorted(backup_path.glob("*.db*")):
            try:
                file_mtime = backup_file.stat().st_mtime
                file_time = datetime.fromtimestamp(file_mtime, tz=timezone.utc)

                if file_mtime < cutoff_timestamp:
                    if keep_weekly:
                        # Group by ISO week number
                        week_num = file_time.isocalendar()[1]
                        if week_num not in backups_by_week:
                            backups_by_week[week_num] = []
                        backups_by_week[week_num].append(backup_file)
                    else:
                        old_backups.append(backup_file)
            except Exception as e:
                logger.warning(f"Failed to process backup file {backup_file.name}: {e}")

        removed = 0

        # Remove old backups, keeping one per week
        if keep_weekly:
            for week_num, files in backups_by_week.items():
                # Keep the most recent backup from each week
                for backup_file in sorted(files)[:-1]:
                    try:
                        backup_file.unlink()
                        removed += 1
                        logger.debug(f"Removed old backup: {backup_file.name}")
                    except Exception as e:
                        logger.warning(
                            f"Failed to remove backup {backup_file.name}: {e}"
                        )
        else:
            for backup_file in old_backups:
                try:
                    backup_file.unlink()
                    removed += 1
                    logger.debug(f"Removed old backup: {backup_file.name}")
                except Exception as e:
                    logger.warning(f"Failed to remove backup {backup_file.name}: {e}")

        if removed > 0:
            logger.info(
                f"Backup cleanup: removed {removed} files older than {max_age_days} days "
                f"(keeping weekly: {keep_weekly})"
            )

        return removed
    except Exception as e:
        logger.error(f"Backup file cleanup failed: {e}")
        return 0


async def check_disk_space(alert_threshold_percent: float = 10.0) -> Dict[str, Any]:
    """Check disk space and alert if low.

    Args:
        alert_threshold_percent: Alert if free space below this percentage

    Returns:
        Dictionary with disk space metrics
    """
    try:
        # Get disk usage for current directory
        stat = shutil.disk_usage(".")

        total_gb = stat.total / (1024**3)
        used_gb = stat.used / (1024**3)
        free_gb = stat.free / (1024**3)
        free_percent = (stat.free / stat.total) * 100

        metrics = {
            "total_gb": round(total_gb, 2),
            "used_gb": round(used_gb, 2),
            "free_gb": round(free_gb, 2),
            "free_percent": round(free_percent, 1),
            "alert": free_percent < alert_threshold_percent,
        }

        if metrics["alert"]:
            logger.warning(
                f"Low disk space: {free_gb:.2f}GB free ({free_percent:.1f}%) - "
                f"below {alert_threshold_percent}% threshold"
            )
        else:
            logger.debug(f"Disk space OK: {free_gb:.2f}GB free ({free_percent:.1f}%)")

        return metrics
    except Exception as e:
        logger.error(f"Disk space check failed: {e}")
        return {
            "total_gb": 0,
            "used_gb": 0,
            "free_gb": 0,
            "free_percent": 0,
            "alert": True,
            "error": str(e),
        }


async def run_cleanup_cycle() -> CleanupStats:
    """Run complete cleanup cycle.

    Returns:
        CleanupStats with operation results
    """
    stats = CleanupStats()

    logger.info("Starting cleanup cycle...")

    # Clean cache entries (hourly)
    stats.cache_entries_removed = await cleanup_cache_entries()

    # Clean WebSocket messages (>24h)
    stats.websocket_messages_removed = await cleanup_websocket_messages(
        max_age_hours=24
    )

    # Clean logs (>7 days)
    stats.log_files_removed = await cleanup_log_files(max_age_days=7, log_dir="logs")

    # Clean backups (>30 days, keep weekly)
    stats.backup_files_removed = await cleanup_backup_files(
        max_age_days=30, backup_dir="backups", keep_weekly=True
    )

    # Check disk space
    disk_metrics = await check_disk_space(alert_threshold_percent=10.0)
    stats.disk_free_percent = disk_metrics.get("free_percent", 0)

    # Calculate space freed (rough estimate from file removals)
    # In production, track actual file sizes
    stats.space_freed_mb = (
        stats.log_files_removed * 5  # Assume ~5MB per log file
        + stats.backup_files_removed * 50  # Assume ~50MB per backup
    )

    logger.info(f"Cleanup cycle complete: {stats.to_dict()}")

    return stats


# Job function for scheduler
async def cache_cleanup_job():
    """APScheduler job for cache cleanup."""
    try:
        stats = await run_cleanup_cycle()

        from backend.core.scheduler import log_event

        log_event("success", "Cache cleanup completed", stats.to_dict())
    except Exception as e:
        logger.error(f"Cache cleanup job failed: {e}", exc_info=True)
        from backend.core.scheduler import log_event

        log_event("error", f"Cache cleanup failed: {e}")
