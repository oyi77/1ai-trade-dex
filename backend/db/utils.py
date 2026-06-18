import time
from contextlib import contextmanager
from datetime import datetime, timezone
from backend.models.database import SessionLocal

from loguru import logger
from sqlalchemy.exc import OperationalError, PendingRollbackError
from backend.core.retry import retry


def utcnow() -> datetime:
    """Return a naive UTC datetime for DB column writes.

    All DB DateTime columns are naive (no tzinfo). Using tz-aware
    datetimes causes comparison mismatches and DetachedInstanceError
    on attribute access after session close.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


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


@contextmanager
def get_db_read_session():
    """Read-only session: yields session, then commits (no-op for reads) to
    ensure the transaction is closed and the connection is returned to the pool.

    This prevents idle-in-transaction leaks from read-only queries that never
    explicitly commit, leaving the connection stuck in a transaction state.
    """
    db = SessionLocal()
    try:
        yield db
        # Commit even for read-only to close the transaction and release the connection
        try:
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise
    finally:
        db.close()
