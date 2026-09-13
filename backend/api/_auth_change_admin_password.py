"""Carved verbatim out of ``backend/api/auth.py`` — statements moved, no logic changed."""

from ._auth_require_admin import (
    ChangePasswordBody,
    require_admin,
)

from .auth import (
    BaseModel,
    Depends,
    Request,
    Session,
    ValidatedCredentialsUpdate,
    get_db,
    router,
)

from . import auth as _facade

@router.post("/change-password")
async def change_admin_password(
    body: ChangePasswordBody, _: None = Depends(require_admin)
):
    """Change the admin password (ADMIN_API_KEY). Persists to .env and hot-reloads."""
    new_pw = body.new_password.strip()
    if not new_pw:
        raise _facade.HTTPException(status_code=400, detail="Password cannot be empty")

    _facade._persist_env_updates({"ADMIN_API_KEY": new_pw})
    _facade.settings.ADMIN_API_KEY = new_pw
    _facade.logger.info("Admin password changed")
    return {"status": "ok", "message": "Password updated — please re-login"}
class ModeToggle(BaseModel):
    mode: str
    active: bool
class CredentialsUpdate(BaseModel):
    private_key: str | None = None
    api_key: str | None = None
    api_secret: str | None = None
    api_passphrase: str | None = None
    signature_type: int | None = None
    builder_api_key: str | None = None
    builder_secret: str | None = None
    builder_passphrase: str | None = None
    relayer_api_key: str | None = None
    relayer_api_key_address: str | None = None
@router.post("/mode")
async def toggle_mode(body: ModeToggle, _: None = Depends(require_admin)):
    mode = body.mode.lower()
    if mode not in ("paper", "testnet", "live"):
        raise _facade.HTTPException(
            status_code=400, detail="mode must be paper, testnet, or live"
        )

    if body.active:
        if mode == "live":
            missing = [
                k
                for k, v in {
                    "POLYMARKET_PRIVATE_KEY": _facade.settings.POLYMARKET_PRIVATE_KEY,
                    "POLYMARKET_API_KEY": _facade.settings.POLYMARKET_API_KEY,
                    "POLYMARKET_API_SECRET": _facade.settings.POLYMARKET_API_SECRET,
                    "POLYMARKET_API_PASSPHRASE": _facade.settings.POLYMARKET_API_PASSPHRASE,
                }.items()
                if not v
            ]
            if missing:
                raise _facade.HTTPException(
                    status_code=400,
                    detail=f"Cannot activate live mode: missing credentials: {missing}",
                )
        elif mode == "testnet":
            if not _facade.settings.POLYMARKET_PRIVATE_KEY:
                raise _facade.HTTPException(
                    status_code=400,
                    detail="Cannot activate testnet mode: POLYMARKET_PRIVATE_KEY required",
                )

    active = _facade.settings.active_modes_set
    if body.active:
        active.add(mode)
    else:
        if mode in active and len(active) <= 1:
            raise _facade.HTTPException(
                status_code=400,
                detail="Cannot deactivate the last active mode. At least one mode must be active.",
            )
        active.discard(mode)

    new_value = ",".join(sorted(active))
    _facade.settings.ACTIVE_MODES = new_value
    _facade._persist_env_updates({"ACTIVE_MODES": new_value, "TRADING_MODE": ""})

    _facade.logger.info(
        f"Trading mode toggled: {mode}={'ON' if body.active else 'OFF'}, active={sorted(active)}"
    )
    return {
        "status": "ok",
        "mode": mode,
        "active": body.active,
        "active_modes": sorted(active),
    }
