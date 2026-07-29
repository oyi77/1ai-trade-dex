"""Trade Attempt Control Room endpoints."""

from datetime import datetime
import json as _json

from fastapi import APIRouter, Depends
from sqlalchemy import func, text
from sqlalchemy.orm import Session
from loguru import logger

from backend.models.database import get_db, TradeAttempt


def _iso(dt) -> str | None:
    """Safely convert a datetime or string to ISO format.

    SQLite stores dates as strings, PostgreSQL as datetime objects.
    This handles both cases without crashing.
    """
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.isoformat()
    if isinstance(dt, str):
        return dt  # Already a string from SQLite
    return str(dt)


_ALLOWED_ATTEMPT_SORT = {
    "id",
    "created_at",
    "updated_at",
    "strategy",
    "mode",
    "market_ticker",
    "status",
    "phase",
    "reason_code",
    "confidence",
    "edge",
    "requested_size",
    "adjusted_size",
    "latency_ms",
}


def _parse_json_text(raw: str | None):
    if not raw:
        return None
    try:
        return _json.loads(raw)
    except Exception:
        logger.exception(
            "Failed to parse JSON in _parse_json_text, returning raw value"
        )
        return raw


def _attempt_to_dict(attempt: TradeAttempt) -> dict:
    return {
        "id": attempt.id,
        "attempt_id": attempt.attempt_id,
        "correlation_id": attempt.correlation_id,
        "created_at": _iso(attempt.created_at),
        "updated_at": _iso(attempt.updated_at),
        "strategy": attempt.strategy,
        "mode": attempt.mode,
        "market_ticker": attempt.market_ticker,
        "platform": attempt.platform,
        "direction": attempt.direction,
        "decision": attempt.decision,
        "status": attempt.status,
        "phase": attempt.phase,
        "reason_code": attempt.reason_code,
        "reason": attempt.reason,
        "confidence": attempt.confidence,
        "edge": attempt.edge,
        "requested_size": attempt.requested_size,
        "adjusted_size": attempt.adjusted_size,
        "entry_price": attempt.entry_price,
        "bankroll": attempt.bankroll,
        "current_exposure": attempt.current_exposure,
        "risk_allowed": attempt.risk_allowed,
        "risk_reason": attempt.risk_reason,
        "trade_id": attempt.trade_id,
        "order_id": attempt.order_id,
        "latency_ms": attempt.latency_ms,
        "factors": _parse_json_text(attempt.factors_json),
        "decision_data": _parse_json_text(attempt.decision_data),
        "signal_data": _parse_json_text(attempt.signal_data),
    }


router = APIRouter(tags=["trade_attempts"])


@router.get("/trade-attempts")
async def list_trade_attempts(
    mode: str | None = None,
    status: str | None = None,
    strategy: str | None = None,
    reason_code: str | None = None,
    market: str | None = None,
    since: str | None = None,
    until: str | None = None,
    sort: str = "created_at",
    order: str = "desc",
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """List trade execution attempts with operator-focused filtering."""
    if sort not in _ALLOWED_ATTEMPT_SORT:
        sort = "created_at"
    limit = max(1, min(limit, 500))
    offset = max(0, offset)

    query = db.query(TradeAttempt)
    if mode and mode != "all":
        query = query.filter(TradeAttempt.mode == mode)
    if status and status != "all":
        query = query.filter(TradeAttempt.status == status.upper())
    if strategy:
        query = query.filter(TradeAttempt.strategy == strategy)
    if reason_code:
        query = query.filter(TradeAttempt.reason_code == reason_code)
    if market:
        query = query.filter(TradeAttempt.market_ticker.contains(market))
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
            query = query.filter(TradeAttempt.created_at >= since_dt)
        except ValueError:
            logger.debug("Invalid trade-attempt since filter ignored: %s", since)
    if until:
        try:
            until_dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
            query = query.filter(TradeAttempt.created_at <= until_dt)
        except ValueError:
            logger.debug("Invalid trade-attempt until filter ignored: %s", until)

    total = query.count()
    col = getattr(TradeAttempt, sort, TradeAttempt.created_at)
    if order.lower() == "desc":
        col = col.desc()
    items = query.order_by(col).offset(offset).limit(limit).all()
    return {"items": [_attempt_to_dict(item) for item in items], "total": total}


@router.get("/trade-attempts/summary")
async def trade_attempts_summary(
    mode: str | None = None,
    db: Session = Depends(get_db),
):
    """Summarize current execution blockers for the Trade Control Room."""
    query = db.query(TradeAttempt)
    if mode and mode != "all":
        query = query.filter(TradeAttempt.mode == mode)

    total = query.count()
    executed = query.filter(TradeAttempt.status == "EXECUTED").count()
    blocked = query.filter(
        TradeAttempt.status.in_(["BLOCKED", "REJECTED", "FAILED"])
    ).count()

    by_status = [
        {"status": status, "count": count}
        for status, count in db.query(TradeAttempt.status, func.count(TradeAttempt.id))
        .filter(TradeAttempt.mode == mode if mode and mode != "all" else text("1=1"))
        .group_by(TradeAttempt.status)
        .order_by(func.count(TradeAttempt.id).desc())
        .all()
    ]
    by_mode = [
        {"mode": row_mode, "count": count}
        for row_mode, count in db.query(TradeAttempt.mode, func.count(TradeAttempt.id))
        .group_by(TradeAttempt.mode)
        .order_by(func.count(TradeAttempt.id).desc())
        .all()
    ]
    top_blockers = [
        {"reason_code": reason_code, "count": count}
        for reason_code, count in db.query(
            TradeAttempt.reason_code, func.count(TradeAttempt.id)
        )
        .filter(TradeAttempt.status.in_(["BLOCKED", "REJECTED", "FAILED"]))
        .filter(TradeAttempt.mode == mode if mode and mode != "all" else text("1=1"))
        .group_by(TradeAttempt.reason_code)
        .order_by(func.count(TradeAttempt.id).desc())
        .limit(8)
        .all()
    ]
    recent_blockers = (
        query.filter(TradeAttempt.status.in_(["BLOCKED", "REJECTED", "FAILED"]))
        .order_by(TradeAttempt.created_at.desc())
        .limit(5)
        .all()
    )
    latest = query.order_by(TradeAttempt.created_at.desc()).first()

    return {
        "total": total,
        "executed": executed,
        "blocked": blocked,
        "execution_rate": executed / total if total else 0.0,
        "last_attempt_at": (
            _iso(latest.created_at) if latest and latest.created_at else None
        ),
        "by_status": by_status,
        "by_mode": by_mode,
        "top_blockers": top_blockers,
        "recent_blockers": [_attempt_to_dict(item) for item in recent_blockers],
    }