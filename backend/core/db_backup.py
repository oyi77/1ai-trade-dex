"""Database backup utility for protecting trading history.

Creates timestamped SQLite backups with configurable retention.
"""

import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from backend.config import settings

from loguru import logger

# Default backup settings
DEFAULT_BACKUP_DIR = "backups"
DEFAULT_RETENTION_DAYS = settings.DB_BACKUP_RETENTION_DAYS
MAX_BACKUPS = settings.DB_BACKUP_MAX_BACKUPS


def get_db_path() -> Optional[Path]:
    """Extract database file path from DATABASE_URL."""
    db_url = settings.DATABASE_URL
    if not db_url.startswith("sqlite"):
        logger.warning("Database backup only supported for SQLite databases")
        return None

    # Extract path from sqlite:///./tradingbot.db or sqlite:///tradingbot.db
    path_str = db_url.replace("sqlite:///", "").replace("./", "")
    return Path(path_str).resolve()


def get_backup_dir() -> Path:
    """Get or create the backup directory."""
    backup_dir = Path(getattr(settings, "DB_BACKUP_DIR", DEFAULT_BACKUP_DIR))
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def create_backup() -> Optional[Path]:
    """Create a timestamped backup of the SQLite database.

    Returns:
        Path to the backup file if successful, None otherwise.
    """
    db_path = get_db_path()
    if db_path is None:
        return None

    if not db_path.exists():
        logger.warning(f"Database file not found: {db_path}")
        return None

    backup_dir = get_backup_dir()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_name = f"tradingbot_{timestamp}.db"
    backup_path = backup_dir / backup_name

    try:
        # Use shutil.copy2 to preserve metadata
        shutil.copy2(db_path, backup_path)

        # Also backup WAL file if it exists (for consistency)
        wal_path = Path(str(db_path) + "-wal")
        if wal_path.exists():
            shutil.copy2(wal_path, backup_dir / f"tradingbot_{timestamp}.db-wal")

        logger.info(
            f"Database backup created: {backup_path} ({backup_path.stat().st_size / 1024:.1f} KB)"
        )
        return backup_path

    except Exception as e:
        logger.error(f"Failed to create database backup: {e}")
        return None


def cleanup_old_backups(retention_days: int = DEFAULT_RETENTION_DAYS) -> int:
    """Remove backups older than retention_days.

    Returns:
        Number of backups removed.
    """
    backup_dir = get_backup_dir()
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    removed = 0

    for backup_file in backup_dir.glob("tradingbot_*.db*"):
        try:
            # Parse timestamp from filename: tradingbot_YYYYMMDD_HHMMSS.db
            name = backup_file.stem
            if name.endswith("-wal") or name.endswith("-shm"):
                # Handle WAL/SHM files - extract timestamp before extension
                name = name.rsplit(".", 1)[0]

            parts = name.split("_")
            if len(parts) >= 3:
                date_str = f"{parts[1]}_{parts[2]}"
                backup_time = datetime.strptime(date_str, "%Y%m%d_%H%M%S").replace(
                    tzinfo=timezone.utc
                )

                if backup_time < cutoff:
                    backup_file.unlink()
                    logger.info(f"Removed old backup: {backup_file.name}")
                    removed += 1

        except (ValueError, IndexError) as e:
            logger.warning(
                f"Could not parse backup timestamp for {backup_file.name}: {e}"
            )
            continue

    return removed


def list_backups() -> list[dict]:
    """List all available backups with metadata.

    Returns:
        List of dicts with backup info (path, size, timestamp).
    """
    backup_dir = get_backup_dir()
    backups = []

    for backup_file in sorted(backup_dir.glob("tradingbot_*.db"), reverse=True):
        # Skip WAL files in listing
        if "-wal" in backup_file.name or "-shm" in backup_file.name:
            continue

        try:
            stat = backup_file.stat()
            backups.append(
                {
                    "path": str(backup_file),
                    "name": backup_file.name,
                    "size_kb": stat.st_size / 1024,
                    "created": datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc
                    ).isoformat(),
                }
            )
        except Exception as e:
            logger.warning(f"Could not stat backup {backup_file}: {e}")

    return backups[:MAX_BACKUPS]


async def backup_job() -> None:
    """Scheduled job to create a backup and cleanup old ones.

    Called by APScheduler on configured interval.
    """
    from backend.core.scheduler import log_event

    log_event("info", "Starting database backup job")

    try:
        # Create new backup
        backup_path = create_backup()
        if backup_path:
            log_event("success", f"Database backed up: {backup_path.name}")
        else:
            log_event("warning", "Database backup skipped (not SQLite or file missing)")
            return

        # Cleanup old backups
        retention_days = getattr(
            settings, "DB_BACKUP_RETENTION_DAYS", DEFAULT_RETENTION_DAYS
        )
        removed = cleanup_old_backups(retention_days)
        if removed > 0:
            log_event("info", f"Cleaned up {removed} old backup(s)")

        # Log current backup count
        backups = list_backups()
        log_event("info", f"Total backups available: {len(backups)}")

    except Exception as e:
        log_event("error", f"Database backup job failed: {e}")
        logger.exception("backup_job failed")


def restore_backup(backup_path: str) -> bool:
    """Restore database from a backup file.

    WARNING: This will overwrite the current database!

    Args:
        backup_path: Path to the backup file to restore.

    Returns:
        True if restore succeeded, False otherwise.
    """
    db_path = get_db_path()
    if db_path is None:
        return False

    backup_file = Path(backup_path)
    if not backup_file.exists():
        logger.error(f"Backup file not found: {backup_path}")
        return False

    try:
        # Create a safety backup of current DB before restore
        safety_backup = db_path.with_suffix(".pre_restore.bak")
        if db_path.exists():
            shutil.copy2(db_path, safety_backup)
            logger.info(f"Created safety backup: {safety_backup}")

        # Restore from backup
        shutil.copy2(backup_file, db_path)
        logger.info(f"Database restored from: {backup_path}")

        # Remove WAL files to force SQLite to use the restored DB cleanly
        wal_path = Path(str(db_path) + "-wal")
        shm_path = Path(str(db_path) + "-shm")
        if wal_path.exists():
            wal_path.unlink()
        if shm_path.exists():
            shm_path.unlink()

        return True

    except Exception as e:
        logger.error(f"Failed to restore database: {e}")
        return False