@router.post("/credentials")
async def update_credentials(
    body: ValidatedCredentialsUpdate, _: None = Depends(require_admin)
):
    """Update Polymarket trading credentials, persist to .env, and hot-reload settings."""
    all_fields = {
        "POLYMARKET_PRIVATE_KEY": body.private_key,
        "POLYMARKET_API_KEY": body.api_key,
        "POLYMARKET_API_SECRET": body.api_secret,
        "POLYMARKET_API_PASSPHRASE": body.api_passphrase,
        "POLYMARKET_SIGNATURE_TYPE": (
            str(body.signature_type) if body.signature_type is not None else None
        ),
        "POLYMARKET_BUILDER_API_KEY": body.builder_api_key,
        "POLYMARKET_BUILDER_SECRET": body.builder_secret,
        "POLYMARKET_BUILDER_PASSPHRASE": body.builder_passphrase,
        "POLYMARKET_RELAYER_API_KEY": body.relayer_api_key,
        "POLYMARKET_RELAYER_API_KEY_ADDRESS": body.relayer_api_key_address,
    }
    env_updates = {k: v.strip() for k, v in all_fields.items() if v and v.strip()}

    _facade._persist_env_updates(env_updates)

    # Hot-reload into running settings object
    if body.private_key and body.private_key.strip():
        _facade.settings.POLYMARKET_PRIVATE_KEY = body.private_key.strip()
    if body.api_key and body.api_key.strip():
        _facade.settings.POLYMARKET_API_KEY = body.api_key.strip()
    if body.api_secret and body.api_secret.strip():
        _facade.settings.POLYMARKET_API_SECRET = body.api_secret.strip()
    if body.api_passphrase and body.api_passphrase.strip():
        _facade.settings.POLYMARKET_API_PASSPHRASE = body.api_passphrase.strip()
    if body.signature_type is not None:
        _facade.settings.POLYMARKET_SIGNATURE_TYPE = body.signature_type
    if body.builder_api_key and body.builder_api_key.strip():
        _facade.settings.POLYMARKET_BUILDER_API_KEY = body.builder_api_key.strip()
    if body.builder_secret and body.builder_secret.strip():
        _facade.settings.POLYMARKET_BUILDER_SECRET = body.builder_secret.strip()
    if body.builder_passphrase and body.builder_passphrase.strip():
        _facade.settings.POLYMARKET_BUILDER_PASSPHRASE = body.builder_passphrase.strip()
    if body.relayer_api_key and body.relayer_api_key.strip():
        _facade.settings.POLYMARKET_RELAYER_API_KEY = body.relayer_api_key.strip()
    if body.relayer_api_key_address and body.relayer_api_key_address.strip():
        _facade.settings.POLYMARKET_RELAYER_API_KEY_ADDRESS = (
            body.relayer_api_key_address.strip()
        )

    has_private_key = bool(_facade.settings.POLYMARKET_PRIVATE_KEY)
    has_api_key = bool(_facade.settings.POLYMARKET_API_KEY)
    has_api_secret = bool(_facade.settings.POLYMARKET_API_SECRET)
    has_api_passphrase = bool(_facade.settings.POLYMARKET_API_PASSPHRASE)
    has_builder_key = bool(_facade.settings.POLYMARKET_BUILDER_API_KEY)

    _facade.logger.info(f"Credentials updated: {list(env_updates.keys())}")

    # Restart polyedge-bot to pick up new credentials
    import asyncio as _asyncio

    pm2_path = _facade.shutil.which("pm2")
    if not pm2_path:
        _facade.logger.warning("pm2 not found in PATH; skipping restart")
    else:
        SERVICE_NAME = "polyedge-bot"
        try:
            _proc = await _asyncio.create_subprocess_exec(
                pm2_path,
                "restart",
                SERVICE_NAME,
                stdout=_asyncio.subprocess.PIPE,
                stderr=_asyncio.subprocess.PIPE,
            )
            await _asyncio.wait_for(_proc.communicate(), timeout=10)
            _facade.logger.info("polyedge-bot restarted to apply new credentials")
        except (
            _asyncio.subprocess.SubprocessError,
            OSError,
            _asyncio.TimeoutError,
        ) as _e:
            _facade.logger.warning(f"Could not restart polyedge-bot: {_e}")
        except Exception:
            _facade.logger.exception("Unexpected error restarting polyedge-bot")

    _sig = _facade.settings.POLYMARKET_SIGNATURE_TYPE
    _creds_live_ok = (
        has_private_key
        if _sig in (1, 2)
        else has_private_key and has_api_key and has_api_secret and has_api_passphrase
    )
    _missing_live = (
        []
        if has_private_key
        else (
            ["POLYMARKET_PRIVATE_KEY"]
            if _sig in (1, 2)
            else [
                k
                for k, v in {
                    "POLYMARKET_PRIVATE_KEY": has_private_key,
                    "POLYMARKET_API_KEY": has_api_key,
                    "POLYMARKET_API_SECRET": has_api_secret,
                    "POLYMARKET_API_PASSPHRASE": has_api_passphrase,
                }.items()
                if not v
            ]
        )
    )

    return {
        "status": "ok",
        "updated": list(env_updates.keys()),
        "restarted_bot": True,
        "creds_paper": True,
        "creds_testnet": has_private_key,
        "creds_live": _creds_live_ok,
        "missing_for_testnet": [] if has_private_key else ["POLYMARKET_PRIVATE_KEY"],
        "missing_for_live": _missing_live,
        "builder_configured": has_builder_key,
        "signature_type": _facade.settings.POLYMARKET_SIGNATURE_TYPE,
    }
