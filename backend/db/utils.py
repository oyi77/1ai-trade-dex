import time
from contextlib import contextmanager
from backend.models.database import SessionLocal

from loguru import logger
from sqlalchemy.exc import OperationalError, PendingRollbackError
from backend.core.retry import retry


@retry(max_attempts=5, retryable_exceptions=(OperationalError,))
def _safe_commit(db) -> None:
    """Commit a session. Retries on OperationalError with rollback between attempts."""
    try:
        db.commit()
    except OperationalError:
        db.rollback()
        raise


@contextmanager
def get_db_session():
    db = SessionLocal()
    try:
        yield db
        try:
            _safe_commit(db)
        except PendingRollbackError:
            # Session is already in DEACTIVE state due to a prior failed flush.
            # The transaction is already rolled back — just exit cleanly without re-raising.
            try:
                db.rollback()
            except Exception:
                logger.exception(
                    "Failed to rollback session after PendingRollbackError"
                )
            return
    except Exception:
        logger.exception("db utils get_db_session failed")
        try:
            db.rollback()
        except Exception:
            logger.exception("db utils rollback also failed")
        raise
    finally:
        db.close()
