"""Bot control endpoints — start, stop, reset, paper-topup, live-adjust."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from backend.config import settings
from backend.models.database import (
    get_db,
    BotState,
    Trade,
    AILog,
    for_update,
)
from backend.api.auth import require_admin
from loguru import logger

router = APIRouter(tags=["system"])


class ResetRequest(BaseModel):
    confirm: bool = False


class PaperTopupRequest(BaseModel):
    amount: float = Field(gt=0, description="USDC to add to paper bankroll")
    confirm: bool = False


class LiveAdjustRequest(BaseModel):
    amount: float = Field(
        description="USDC amount (positive=deposit, negative=withdraw)"
    )
    confirm: bool = False


@router.post("/bot/start")
async def start_bot(
    body: dict | None = None,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    from backend.core.scheduling.scheduler import start_scheduler, log_event, is_scheduler_running

    mode = (body or {}).get("mode", settings.TRADING_MODE)
    state = for_update(db, db.query(BotState).filter_by(mode=mode)).first()
    if state and state.is_running:
        raise HTTPException(
            status_code=409, detail={"error": "already_running", "is_running": True}
        )

    if state:
        state.is_running = True
        db.commit()

    if not is_scheduler_running():
        start_scheduler()

    log_event("success", f"Trading bot started for mode={mode}")
    return {"status": "started", "is_running": True, "mode": mode}


@router.post("/bot/stop")
async def stop_bot(
    body: dict | None = None,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    from backend.core.scheduling.scheduler import log_event

    mode = (body or {}).get("mode", settings.TRADING_MODE)
    state = for_update(db, db.query(BotState).filter_by(mode=mode)).first()
    if state and not state.is_running:
        raise HTTPException(
            status_code=409, detail={"error": "already_stopped", "is_running": False}
        )

    if state:
        state.is_running = False
        db.commit()

    log_event("info", f"Trading bot paused for mode={mode}")
    return {"status": "stopped", "is_running": False, "mode": mode}


@router.post("/bot/reset")
async def reset_bot(
    body: ResetRequest, db: Session = Depends(get_db), _: None = Depends(require_admin)
):
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="Set confirm=true to confirm reset. This deletes ALL trades and resets bankroll.",
        )
    from backend.core.scheduling.scheduler import log_event

    try:
        trades_deleted = db.query(Trade).delete()

        from backend.core.wallet.botstate_ledger import BotStateLedger

        for mode in ["paper", "testnet", "live"]:
            state = for_update(db, db.query(BotState).filter_by(mode=mode)).first()
            if state:
                BotStateLedger.sync_to_absolute(
                    db=db,
                    mode=mode,
                    target_balance=float(settings.INITIAL_BANKROLL),
                    source="bot_reset",
                )
                state.total_trades = 0
                state.winning_trades = 0
                state.total_pnl = 0.0
                state.is_running = True

        ai_logs_deleted = db.query(AILog).delete()
        db.commit()

        log_event(
            "success",
            f"Bot reset: {trades_deleted} trades deleted. Fresh start with ${settings.INITIAL_BANKROLL:,.2f}",
        )

        return {
            "status": "reset",
            "trades_deleted": trades_deleted,
            "ai_logs_deleted": ai_logs_deleted,
            "new_bankroll": settings.INITIAL_BANKROLL,
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Reset failed")


@router.post("/bot/paper-topup")
async def paper_topup(
    body: PaperTopupRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="Set confirm=true to confirm topup.",
        )
    if not settings.is_mode_active("paper"):
        raise HTTPException(
            status_code=409,
            detail="paper-topup only available when paper mode is active",
        )

    from backend.core.scheduling.scheduler import log_event
    from backend.core.wallet.botstate_ledger import BotStateLedger
    from backend.models.audit_logger import log_audit_event

    state = for_update(db, db.query(BotState).filter_by(mode="paper")).first()
    if state is None:
        raise HTTPException(status_code=404, detail="Paper bot state not found")

    previous = float(state.paper_bankroll or 0.0)
    BotStateLedger.record_deposit(
        db=db, mode="paper", amount=float(body.amount), source="paper_topup"
    )

    # Also bump the effective initial bankroll so reconciliation preserves the top-up.
    prev_initial = float(state.paper_initial_bankroll or settings.INITIAL_BANKROLL)
    state.paper_initial_bankroll = prev_initial + body.amount

    db.commit()

    log_event(
        "info",
        f"Paper bankroll topped up by ${body.amount:,.2f} (${previous:,.2f} → ${state.paper_bankroll:,.2f}); "
        f"initial_bankroll ${prev_initial:,.2f} → ${state.paper_initial_bankroll:,.2f}",
    )
    log_audit_event(
        db,
        event_type="PAPER_TOPUP",
        entity_type="BOT_STATE",
        entity_id="paper",
        old_value={"paper_bankroll": previous, "paper_initial_bankroll": prev_initial},
        new_value={
            "paper_bankroll": float(state.paper_bankroll),
            "paper_initial_bankroll": float(state.paper_initial_bankroll),
            "added": body.amount,
        },
        user_id="admin_topup",
    )
    db.commit()

    return {
        "status": "topped_up",
        "previous_bankroll": previous,
        "added": body.amount,
        "new_bankroll": state.paper_bankroll,
        "new_initial_bankroll": state.paper_initial_bankroll,
    }


@router.post("/bot/live-adjust")
async def live_adjust(
    body: LiveAdjustRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Adjust live bankroll initial capital on deposit/withdraw."""
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Set confirm=true to confirm.")
    if not settings.is_mode_active("live"):
        raise HTTPException(
            status_code=409,
            detail="live-adjust only available when live mode is active",
        )

    from backend.core.scheduling.scheduler import log_event
    from backend.models.audit_logger import log_audit_event

    state = for_update(db, db.query(BotState).filter_by(mode="live")).first()
    if state is None:
        raise HTTPException(status_code=404, detail="Live bot state not found")

    prev_initial = float(state.live_initial_bankroll or settings.INITIAL_BANKROLL)
    new_initial = prev_initial + body.amount
    if new_initial < 0:
        raise HTTPException(
            status_code=400, detail="Cannot withdraw more than initial capital"
        )

    state.live_initial_bankroll = new_initial
    db.commit()

    action = "deposit" if body.amount > 0 else "withdrawal"
    log_event(
        "info",
        f"Live {action} ${abs(body.amount):,.2f} — initial_bankroll ${prev_initial:,.2f} → ${new_initial:,.2f}",
    )
    log_audit_event(
        db,
        event_type=f"LIVE_{action.upper()}",
        entity_type="BOT_STATE",
        entity_id="live",
        old_value={"live_initial_bankroll": prev_initial},
        new_value={"live_initial_bankroll": new_initial, action: abs(body.amount)},
        user_id="admin_adjust",
    )
    db.commit()

    return {
        "status": action,
        "previous_initial": prev_initial,
        "adjusted": body.amount,
        "new_initial": new_initial,
    }
