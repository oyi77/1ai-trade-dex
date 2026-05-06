"""Wallet management routes - CRUD, active wallet, balances."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone
from sqlalchemy.orm import Session
import json as _json
import logging

from backend.models.database import get_db, WalletConfig, BotState, SessionLocal
from backend.api.auth import require_admin
from backend.config import settings
from backend.api.validation import (
    WalletConfigCreateRequest as ValidatedWalletConfigCreate,
    WalletConfigUpdateRequest as ValidatedWalletConfigUpdate,
)

logger = logging.getLogger("trading_bot")
router = APIRouter(prefix="/wallets", tags=["wallets"])


# ============================================================================
# Pydantic Models
# ============================================================================


class WalletConfigCreate(BaseModel):
    address: str
    pseudonym: Optional[str] = None
    source: Optional[str] = "user"
    tags: Optional[List[str]] = None
    enabled: Optional[bool] = True


class WalletConfigUpdate(BaseModel):
    pseudonym: Optional[str] = None
    tags: Optional[List[str]] = None
    enabled: Optional[bool] = None
    notes: Optional[str] = None


class ActiveWalletSet(BaseModel):
    address: str


class BalanceUpdate(BaseModel):
    usdc_balance: float
    source: Optional[str] = "manual"


def _row_to_dict(r: WalletConfig) -> dict:
    tags = []
    if r.tags:
        try:
            tags = _json.loads(r.tags)
        except Exception:
            tags = []
    return {
        "id": r.id,
        "address": r.address,
        "pseudonym": r.pseudonym or "",
        "source": r.source or "user",
        "tags": tags,
        "enabled": r.enabled,
        "added_at": r.added_at.isoformat() if r.added_at else None,
    }


# ============================================================================
# Wallet Config CRUD
# ============================================================================


@router.get("/config")
async def list_wallet_configs(
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """List all configured wallets."""
    rows = db.query(WalletConfig).order_by(WalletConfig.added_at.desc()).all()
    return {
        "items": [_row_to_dict(r) for r in rows],
        "total": len(rows),
    }


@router.post("/config")
async def create_wallet_config(
    body: ValidatedWalletConfigCreate,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Add a wallet to the config."""
    existing = (
        db.query(WalletConfig).filter(WalletConfig.address == body.address).first()
    )
    if existing:
        raise HTTPException(
            status_code=409, detail=f"Wallet {body.address} already configured"
        )

    row = WalletConfig(
        address=body.address,
        pseudonym=body.pseudonym,
        source=body.source or "user",
        tags=_json.dumps(body.tags) if body.tags else None,
        enabled=body.enabled if body.enabled is not None else True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _row_to_dict(row)


@router.put("/config/{config_id}")
async def update_wallet_config(
    config_id: int,
    body: ValidatedWalletConfigUpdate,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Update a wallet config."""
    row = db.query(WalletConfig).filter(WalletConfig.id == config_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Wallet config not found")

    if body.pseudonym is not None:
        row.pseudonym = body.pseudonym
    if body.tags is not None:
        row.tags = _json.dumps(body.tags)
    if body.enabled is not None:
        row.enabled = body.enabled
    if body.notes is not None:
        row.notes = body.notes

    db.commit()
    db.refresh(row)
    return _row_to_dict(row)


@router.delete("/config/{config_id}")
async def delete_wallet_config(
    config_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Remove a wallet config."""
    row = db.query(WalletConfig).filter(WalletConfig.id == config_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Wallet config not found")

    db.delete(row)
    db.commit()
    return {"status": "deleted"}


# ============================================================================
# Wallet Creation (generate new keypair)
# ============================================================================


@router.post("/create")
async def create_wallet(_: None = Depends(require_admin)):
    """Generate a new wallet keypair."""
    try:
        from eth_account import Account

        acct = Account.create()
        return {
            "address": acct.address,
            "private_key": acct.key.hex(),
            "message": "Wallet created. Store your private key securely — it cannot be retrieved from this API.",
        }
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="eth_account not installed — wallet creation disabled",
        )


# ============================================================================
# Active Wallet
# ============================================================================


@router.get("/active")
async def get_active_wallet(
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Get the currently active wallet address."""
    state = db.query(BotState).first()
    return {"active_wallet": state.active_wallet if state else None}


@router.put("/active")
async def set_active_wallet(
    body: ActiveWalletSet,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Set the active wallet address."""
    # Verify the wallet exists in config
    wallet = db.query(WalletConfig).filter(WalletConfig.address == body.address).first()
    if not wallet:
        raise HTTPException(
            status_code=404, detail=f"Wallet {body.address} not configured"
        )

    state = db.query(BotState).first()
    if not state:
        raise HTTPException(status_code=404, detail="Bot state not initialized")

    state.active_wallet = body.address
    db.commit()
    return {"active_wallet": body.address}


# ============================================================================
# Wallet Balance
# ============================================================================


@router.get("/{address}/balance")
async def get_wallet_balance(
    address: str,
    db: Session = Depends(get_db),
    force_refresh: bool = False,
    _: None = Depends(require_admin),
):
    """Get wallet balance (fetches live from Polymarket if authenticated, otherwise uses cache)."""
    row = db.query(WalletConfig).filter(WalletConfig.address == address).first()
    if not row:
        return {
            "address": address,
            "usdc_balance": 0.0,
            "last_updated": None,
            "source": "error",
            "error": "Wallet not found",
        }

    # If not forcing refresh and we have a valid cache, use it
    if not force_refresh and row.balance_cache:
        try:
            cached = _json.loads(row.balance_cache)
            # Cache is valid for 5 minutes
            last_updated = cached.get("last_updated")
            if last_updated:
                from datetime import timedelta

                cache_age = datetime.now(timezone.utc) - datetime.fromisoformat(
                    last_updated
                )
                if cache_age < timedelta(minutes=5):
                    return {
                        "address": address,
                        "usdc_balance": cached.get("usdc_balance", 0.0),
                        "last_updated": last_updated,
                        "source": "cache",
                    }
        except Exception as e:
            logger.debug(f"Balance cache parse error: {e}")

    # Try to fetch live balance from Polymarket if we have credentials.
    # NOTE: The CLOB client is authenticated with the bot's private key, so it
    # can only return the bot's own balance. For other addresses we skip the
    # live fetch and fall back to cache.
    bot_address = None
    if settings.POLYMARKET_PRIVATE_KEY:
        try:
            from eth_account import Account as _Acct

            bot_address = _Acct.from_key(
                settings.POLYMARKET_PRIVATE_KEY
            ).address.lower()
        except Exception as e:
            logger.debug(f"Address key derivation error: {e}")

    if (
        settings.POLYMARKET_PRIVATE_KEY
        and bot_address
        and address.lower() == bot_address
    ):
        try:
            from backend.data.polymarket_clob import clob_from_settings

            # Iterate over active modes that require live wallet sync (live/testnet)
            active_trading_modes = [m for m in settings.active_modes_set if m in ("live", "testnet")]
            if not active_trading_modes:
                active_trading_modes = ["live"]  # Fallback if no active trading modes
            
            async with clob_from_settings(mode=active_trading_modes[0]) as clob:
                balance_data = await clob.get_wallet_balance()

                if balance_data.get("error") is None:
                    usdc_balance = balance_data.get("usdc_balance", 0.0)
                    last_updated = datetime.now(timezone.utc).isoformat()

                    # Update cache in DB
                    row.balance_cache = _json.dumps(
                        {
                            "usdc_balance": usdc_balance,
                            "last_updated": last_updated,
                        }
                    )
                    db.commit()

                    return {
                        "address": address,
                        "usdc_balance": usdc_balance,
                        "last_updated": last_updated,
                        "source": "polymarket",
                    }
        except Exception as e:
            logger.warning(f"Failed to fetch live balance for {address[:10]}...: {e}")

    # Fallback to cache or return 0
    if row.balance_cache:
        try:
            cached = _json.loads(row.balance_cache)
            return {
                "address": address,
                "usdc_balance": cached.get("usdc_balance", 0.0),
                "last_updated": cached.get("last_updated"),
                "source": "cache",
            }
        except Exception as e:
            logger.debug(f"Key derivation error: {e}")

    return {
        "address": address,
        "usdc_balance": 0.0,
        "last_updated": None,
        "source": "none",
    }


@router.put("/{address}/balance")
async def update_wallet_balance(
    address: str,
    body: BalanceUpdate,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Update cached wallet balance."""
    row = db.query(WalletConfig).filter(WalletConfig.address == address).first()
    if not row:
        raise HTTPException(status_code=404, detail="Wallet not found")

    row.balance_cache = _json.dumps(
        {
            "usdc_balance": body.usdc_balance,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
    )
    db.commit()

    return {
        "address": address,
        "usdc_balance": body.usdc_balance,
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "source": body.source or "manual",
    }
