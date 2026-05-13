from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.orm import Session
from datetime import datetime, timezone
import json as _json

from backend.models.database import get_db
from backend.models.trading_wallet import TradingWallet, WalletAllocation
from backend.api.auth import require_admin
from loguru import logger

router = APIRouter(prefix="/wallet-allocations", tags=["wallet_allocations"])

class TradingWalletCreate(BaseModel):
    label: str
    chain: str
    address: str
    encrypted_private_key: Optional[str] = None
    api_key: Optional[str] = None
    encrypted_api_secret: Optional[str] = None
    enabled: bool = True
    is_paper: bool = False
    notes: Optional[str] = None

class TradingWalletUpdate(BaseModel):
    label: Optional[str] = None
    chain: Optional[str] = None
    address: Optional[str] = None
    encrypted_private_key: Optional[str] = None
    api_key: Optional[str] = None
    encrypted_api_secret: Optional[str] = None
    enabled: Optional[bool] = None
    is_paper: Optional[bool] = None
    notes: Optional[str] = None

class WalletAllocationCreate(BaseModel):
    wallet_id: int
    strategy_name: str
    weight: float = 1.0
    max_exposure_usd: Optional[float] = None
    enabled: bool = True

class WalletAllocationUpdate(BaseModel):
    weight: Optional[float] = None
    max_exposure_usd: Optional[float] = None
    enabled: Optional[bool] = None

def _wallet_to_dict(w: TradingWallet) -> dict:
    return {
        "id": w.id,
        "label": w.label,
        "chain": w.chain,
        "address": w.address,
        "has_private_key": bool(w.encrypted_private_key),
        "api_key": w.api_key,
        "has_api_secret": bool(w.encrypted_api_secret),
        "enabled": w.enabled,
        "is_paper": w.is_paper,
        "created_at": w.created_at.isoformat() if w.created_at else None,
        "notes": w.notes,
    }

def _alloc_to_dict(a: WalletAllocation) -> dict:
    return {
        "id": a.id,
        "wallet_id": a.wallet_id,
        "strategy_name": a.strategy_name,
        "weight": a.weight,
        "max_exposure_usd": a.max_exposure_usd,
        "enabled": a.enabled,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }

@router.get("/wallets")
def list_trading_wallets(db: Session = Depends(get_db), _: None = Depends(require_admin)):
    rows = db.query(TradingWallet).all()
    return {"items": [_wallet_to_dict(r) for r in rows]}

@router.post("/wallets")
def create_trading_wallet(body: TradingWalletCreate, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    row = TradingWallet(
        label=body.label,
        chain=body.chain,
        address=body.address,
        encrypted_private_key=body.encrypted_private_key,
        api_key=body.api_key,
        encrypted_api_secret=body.encrypted_api_secret,
        enabled=body.enabled,
        is_paper=body.is_paper,
        notes=body.notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _wallet_to_dict(row)

@router.put("/wallets/{wallet_id}")
def update_trading_wallet(wallet_id: int, body: TradingWalletUpdate, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    row = db.query(TradingWallet).filter_by(id=wallet_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Wallet not found")
    
    if body.label is not None:
        row.label = body.label
    if body.chain is not None:
        row.chain = body.chain
    if body.address is not None:
        row.address = body.address
    if body.encrypted_private_key is not None:
        row.encrypted_private_key = body.encrypted_private_key
    if body.api_key is not None:
        row.api_key = body.api_key
    if body.encrypted_api_secret is not None:
        row.encrypted_api_secret = body.encrypted_api_secret
    if body.enabled is not None:
        row.enabled = body.enabled
    if body.is_paper is not None:
        row.is_paper = body.is_paper
    if body.notes is not None:
        row.notes = body.notes
        
    db.commit()
    db.refresh(row)
    return _wallet_to_dict(row)

@router.delete("/wallets/{wallet_id}")
def delete_trading_wallet(wallet_id: int, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    row = db.query(TradingWallet).filter_by(id=wallet_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Wallet not found")
    db.delete(row)
    db.commit()
    return {"success": True}

@router.get("/allocations")
def list_allocations(db: Session = Depends(get_db), _: None = Depends(require_admin)):
    rows = db.query(WalletAllocation).all()
    return {"items": [_alloc_to_dict(r) for r in rows]}

@router.post("/allocations")
def create_allocation(body: WalletAllocationCreate, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    row = WalletAllocation(
        wallet_id=body.wallet_id,
        strategy_name=body.strategy_name,
        weight=body.weight,
        max_exposure_usd=body.max_exposure_usd,
        enabled=body.enabled,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _alloc_to_dict(row)

@router.put("/allocations/{alloc_id}")
def update_allocation(alloc_id: int, body: WalletAllocationUpdate, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    row = db.query(WalletAllocation).filter_by(id=alloc_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Allocation not found")
    
    if body.weight is not None:
        row.weight = body.weight
    if body.max_exposure_usd is not None:
        row.max_exposure_usd = body.max_exposure_usd
    if body.enabled is not None:
        row.enabled = body.enabled
        
    db.commit()
    db.refresh(row)
    return _alloc_to_dict(row)

@router.delete("/allocations/{alloc_id}")
def delete_allocation(alloc_id: int, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    row = db.query(WalletAllocation).filter_by(id=alloc_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Allocation not found")
    db.delete(row)
    db.commit()
    return {"success": True}
