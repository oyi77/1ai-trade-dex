"""
Decision logging helper for PolyEdge strategies.

Every strategy must call record_decision() for EVERY BUY/SKIP/SELL/HOLD/ERROR
evaluation — including skips. This creates the audit trail and ML training dataset.
"""

import json
from datetime import datetime, timezone

from sqlalchemy.exc import OperationalError, PendingRollbackError, TimeoutError

from backend.models.database import DecisionLog
from backend.core.retry import retry

from loguru import logger


@retry(max_attempts=5, retryable_exceptions=(OperationalError, TimeoutError))
def _flush_decision(
    db,
    strategy: str,
    market_ticker: str,
    decision: str,
    confidence: float | None,
    signal_json: str | None,
    reason: str | None,
) -> DecisionLog:
    """DB-write portion: create + flush a DecisionLog row. Retried on lock/timeout."""
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
    except OperationalError:
        # Rollback to clear the session before the decorator retries
        try:
            db.rollback()
        except Exception:
            pass
        raise
    except TimeoutError:
        try:
            db.rollback()
        except Exception:
            pass
        raise


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

    try:
        return _flush_decision(
            db, strategy, market_ticker, decision, confidence, signal_json, reason
        )
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
            logger.exception(
                f"record_decision: rollback also failed for {strategy}/{market_ticker}"
            )
        return None
    except OperationalError as e:
        logger.warning(
            f"record_decision: OperationalError for {strategy}/{market_ticker} after retries, "
            f"rolling back session: {e}"
        )
        try:
            db.rollback()
        except Exception:
            logger.exception(
                f"record_decision: rollback also failed for {strategy}/{market_ticker}"
            )
        return None
    except TimeoutError as e:
        logger.warning(
            f"record_decision: TimeoutError for {strategy}/{market_ticker} after retries, "
            f"rolling back session: {e}"
        )
        try:
            db.rollback()
        except Exception:
            logger.exception(
                f"record_decision: rollback also failed for {strategy}/{market_ticker}"
            )
        return None
    except Exception as e:
        logger.error(f"record_decision failed for {strategy}/{market_ticker}: {e}")
        try:
            db.rollback()
        except Exception:
            logger.exception(
                "record_decision: rollback failed after unhandled exception"
            )
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
    """Open own DB session, insert decision, commit immediately, close.

    Use for burst writes (e.g., 6 BTC 5-min markets in a loop)
    to avoid shared-session lock contention.

    Retries up to max_retries times on OperationalError (database locked).

    Returns:
        The inserted DecisionLog instance, or None on failure.
    """
    from backend.db.utils import get_db_session

    @retry(max_attempts=max_retries, retryable_exceptions=(OperationalError, TimeoutError))
    def _insert_standalone() -> DecisionLog:
        with get_db_session() as db:
            row = record_decision(
                db,
                strategy,
                market_ticker,
                decision,
                confidence,
                signal_data,
                reason,
            )
            # Force the result so exceptions propagate out of the context manager
            if row is not None:
                return row
            raise OperationalError("record_decision returned None", {}, None)

    try:
        return _insert_standalone()
    except OperationalError:
        return None
    except Exception as e:
        logger.error(
            f"record_decision_standalone failed for {strategy}/{market_ticker}: {e}"
        )
        return None
