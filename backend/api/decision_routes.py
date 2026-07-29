"""Decision log endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from datetime import datetime
from sqlalchemy.orm import Session
import json as _json

from backend.models.database import get_db, DecisionLog
from loguru import logger

router = APIRouter(tags=["decisions"])

_ALLOWED_DECISION_SORT = {
    "id",
    "created_at",
    "strategy",
    "market_ticker",
    "confidence",
    "decision",
}


@router.get("/decisions")
async def list_decisions(
    strategy: str | None = None,
    decision: str | None = None,
    market: str | None = None,
    since: str | None = None,
    until: str | None = None,
    sort: str = "created_at",
    order: str = "desc",
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """List decision log entries with filtering."""
    if sort not in _ALLOWED_DECISION_SORT:
        sort = "created_at"
    limit = min(limit, 500)
    query = db.query(DecisionLog)
    if strategy:
        query = query.filter(DecisionLog.strategy == strategy)
    if decision:
        query = query.filter(DecisionLog.decision == decision.upper())
    if market:
        query = query.filter(DecisionLog.market_ticker.contains(market))
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
            query = query.filter(DecisionLog.created_at >= since_dt)
        except ValueError as e:
            logger.debug(f"Strategy status check error: {e}")
    if until:
        try:
            until_dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
            query = query.filter(DecisionLog.created_at <= until_dt)
        except ValueError as e:
            logger.debug(f"Strategy status check error: {e}")
    total = query.count()
    col = getattr(DecisionLog, sort, DecisionLog.created_at)
    if order == "desc":
        col = col.desc()
    items = query.order_by(col).offset(offset).limit(limit).all()

    def _parse_signal_data(raw):
        if not raw:
            return None
        try:
            return _json.loads(raw)
        except Exception:
            logger.exception("Failed to parse signal_data JSON in list_decisions")
            return raw

    return {
        "items": [
            {
                "id": d.id,
                "strategy": d.strategy,
                "market_ticker": d.market_ticker,
                "decision": d.decision,
                "confidence": d.confidence,
                "reason": d.reason,
                "outcome": d.outcome,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "signal_data": _parse_signal_data(d.signal_data),
            }
            for d in items
        ],
        "total": total,
    }


@router.get("/decisions/export")
async def export_decisions(
    format: str = "jsonl",
    strategy: str | None = None,
    decision: str | None = None,
    limit: int = 10000,
    db: Session = Depends(get_db),
):
    """Export decision log as JSONL for ML training."""
    limit = min(limit, 5000)

    query = db.query(DecisionLog)
    if strategy:
        query = query.filter(DecisionLog.strategy == strategy)
    if decision:
        query = query.filter(DecisionLog.decision == decision.upper())
    items = query.order_by(DecisionLog.created_at.desc()).limit(limit).all()

    def generate():
        for d in items:
            signal_data = None
            if d.signal_data:
                try:
                    signal_data = _json.loads(d.signal_data)
                except Exception:
                    logger.exception(
                        f"Failed to parse signal_data for decision export {d.id}"
                    )
                    signal_data = d.signal_data
            row = {
                "id": d.id,
                "strategy": d.strategy,
                "market_ticker": d.market_ticker,
                "decision": d.decision,
                "confidence": d.confidence,
                "signal_data": signal_data,
                "reason": d.reason,
                "outcome": d.outcome,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            yield _json.dumps(row) + "\n"

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": "attachment; filename=decisions.jsonl"},
    )


@router.get("/decisions/{decision_id}")
async def get_decision(
    decision_id: int,
    db: Session = Depends(get_db),
):
    """Get a single decision log entry by ID."""
    if decision_id < 0 or decision_id > 2**63 - 1:
        raise HTTPException(status_code=400, detail="Invalid decision_id")
    decision = db.query(DecisionLog).filter(DecisionLog.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    signal_data = None
    if decision.signal_data:
        try:
            signal_data = _json.loads(decision.signal_data)
        except Exception:
            logger.exception(f"Failed to parse signal_data for decision {decision_id}")
            signal_data = decision.signal_data

    return {
        "id": decision.id,
        "strategy": decision.strategy,
        "market_ticker": decision.market_ticker,
        "decision": decision.decision,
        "confidence": decision.confidence,
        "signal_data": signal_data,
        "reason": decision.reason,
        "outcome": decision.outcome,
        "created_at": decision.created_at.isoformat() if decision.created_at else None,
    }