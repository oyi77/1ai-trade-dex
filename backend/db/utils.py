import time
import logging
from contextlib import contextmanager
from backend.models.database import SessionLocal

logger = logging.getLogger(__name__)

@contextmanager
def get_db_session():
    db = SessionLocal()
    try:
        yield db
        for attempt in range(5):
            try:
                db.commit()
                return
            except Exception as commit_err:
                db.rollback()
                if "locked" in str(commit_err).lower() and attempt < 4:
                    time.sleep(0.3 * (2 ** attempt))
                    continue
                raise
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise
    finally:
        db.close()
