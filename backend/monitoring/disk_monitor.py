"""G-04: Disk space monitoring — alerts when usage exceeds threshold."""

import psutil
from loguru import logger


async def disk_space_check_job():
    """Check disk usage and alert if above threshold."""
    from backend.config import settings
    from backend.core.scheduler import log_event

    alert_pct = getattr(settings, "DISK_USAGE_ALERT_PCT", 0.90)

    try:
        usage = psutil.disk_usage("/")
        used_pct = usage.percent / 100.0

        if used_pct >= alert_pct:
            msg = (
                f"DISK ALERT: usage {usage.percent:.1f}% >= {alert_pct:.0%} threshold "
                f"({usage.free / (1024**3):.1f} GB free of {usage.total / (1024**3):.1f} GB)"
            )
            logger.warning(msg)
            log_event("warning", msg)

            try:
                from backend.core.alert_manager import AlertManager
                from backend.db.utils import get_db_session

                with get_db_session() as db:
                    am = AlertManager(db)
                    am.send_alert("disk_space_warning", msg, severity="warning")
            except Exception:
                logger.debug("[disk_monitor] AlertManager notification skipped")
        else:
            logger.debug(
                "[disk_monitor] Disk usage OK: {:.1f}% ({:.1f} GB free)",
                usage.percent,
                usage.free / (1024**3),
            )
    except Exception as e:
        logger.warning("[disk_monitor] Disk check failed: {}", e)
