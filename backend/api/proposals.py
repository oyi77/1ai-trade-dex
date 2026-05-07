"""API endpoints for strategy proposal management."""

import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.models.database import get_db, StrategyProposal as DBProposal, Trade
from backend.api.auth import require_admin
from backend.ai.proposal_generator import ProposalGenerator
from backend.api_websockets.proposals import broadcast_proposal_update
from backend.api.validation import (
    ProposalCreateRequest as ValidatedProposalCreate,
    ProposalApprovalRequest as ValidatedProposalApproval,
)
from backend.ai.impact_measurer import ImpactMeasurer
from backend.services.rollback_manager import RollbackManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/proposals", tags=["proposals"])


class ProposalResponse(BaseModel):
    id: int
    strategy_name: str
    change_details: dict
    expected_impact: str
    admin_decision: str
    status: Optional[str] = None
    auto_promotable: Optional[bool] = None
    backtest_passed: Optional[bool] = None
    backtest_sharpe: Optional[float] = None
    backtest_win_rate: Optional[float] = None
    proposed_params: Optional[dict] = None
    created_at: str
    executed_at: Optional[str] = None


class ApprovalRequest(BaseModel):
    admin_user_id: str
    reason: str = Field(..., min_length=1, description="Reason must not be empty")


class CreateProposalRequest(BaseModel):
    strategy_name: str
    change_details: dict
    expected_impact: float


@router.get("", response_model=List[ProposalResponse])
async def list_proposals(
    status: Optional[str] = "pending",
    db: Session = Depends(get_db)
):
    """List strategy proposals filtered by status.

    Query params:
        status: Filter by admin_decision status (pending, approved, rejected)
    """
    query = db.query(DBProposal)

    if status:
        query = query.filter(DBProposal.admin_decision == status)

    proposals = query.order_by(DBProposal.created_at.desc()).all()

    return [
        ProposalResponse(
            id=p.id,
            strategy_name=p.strategy_name,
            change_details=p.change_details,
            expected_impact=p.expected_impact,
            admin_decision=p.admin_decision,
            status=p.status,
            auto_promotable=p.auto_promotable,
            backtest_passed=p.backtest_passed,
            backtest_sharpe=p.backtest_sharpe,
            backtest_win_rate=p.backtest_win_rate,
            proposed_params=p.proposed_params,
            created_at=p.created_at.isoformat() if p.created_at else "",
            executed_at=p.executed_at.isoformat() if p.executed_at else None
        )
        for p in proposals
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_proposal(
    request: ValidatedProposalCreate,
    db: Session = Depends(get_db),
    _admin: None = Depends(require_admin),
):
    """Create a new strategy proposal."""
    from datetime import datetime, timezone

    proposal = DBProposal(
        strategy_name=request.strategy_name,
        change_details=request.change_details,
        expected_impact=request.expected_impact,
        admin_decision="pending",
        created_at=datetime.now(timezone.utc)
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)

    return ProposalResponse(
        id=proposal.id,
        strategy_name=proposal.strategy_name,
        change_details=proposal.change_details,
        expected_impact=proposal.expected_impact,
        admin_decision=proposal.admin_decision,
        created_at=proposal.created_at.isoformat() if proposal.created_at else "",
        executed_at=proposal.executed_at.isoformat() if proposal.executed_at else None
    )


@router.post("/{proposal_id}/approve", status_code=status.HTTP_200_OK)
async def approve_proposal(
    proposal_id: int,
    request: ValidatedProposalApproval,
    db: Session = Depends(get_db),
    _admin: dict = Depends(require_admin)
):
    """Approve a strategy proposal (admin only).

    Requires admin authentication. Returns 403 if called by non-admin.
    """
    generator = ProposalGenerator()

    success = generator.approve_proposal(
        proposal_id,
        request.admin_user_id,
        request.reason
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proposal {proposal_id} not found or already processed"
        )

    proposal = db.query(DBProposal).filter(DBProposal.id == proposal_id).first()
    if proposal:
        await broadcast_proposal_update({
            "id": proposal.id,
            "strategy_name": proposal.strategy_name,
            "admin_decision": proposal.admin_decision,
            "admin_user_id": proposal.admin_user_id,
        })

    return {"status": "approved", "proposal_id": proposal_id}


@router.post("/{proposal_id}/reject", status_code=status.HTTP_200_OK)
async def reject_proposal(
    proposal_id: int,
    request: ValidatedProposalApproval,
    db: Session = Depends(get_db),
    _admin: dict = Depends(require_admin)
):
    """Reject a strategy proposal (admin only).

    Requires admin authentication. Returns 403 if called by non-admin.
    """
    generator = ProposalGenerator()

    success = generator.reject_proposal(
        proposal_id,
        request.admin_user_id,
        request.reason
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proposal {proposal_id} not found or already processed"
        )

    proposal = db.query(DBProposal).filter(DBProposal.id == proposal_id).first()
    if proposal:
        await broadcast_proposal_update({
            "id": proposal.id,
            "strategy_name": proposal.strategy_name,
            "admin_decision": proposal.admin_decision,
            "admin_user_id": proposal.admin_user_id,
        })

    return {"status": "rejected", "proposal_id": proposal_id}


@router.post("/generate", status_code=status.HTTP_201_CREATED)
async def generate_proposal(
    db: Session = Depends(get_db),
    _admin: dict = Depends(require_admin)
):
    """Generate a new strategy proposal from recent trades (admin only).

    Analyzes the last 20 trades and uses Claude API to generate improvement proposal.
    """
    recent_trades = db.query(Trade).order_by(Trade.timestamp.desc()).limit(20).all()

    if not recent_trades:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No trades available for analysis"
        )

    generator = ProposalGenerator()
    proposal = await generator.generate_proposal(recent_trades)

    if not proposal:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate proposal"
        )

    return {
        "status": "created",
        "strategy_name": proposal.strategy_name,
        "change_type": proposal.change_type,
        "confidence": proposal.confidence
    }


@router.get("/{proposal_id}/impact")
async def get_proposal_impact(
    proposal_id: int,
    db: Session = Depends(get_db)
):
    """Get impact metrics for an executed proposal."""
    measurer = ImpactMeasurer()
    impact_data = measurer.get_proposal_impact(proposal_id)

    if not impact_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No impact data found for proposal {proposal_id}"
        )

    return impact_data


@router.post("/{proposal_id}/rollback", status_code=status.HTTP_200_OK)
async def rollback_proposal(
    proposal_id: int,
    db: Session = Depends(get_db),
    _admin: dict = Depends(require_admin)
):
    """Rollback a proposal to restore previous strategy config (admin only)."""
    rollback_mgr = RollbackManager()

    if not rollback_mgr.can_rollback(proposal_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Proposal {proposal_id} cannot be rolled back (not approved or no snapshot)"
        )

    success = rollback_mgr.rollback_proposal(proposal_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to rollback proposal {proposal_id}"
        )

    return {
        "status": "rolled_back",
        "proposal_id": proposal_id,
        "message": "Strategy configuration restored to previous state"
    }


@router.websocket("/ws")
async def proposals_websocket(websocket: WebSocket):
    """WebSocket endpoint for real-time proposal updates."""
    from backend.api.ws_manager_v2 import topic_manager

    await websocket.accept()

    try:
        data = await websocket.receive_json()
        if data.get("action") == "subscribe":
            topic = data.get("topic", "proposals")
            await topic_manager.subscribe(websocket, topic)
            await websocket.send_json({"type": "subscribed", "topic": topic})

        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await topic_manager.disconnect(websocket)
