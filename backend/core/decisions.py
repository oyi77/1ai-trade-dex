"""
Decision logging helper for PolyEdge strategies.

Every strategy must call record_decision() for EVERY BUY/SKIP/SELL/HOLD/ERROR
evaluation — including skips. This creates the audit trail and ML training dataset.
"""
import json
import time
from datetime import datetime, timezone

from sqlalchemy.exc import OperationalError, PendingRollbackError

from backend.models.database import DecisionLog

from loguru import logger
_DB_LOCKED_MAX_RETRIES = 3
_DB_LOCKED_RETRY_DELAY = 0.5


def record_decision(
    db,
    strategy: str,
    market_ticker: str,
    decision: str,
    confidence: float | None = None,
    signal_data: dict | None = None,
    reason: str | None = None,
) -> DecisionLog | None:
    """
    Insert a DecisionLog row with automatic retry on SQLite lock contention.

    Args:
        db: SQLAlchemy Session
        strategy: strategy name (e.g. "copy_trader", "weather_emos")
        market_ticker: Polymarket market ticker or condition_id
        decision: one of BUY, SKIP, SELL, HOLD, ERROR
        confidence: float 0.0-1.0 or None
        signal_data: dict of inputs that drove the decision (JSON-serialized)
        reason: human-readable explanation

    Returns:
        The inserted DecisionLog instance, or None on failure.
    """
    signal_json: str | None = None
    if signal_data is not None:
        try:
            signal_json = json.dumps(signal_data)
        except (TypeError, ValueError):
            try:
                signal_json = json.dumps(signal_data, default=str)
            except Exception:
                logger.warning(
                    f"record_decision: could not serialize signal_data for "
                    f"{strategy}/{market_ticker} — storing as string repr"
                )
                signal_json = str(signal_data)

    for attempt in range(_DB_LOCKED_MAX_RETRIES):
        try:
            row = DecisionLog(
                strategy=strategy,
                market_ticker=market_ticker,
                decision=decision.upper(),
                confidence=confidence,
                signal_data=signal_json,
                reason=reason,
                created_at=datetime.now(timezone.utc),
            )
            db.add(row)
            db.flush()
            return row
        except PendingRollbackError as e:
            # Session is in DEACTIVE state due to a prior failed flush.
            # Rollback to recover the session, then return None — do not retry.
            logger.warning(
                f"record_decision: PendingRollbackError for {strategy}/{market_ticker}, "
                f"rolling back to recover session: {e}",
                extra={"component": "decisions"},
            )
            try:
                db.rollback()
            except Exception:
                logger.error(f"record_decision: rollback also failed for {strategy}/{market_ticker}")
            return None
        except OperationalError as e:
            if "database is locked" not in str(e).lower() or attempt >= _DB_LOCKED_MAX_RETRIES - 1:
                logger.warning(
                    f"record_decision: OperationalError for {strategy}/{market_ticker}, "
                    f"rolling back session: {e}",
                    extra={"component": "decisions"},
                )
                try:
                    db.rollback()
                except Exception:
                    logger.error(f"record_decision: rollback also failed for {strategy}/{market_ticker}")
                return None
            logger.info(
                f"record_decision: database locked for {strategy}/{market_ticker}, "
                f"retry {attempt + 1}/{_DB_LOCKED_MAX_RETRIES}"
            )
            try:
                db.rollback()
            except Exception:
                logger.exception("record_decision: failed to rollback after OperationalError")
                pass
            time.sleep(_DB_LOCKED_RETRY_DELAY)
        except Exception as e:
            logger.error(
                f"record_decision failed for {strategy}/{market_ticker}: {e}",
                extra={"component": "decisions"},
            )
            try:
                db.rollback()
            except Exception:
                logger.exception("record_decision: rollback failed after unhandled exception")
            return None
    return None


def record_decision_standalone(
    strategy: str,
    market_ticker: str,
    decision: str,
    confidence: float | None = None,
    signal_data: dict | None = None,
    reason: str | None = None,
    max_retries: int = 3,
    retry_delay: float = 0.1,
) -> DecisionLog | None:
    """
    Open own DB session, insert decision, commit immediately, close.
    Use for burst writes (e.g., 6 BTC 5-min markets in a loop)
    to avoid shared-session lock contention.

    Retries up to max_retries times on OperationalError (database locked).

    Returns:
        The inserted DecisionLog instance, or None on failure.
    """
    from backend.db.utils import get_db_session

    for attempt in range(max_retries):
        try:
            with get_db_session() as db:
                row = record_decision(db, strategy, market_ticker, decision, confidence, signal_data, reason)
                return row
        except OperationalError as e:
            logger.warning(
                f"record_decision_standalone: OperationalError on attempt {attempt+1}/{max_retries} "
                f"for {strategy}/{market_ticker}: {e}"
            )
            if attempt < max_retries - 1:
                time.sleep(retry_delay * (attempt + 1))
                continue
            return None
        except Exception as e:
            logger.error(f"record_decision_standalone failed for {strategy}/{market_ticker}: {e}")
            return None
    return None
