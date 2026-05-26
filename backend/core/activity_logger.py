"""Activity logging backend for strategy decisions.

Logs all strategy decisions (entry/exit/hold/adjustment) to the ActivityLog table
with thread-safe writes and automatic retention policy enforcement.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from loguru import logger

from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, PendingRollbackError

from backend.models.database import SessionLocal, ActivityLog
from backend.core.config_service import get_setting
from backend.core.retry import retry

# SQLite retry configuration for cross-process database lock contention
# Uses exponential backoff to handle database locks between polyedge-bot and polyedge-api PM2 processes


@retry(max_attempts=3)
def _write_activity(db: Session, activity: ActivityLog) -> int:
    """Write an ActivityLog row + commit. Retried on transient DB errors."""
    try:
        db.add(activity)
        db.commit()
        db.refresh(activity)
        return activity.id
    except (OperationalError, PendingRollbackError):
        try:
            db.rollback()
        except Exception:
            logger.debug("activity_logger: db rollback failed after OperationalError")
        raise


@retry(max_attempts=3)
def _delete_old_activities(db: Session, cutoff: datetime) -> int:
    """Delete ActivityLog rows older than cutoff + commit. Retried on transient DB errors."""
    try:
        deleted = (
            db.query(ActivityLog)
            .filter(ActivityLog.timestamp < cutoff)
            .delete()
        )
        db.commit()
        return deleted
    except (OperationalError, PendingRollbackError):
        try:
            db.rollback()
        except Exception:
            logger.debug("activity_logger: db rollback failed in delete")
        raise


class ActivityLogger:
    """Thread-safe activity logger for strategy decisions."""

    def __init__(self):
        """No-op activity logger. Override in subclass for real logging."""
        pass

    def log_entry(
        self,
        strategy_name: str,
        decision_type: str,
        data: Dict[str, Any],
        confidence: float,
        mode: str = "paper",
        db: Optional[Session] = None,
    ) -> Optional[int]:
        """
        Log a strategy decision to the database.

        Args:
            strategy_name: Name of the strategy (e.g., 'btc_momentum', 'btc_oracle')
            decision_type: Type of decision ('entry', 'exit', 'hold', 'adjustment')
            data: Full decision context (price, indicators, market info, etc.)
            confidence: Confidence score (0.0-1.0)
            mode: Trading mode ('paper' or 'live')
            db: Optional database session (creates new if None)

        Returns:
            Activity log ID if successful, None otherwise
        """
        should_close = False
        if db is None:
            db = SessionLocal()
            should_close = True

        try:
            activity = ActivityLog(
                timestamp=datetime.now(timezone.utc),
                strategy_name=strategy_name,
                decision_type=decision_type,
                data=data,
                confidence_score=confidence,
                mode=mode,
            )
            activity_id = _write_activity(db, activity)

            logger.debug(
                f"ActivityLogger: Logged {decision_type} for {strategy_name} "
                f"(confidence={confidence:.2f}, mode={mode}, id={activity_id})"
            )
            return activity_id
        except (OperationalError, PendingRollbackError):
            db.rollback()
            logger.warning(
                f"ActivityLogger: write failed after retries for {strategy_name}/{decision_type}"
            )
            return None
        except Exception as e:
            logger.error(f"ActivityLogger: Failed to log activity: {e}", exc_info=True)
            db.rollback()
            return None
        finally:
            if should_close:
                db.close()

    def get_activities(
        self,
        limit: int = 100,
        strategy: Optional[str] = None,
        days: Optional[int] = None,
        db: Optional[Session] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve activity logs with optional filtering.

        Args:
            limit: Maximum number of records to return (default 100)
            strategy: Filter by strategy name (optional)
            days: Filter to last N days (optional)
            db: Optional database session (creates new if None)

        Returns:
            List of activity log dictionaries
        """
        should_close = False
        if db is None:
            db = SessionLocal()
            should_close = True

        try:
            query = db.query(ActivityLog)

            # Apply filters
            if strategy:
                query = query.filter(ActivityLog.strategy_name == strategy)

            if days:
                cutoff = datetime.now(timezone.utc) - timedelta(days=days)
                query = query.filter(ActivityLog.timestamp >= cutoff)

            # Order by timestamp descending (newest first)
            query = query.order_by(ActivityLog.timestamp.desc())

            # Apply limit
            query = query.limit(limit)

            activities = query.all()

            # Convert to dictionaries
            result = []
            for activity in activities:
                result.append(
                    {
                        "id": activity.id,
                        "timestamp": activity.timestamp.isoformat(),
                        "strategy_name": activity.strategy_name,
                        "decision_type": activity.decision_type,
                        "data": activity.data,
                        "confidence_score": activity.confidence_score,
                        "mode": activity.mode,
                    }
                )

            return result
        except Exception as e:
            logger.error(
                f"ActivityLogger: Failed to retrieve activities: {e}", exc_info=True
            )
            return []
        finally:
            if should_close:
                db.close()

    def cleanup_old_activities(self, db: Optional[Session] = None) -> int:
        """
        Delete activity logs older than ACTIVITY_LOG_RETENTION_DAYS.

        Args:
            db: Optional database session (creates new if None)

        Returns:
            Number of records deleted
        """
        should_close = False
        if db is None:
            db = SessionLocal()
            should_close = True

        try:
            # Get retention policy from settings (default 90 days)
            retention_days = get_setting(
                "ACTIVITY_LOG_RETENTION_DAYS", default=90, db=db
            )

            cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

            deleted = _delete_old_activities(db, cutoff)

            if deleted > 0:
                logger.info(
                    f"ActivityLogger: Cleaned up {deleted} activity logs "
                    f"older than {retention_days} days"
                )
            return deleted
        except (OperationalError, PendingRollbackError):
            db.rollback()
            logger.warning(
                "ActivityLogger: cleanup failed after retries"
            )
            return 0
        except Exception as e:
            logger.error(
                f"ActivityLogger: Failed to cleanup old activities: {e}", exc_info=True
            )
            db.rollback()
            return 0
        finally:
            if should_close:
                db.close()


# Global singleton instance
activity_logger = ActivityLogger()
