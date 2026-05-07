"""Activity logging backend for strategy decisions.

Logs all strategy decisions (entry/exit/hold/adjustment) to the ActivityLog table
with thread-safe writes and automatic retention policy enforcement.
"""

import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, PendingRollbackError

from backend.models.database import SessionLocal, ActivityLog
from backend.core.config_service import get_setting

logger = logging.getLogger(__name__)

# SQLite retry configuration for cross-process database lock contention
# Uses exponential backoff to handle database locks between polyedge-bot and polyedge-api PM2 processes


class ActivityLogger:
    """Thread-safe activity logger for strategy decisions."""

    def __init__(self):
        """Initialize the activity logger."""
        pass

    def log_entry(
        self,
        strategy_name: str,
        decision_type: str,
        data: Dict[str, Any],
        confidence: float,
        mode: str = "paper",
        db: Optional[Session] = None
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
            # Retry with exponential backoff for cross-process database lock contention
            max_retries = 3
            base_delay_ms = 200

            for attempt in range(max_retries):
                try:
                    activity = ActivityLog(
                        timestamp=datetime.now(timezone.utc),
                        strategy_name=strategy_name,
                        decision_type=decision_type,
                        data=data,
                        confidence_score=confidence,
                        mode=mode
                    )
                    db.add(activity)
                    db.commit()
                    db.refresh(activity)

                    logger.debug(
                        f"ActivityLogger: Logged {decision_type} for {strategy_name} "
                        f"(confidence={confidence:.2f}, mode={mode}, id={activity.id})"
                    )
                    return activity.id
                except (OperationalError, PendingRollbackError):
                    # Only retry OperationalError (database locked) or PendingRollbackError
                    # not other errors
                    if attempt < max_retries - 1:
                        # Rollback to clear the session state before retrying
                        db.rollback()
                        delay_ms = base_delay_ms * (2 ** attempt)
                        logger.warning(
                            f"ActivityLogger: Database locked, retrying in {delay_ms}ms "
                            f"(attempt {attempt + 1}/{max_retries})"
                        )
                        time.sleep(delay_ms / 1000)
                        continue
                    else:
                        # Re-raise if out of retries
                        raise
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
        db: Optional[Session] = None
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
                result.append({
                    "id": activity.id,
                    "timestamp": activity.timestamp.isoformat(),
                    "strategy_name": activity.strategy_name,
                    "decision_type": activity.decision_type,
                    "data": activity.data,
                    "confidence_score": activity.confidence_score,
                    "mode": activity.mode
                })

            return result
        except Exception as e:
            logger.error(f"ActivityLogger: Failed to retrieve activities: {e}", exc_info=True)
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
            retention_days = get_setting("ACTIVITY_LOG_RETENTION_DAYS", default=90, db=db)

            cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

            # Retry with exponential backoff for cross-process database lock contention
            max_retries = 3
            base_delay_ms = 200

            for attempt in range(max_retries):
                try:
                    deleted = db.query(ActivityLog).filter(
                        ActivityLog.timestamp < cutoff
                    ).delete()
                    db.commit()

                    if deleted > 0:
                        logger.info(
                            f"ActivityLogger: Cleaned up {deleted} activity logs "
                            f"older than {retention_days} days"
                        )

                    return deleted
                except (OperationalError, PendingRollbackError):
                    # Only retry OperationalError (database locked) or PendingRollbackError
                    # not other errors
                    if attempt < max_retries - 1:
                        # Rollback to clear the session state before retrying
                        db.rollback()
                        delay_ms = base_delay_ms * (2 ** attempt)
                        logger.warning(
                            f"ActivityLogger: Database locked during cleanup, retrying in {delay_ms}ms "
                            f"(attempt {attempt + 1}/{max_retries})"
                        )
                        time.sleep(delay_ms / 1000)
                        continue
                    else:
                        # Re-raise if out of retries
                        raise
        except Exception as e:
            logger.error(f"ActivityLogger: Failed to cleanup old activities: {e}", exc_info=True)
            db.rollback()
            return 0
        finally:
            if should_close:
                db.close()


# Global singleton instance
activity_logger = ActivityLogger()
