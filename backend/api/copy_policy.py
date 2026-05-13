from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session

from backend.models.database import get_db
from backend.models.trading_wallet import CopyPolicy
from backend.api.auth import require_admin

router = APIRouter(prefix="/copy-policy", tags=["copy_policy"])

class CopyPolicyCreate(BaseModel):
    source_name: str
    enabled: bool = True
    max_size_usd: float = 50.0
    confidence_floor: float = 0.6
    max_delay_seconds: int = 30
    size_scale_factor: float = 1.0
    cooldown_seconds: int = 60

class CopyPolicyUpdate(BaseModel):
    enabled: Optional[bool] = None
    max_size_usd: Optional[float] = None
    confidence_floor: Optional[float] = None
    max_delay_seconds: Optional[int] = None
    size_scale_factor: Optional[float] = None
    cooldown_seconds: Optional[int] = None

def _policy_to_dict(p: CopyPolicy) -> dict:
    return {
        "id": p.id,
        "source_name": p.source_name,
        "enabled": p.enabled,
        "max_size_usd": p.max_size_usd,
        "confidence_floor": p.confidence_floor,
        "max_delay_seconds": p.max_delay_seconds,
        "size_scale_factor": p.size_scale_factor,
        "cooldown_seconds": p.cooldown_seconds,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }

@router.get("/")
def list_copy_policies(db: Session = Depends(get_db), _: None = Depends(require_admin)):
    rows = db.query(CopyPolicy).all()
    return {"items": [_policy_to_dict(r) for r in rows]}

@router.post("/")
def create_copy_policy(body: CopyPolicyCreate, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    row = CopyPolicy(
        source_name=body.source_name,
        enabled=body.enabled,
        max_size_usd=body.max_size_usd,
        confidence_floor=body.confidence_floor,
        max_delay_seconds=body.max_delay_seconds,
        size_scale_factor=body.size_scale_factor,
        cooldown_seconds=body.cooldown_seconds,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _policy_to_dict(row)

@router.put("/{policy_id}")
def update_copy_policy(policy_id: int, body: CopyPolicyUpdate, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    row = db.query(CopyPolicy).filter_by(id=policy_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="CopyPolicy not found")

    if body.enabled is not None:
        row.enabled = body.enabled
    if body.max_size_usd is not None:
        row.max_size_usd = body.max_size_usd
    if body.confidence_floor is not None:
        row.confidence_floor = body.confidence_floor
    if body.max_delay_seconds is not None:
        row.max_delay_seconds = body.max_delay_seconds
    if body.size_scale_factor is not None:
        row.size_scale_factor = body.size_scale_factor
    if body.cooldown_seconds is not None:
        row.cooldown_seconds = body.cooldown_seconds

    db.commit()
    db.refresh(row)
    return _policy_to_dict(row)

@router.delete("/{policy_id}")
def delete_copy_policy(policy_id: int, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    row = db.query(CopyPolicy).filter_by(id=policy_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="CopyPolicy not found")
    db.delete(row)
    db.commit()
    return {"success": True}
