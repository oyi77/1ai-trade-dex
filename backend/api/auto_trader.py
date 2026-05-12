"""Auto-trader routes - pending approvals, approve/reject trades."""

from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timezone

from backend.models.database import PendingApproval
from backend.api.auth import require_admin
from loguru import logger
router = APIRouter(prefix="/auto-trader", tags=["auto_trader"])


@router.get("/pending")
async def list_pending_approvals():
    """List all pending trade approvals."""
    from backend.db.utils import get_db_session
    with get_db_session() as db:
            rows = (
                db.query(PendingApproval)
                .filter(PendingApproval.status == "pending")
                .order_by(PendingApproval.created_at.desc())
                .limit(100)
                .all()
            )
            return [
                {
                    "id": r.id,
                    "market_id": r.market_id,
                    "direction": r.direction,
                    "size": r.size,
                    "confidence": r.confidence,
                    "signal_data": r.signal_data,
                    "status": r.status,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]


@router.post("/approve/{trade_id}")
async def approve_pending_trade(trade_id: int, _admin=Depends(require_admin)):
    """Approve a pending trade."""
    from backend.db.utils import get_db_session
    with get_db_session() as db:
            row = db.query(PendingApproval).filter(PendingApproval.id == trade_id).first()
            if not row:
                raise HTTPException(status_code=404, detail="not found")
            row.status = "approved"
            row.decided_at = datetime.now(timezone.utc)
            db.commit()
            return {"id": row.id, "status": row.status}


@router.post("/reject/{trade_id}")
async def reject_pending_trade(trade_id: int, _admin=Depends(require_admin)):
    """Reject a pending trade."""
    from backend.db.utils import get_db_session
    with get_db_session() as db:
            row = db.query(PendingApproval).filter(PendingApproval.id == trade_id).first()
            if not row:
                raise HTTPException(status_code=404, detail="not found")
            row.status = "rejected"
            row.decided_at = datetime.now(timezone.utc)
            db.commit()
            return {"id": row.id, "status": row.status}


@router.post("/batch-approve")
async def batch_approve_trades(
    trade_ids: list[int],
    _admin=Depends(require_admin),
):
    """Batch approve multiple pending trades."""
    from backend.db.utils import get_db_session
    with get_db_session() as db:
            rows = (
                db.query(PendingApproval)
                .filter(
                    PendingApproval.id.in_(trade_ids),
                    PendingApproval.status == "pending",
                )
                .all()
            )
            now = datetime.now(timezone.utc)
            for row in rows:
                row.status = "approved"
                row.decided_at = now
            db.commit()
            return {
                "approved_count": len(rows),
                "approved_ids": [r.id for r in rows],
            }


@router.post("/batch-reject")
async def batch_reject_trades(
    trade_ids: list[int],
    _admin=Depends(require_admin),
):
    """Batch reject multiple pending trades."""
    from backend.db.utils import get_db_session
    with get_db_session() as db:
            rows = (
                db.query(PendingApproval)
                .filter(
                    PendingApproval.id.in_(trade_ids),
                    PendingApproval.status == "pending",
                )
                .all()
            )
            now = datetime.now(timezone.utc)
            for row in rows:
                row.status = "rejected"
                row.decided_at = now
            db.commit()
            return {
                "rejected_count": len(rows),
                "rejected_ids": [r.id for r in rows],
            }


@router.post("/clear-all")
async def clear_all_approvals(_admin=Depends(require_admin)):
    """Clear (reject) all pending approvals."""
    from backend.db.utils import get_db_session
    with get_db_session() as db:
            rows = (
                db.query(PendingApproval).filter(PendingApproval.status == "pending").all()
            )
            now = datetime.now(timezone.utc)
            for row in rows:
                row.status = "rejected"
                row.decided_at = now
            db.commit()
            return {
                "cleared_count": len(rows),
                "cleared_ids": [r.id for r in rows],
            }
