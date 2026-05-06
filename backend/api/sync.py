"""Wallet synchronization endpoints."""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.api.auth import require_admin
from backend.config import settings
from backend.core.event_bus import publish_event
from backend.core.wallet_reconciliation import WalletReconciler
from backend.models.database import BotState, get_db

logger = logging.getLogger("trading_bot")

router = APIRouter(tags=["sync"])

class SyncStatusResponse(BaseModel):
    """Status of wallet sync for a single mode (testnet or live)."""
    mode: str  # "testnet" or "live"
    last_synced_at: Optional[datetime]
    next_sync_at: Optional[datetime]
    last_result: Optional[str]  # "success", "error", or None
    status: str  # "healthy" if last sync < 2 min ago, else "stale"


class SyncStatusAllResponse(BaseModel):
    """Combined sync status for both modes."""
    testnet: SyncStatusResponse
    live: SyncStatusResponse


@router.get("/admin/sync-status", response_model=SyncStatusAllResponse)
async def get_sync_status(
    db: Session = Depends(get_db),
    _: None = Depends(require_admin)
):
    """
    Get wallet sync status for testnet and live modes.
    
    Returns:
    - last_synced_at: Timestamp of last successful sync
    - next_sync_at: Estimated next sync time (if scheduled)
    - last_result: Result of last sync ("success" or error message)
    - status: "healthy" if last sync < 2 min ago, else "stale"
    """
    state = db.query(BotState).first()
    now = datetime.now(timezone.utc)
    
    # Helper to compute status
    def compute_status(last_sync_at: Optional[datetime]) -> str:
        if not last_sync_at:
            return "stale"
        # Make last_sync_at timezone-aware if it's naive
        if last_sync_at.tzinfo is None:
            last_sync_at = last_sync_at.replace(tzinfo=timezone.utc)
        elapsed = (now - last_sync_at).total_seconds()
        return "healthy" if elapsed < 120 else "stale"
    
    # For now, use the single last_sync_at from BotState for both modes
    # In future, could track per-mode sync times
    testnet_status = SyncStatusResponse(
        mode="testnet",
        last_synced_at=state.last_sync_at if state else None,
        next_sync_at=None,  # Not scheduled yet
        last_result=None,
        status=compute_status(state.last_sync_at if state else None),
    )
    
    live_status = SyncStatusResponse(
        mode="live",
        last_synced_at=state.last_sync_at if state else None,
        next_sync_at=None,  # Not scheduled yet
        last_result=None,
        status=compute_status(state.last_sync_at if state else None),
    )
    
    return SyncStatusAllResponse(testnet=testnet_status, live=live_status)


async def _sync_wallet_background(mode: str, db: Session):
    """Background task to perform wallet sync."""
    try:
        from backend.data.polymarket_clob import clob_from_settings

        logger.info(f"Starting background sync for mode={mode}")

        clob = clob_from_settings(mode=mode)
        reconciler = WalletReconciler(clob, db, mode)
        result = await reconciler.full_reconciliation()

        # Update BotState with sync result
        state = db.query(BotState).first()
        if state:
            state.last_sync_at = result.last_sync_at
            db.commit()

        logger.info(
            f"Background sync complete [{mode}]: imported={result.imported_count}, "
            f"updated={result.updated_count}, closed={result.closed_count}, "
            f"errors={len(result.errors)}"
        )

        # Publish event for dashboard
        publish_event("sync_completed", {
            "mode": mode,
            "imported": result.imported_count,
            "updated": result.updated_count,
            "closed": result.closed_count,
            "errors": len(result.errors),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    except Exception as e:
        logger.error(
            f"[api.sync._sync_wallet_background] {type(e).__name__}: Background sync failed for mode={mode}: {e}",
            exc_info=True
        )
        publish_event("sync_failed", {
            "mode": mode,
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    finally:
        db.close()


@router.post("/admin/sync-now")
async def sync_now(
    mode: str = "live",
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(get_db),
    _: None = Depends(require_admin)
):
    """
    Trigger an immediate wallet sync in the background.
    
    Args:
        mode: "testnet" or "live" (default: "live")
    
    Returns:
        202 Accepted with status "syncing"
    
    Note:
        - Does not block the API response
        - Sync completion is published via WebSocket events
        - Paper mode is skipped (returns 400)
    """
    if mode != "live":
        raise HTTPException(
            status_code=400,
            detail="mode must be 'live' (no separate testnet blockchain exists)"
        )
    
    if not settings.is_mode_active("live") and not settings.is_mode_active("testnet"):
        raise HTTPException(
            status_code=400,
            detail="Sync not available — no live/testnet mode active"
        )
    
    # Need to create a new session for background task since the injected one closes when request finishes
    from backend.models.database import SessionLocal
    bg_db = SessionLocal()
    
    # Queue background task
    background_tasks.add_task(_sync_wallet_background, mode, bg_db)
    
    logger.info(f"Queued background sync for mode={mode}")
    
    return {
        "status": "syncing",
        "mode": mode,
        "message": f"Wallet sync started for {mode} mode"
    }