@router.get("/system")
async def get_admin_system(
    request: Request, db: Session = Depends(get_db), _: None = Depends(require_admin)
):
    """Return system health overview."""
    state = db.query(_facade.BotState).first()
    pending_trades = (
        db.query(_facade.Trade)
        .filter(
            _facade.Trade.settled.is_(False), _facade.Trade.trading_mode.in_(_facade.settings.active_modes_set)
        )
        .count()
    )
    db_trade_count = (
        db.query(_facade.Trade)
        .filter(_facade.Trade.trading_mode.in_(_facade.settings.active_modes_set))
        .count()
    )
    db_signal_count = db.query(_facade.Signal).count()

    uptime = (
        _facade.datetime.now(_facade.timezone.utc)
        - (
            request.app.state.start_time
            if hasattr(request.app.state, "start_time")
            else _facade.datetime.now(_facade.timezone.utc)
        )
    ).total_seconds()

    has_private_key = bool(_facade.settings.POLYMARKET_PRIVATE_KEY)
    has_api_key = bool(_facade.settings.POLYMARKET_API_KEY)
    has_api_secret = bool(_facade.settings.POLYMARKET_API_SECRET)
    has_api_passphrase = bool(_facade.settings.POLYMARKET_API_PASSPHRASE)
    has_builder_key = bool(_facade.settings.POLYMARKET_BUILDER_API_KEY)

    # For signature types 1 (Poly-Proxy) and 2 (Poly-EOA), API credentials
    # are auto-derived from the private key at startup — separate env vars
    # are NOT required.  For type 0 (EOA), all three must be set explicitly.
    _sig_type = _facade.settings.POLYMARKET_SIGNATURE_TYPE
    if _sig_type in (1, 2):
        creds_live_ok = has_private_key
        missing_for_live = [] if has_private_key else ["POLYMARKET_PRIVATE_KEY"]
    else:
        creds_live_ok = (
            has_private_key and has_api_key and has_api_secret and has_api_passphrase
        )
        missing_for_live = [
            k
            for k, v in {
                "POLYMARKET_PRIVATE_KEY": has_private_key,
                "POLYMARKET_API_KEY": has_api_key,
                "POLYMARKET_API_SECRET": has_api_secret,
                "POLYMARKET_API_PASSPHRASE": has_api_passphrase,
            }.items()
            if not v
        ]

    response = {
        "trading_mode": _facade.settings.TRADING_MODE,
        "active_modes": sorted(_facade.settings.active_modes_set),
        "bot_running": state.is_running if state else False,
        "uptime_seconds": int(uptime),
        "pending_trades": pending_trades,
        "telegram_configured": bool(_facade.settings.TELEGRAM_BOT_TOKEN),
        "kalshi_enabled": _facade.settings.KALSHI_ENABLED,
        "weather_enabled": _facade.settings.WEATHER_ENABLED,
        "db_trade_count": db_trade_count,
        "db_signal_count": db_signal_count,
        # Credential readiness per mode
        "creds_paper": True,  # paper needs no credentials
        "creds_testnet": has_private_key,
        "creds_live": creds_live_ok,
        "missing_for_testnet": [] if has_private_key else ["POLYMARKET_PRIVATE_KEY"],
        "missing_for_live": missing_for_live,
        # Builder Program & Signature Type
        "builder_configured": has_builder_key,
        "signature_type": _facade.settings.POLYMARKET_SIGNATURE_TYPE,
        "signature_type_label": {
            0: "EOA (direct wallet)",
            1: "Poly-Proxy (email login)",
            2: "Poly-EOA (PK maps to proxy)",
        }.get(_facade.settings.POLYMARKET_SIGNATURE_TYPE, "Unknown"),
    }
    db.rollback()
    return response
@router.post("/alerts/test")
async def test_alert(_: None = Depends(require_admin)):
    """Send a test Telegram alert to verify bot configuration."""
    from backend.bot.notification.registry import registry

    if not _facade.settings.TELEGRAM_BOT_TOKEN:
        raise _facade.HTTPException(status_code=400, detail="TELEGRAM_BOT_TOKEN not configured")
    await registry.send_alert(
        title="Auth Alert", message="PolyEdge alert test -- bot is configured correctly"
    )
    return {"status": "ok", "message": "Test alert sent"}
@router.get("/ai/suggest")
async def ai_suggest_params(
    db: Session = Depends(get_db), _: None = Depends(require_admin)
):
    """Use AI to analyze recent performance and suggest parameter improvements."""
    from backend.ai.optimizer import ParameterOptimizer

    optimizer = ParameterOptimizer(_facade.settings)
    return await optimizer.get_suggestions(db)
@router.get("/scheduler/jobs")
async def get_scheduler_jobs_endpoint(_: None = Depends(require_admin)):
    """Return current APScheduler job list."""
    from backend.core.scheduling.scheduler import get_scheduler_jobs

    return get_scheduler_jobs()
