import time
from contextlib import contextmanager
from backend.models.database import SessionLocal

from loguru import logger
from sqlalchemy.exc import PendingRollbackError


@contextmanager
def get_db_session():
    db = SessionLocal()
    try:
        yield db
        for attempt in range(5):
            try:
                db.commit()
                return
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
            except Exception as commit_err:
                db.rollback()
                if "locked" in str(commit_err).lower() and attempt < 4:
                    time.sleep(0.3 * (2**attempt))
                    continue
                raise
    except Exception:
        logger.exception("db utils get_db_session failed")
        try:
            db.rollback()
        except Exception:
            logger.exception("db utils rollback also failed")
        raise
    finally:
        db.close()
