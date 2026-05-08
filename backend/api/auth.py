"""Authentication and admin routes."""

import secrets
import time
from fastapi import Depends, HTTPException, Header, APIRouter, Request, Response, Cookie
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import datetime, timezone
import logging
import os

from backend.config import settings
from backend.models.database import get_db, BotState, Trade, Signal, for_update
from backend.api.validation import CredentialsUpdateRequest as ValidatedCredentialsUpdate

logger = logging.getLogger("trading_bot")

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin(authorization: str | None = Header(None)):
    """Require admin API key if ADMIN_API_KEY is configured."""
    key = settings.ADMIN_API_KEY
    if not key:
        return  # No key configured = open (dev mode)
    if not authorization or authorization != f"Bearer {key}":
        raise HTTPException(
            status_code=401,
            detail="Unauthorized — set Authorization: Bearer <ADMIN_API_KEY>",
        )


class AdminLoginBody(BaseModel):
    password: str


class ChangePasswordBody(BaseModel):
    new_password: str


# Secret keywords for masking sensitive values
_SECRET_KEYWORDS = {"KEY", "SECRET", "PASSWORD", "PASSPHRASE", "TOKEN", "PRIVATE"}


def _is_secret(field_name: str) -> bool:
    upper = field_name.upper()
    return any(kw in upper for kw in _SECRET_KEYWORDS)


def _mask_value(field_name: str, value) -> str:
    if value is None or value == "" or value == "None":
        return ""
    if _is_secret(field_name):
        return "****"
    return value


# ---------------------------------------------------------------------------
# Session-based cookie auth (Task 15)
# ---------------------------------------------------------------------------
# In-memory session store: token -> {"created_at": float, "csrf": str}
_SESSION_STORE: dict[str, dict] = {}
_SESSION_TTL_SECONDS = 86400  # 24 hours
_COOKIE_NAME = "admin_session"


def _cleanup_expired_sessions() -> None:
    """Remove sessions older than TTL."""
    now = time.time()
    expired = [tok for tok, data in _SESSION_STORE.items() if now - data["created_at"] > _SESSION_TTL_SECONDS]
    for tok in expired:
        del _SESSION_STORE[tok]


class CookieLoginBody(BaseModel):
    admin_key: str


@router.post("/auth/login")
def cookie_login(body: CookieLoginBody, response: Response):
    """Login with admin_key, receive httpOnly cookie + CSRF token."""
    _cleanup_expired_sessions()
    key = settings.ADMIN_API_KEY
    if not key:
        raise HTTPException(status_code=400, detail="No ADMIN_API_KEY configured — cookie auth unavailable")
    if body.admin_key != key:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    session_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    _SESSION_STORE[session_token] = {"created_at": time.time(), "csrf": csrf_token}

    response.set_cookie(
        key=_COOKIE_NAME,
        value=session_token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=_SESSION_TTL_SECONDS,
        path="/api",
    )
    return {"csrf_token": csrf_token, "message": "Login successful"}


@router.post("/auth/logout")
def cookie_logout(response: Response, admin_session: str | None = Cookie(None)):
    """Clear the session cookie."""
    if admin_session and admin_session in _SESSION_STORE:
        del _SESSION_STORE[admin_session]
    response.delete_cookie(key=_COOKIE_NAME, path="/api")
    return {"message": "Logged out"}


def require_admin_from_cookie(
    admin_session: str | None = Cookie(None),
    x_csrf_token: str | None = Header(None),
    authorization: str | None = Header(None),
):
    """Authenticate via cookie + CSRF OR via Bearer header (backward compat)."""
    key = settings.ADMIN_API_KEY
    if not key:
        return  # No key configured = open (dev mode)

    # Backward compat: Bearer header auth
    if authorization and authorization == f"Bearer {key}":
        return

    # Cookie-based auth
    if not admin_session or admin_session not in _SESSION_STORE:
        raise HTTPException(status_code=401, detail="Unauthorized — invalid or expired session")

    session = _SESSION_STORE[admin_session]

    # Check session expiry
    if time.time() - session["created_at"] > _SESSION_TTL_SECONDS:
        del _SESSION_STORE[admin_session]
        raise HTTPException(status_code=401, detail="Session expired")

    # CSRF validation for mutating requests (caller must validate via require_csrf)
    # This dep just ensures the session is valid
    return session


def require_csrf(
    x_csrf_token: str | None = Header(None),
    admin_session: str | None = Cookie(None),
    authorization: str | None = Header(None),
):
    """Validate CSRF token for cookie-authenticated mutating requests."""
    key = settings.ADMIN_API_KEY
    if not key:
        return
    if authorization and authorization == f"Bearer {key}":
        return
    if not admin_session or admin_session not in _SESSION_STORE:
        return
    session = _SESSION_STORE[admin_session]
    if not x_csrf_token or x_csrf_token != session.get("csrf"):
        raise HTTPException(status_code=403, detail="CSRF token missing or invalid")


def _get_valid_session(admin_session: str | None) -> dict | None:
    """Return session dict when cookie session exists and is not expired."""
    if not admin_session:
        return None
    session = _SESSION_STORE.get(admin_session)
    if not session:
        return None
    if time.time() - session["created_at"] > _SESSION_TTL_SECONDS:
        del _SESSION_STORE[admin_session]
        return None
    return session


def authorize_realtime_access(token: str | None = None, admin_session: str | None = None) -> bool:
    """Authorize SSE/WebSocket access — public read-only for dashboard data.
    
    Real-time streams are read-only (no write capability) so public access
    is safe. Auth is still enforced for admin actions via require_admin.
    """
    return True


def _persist_env_updates(updates: dict[str, str]) -> None:
    """
    Atomic .env file update helper.

    Reads existing .env, merges in updates, and atomically replaces the file
    using a temp-file + os.replace() pattern to prevent partial writes on crash.

    Args:
        updates: dict of env var names to their new values
    """
    import tempfile

    env_path = ".env"
    env_lines: dict[str, str] = {}

    # Read existing .env
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line_stripped = line.strip()
                if "=" in line_stripped and not line_stripped.startswith("#"):
                    k, v = line_stripped.split("=", 1)
                    env_lines[k.strip()] = v.strip()

    # Merge updates
    env_lines.update(updates)

    # Atomic write: write to temp file in same dir, then rename
    env_dir = os.path.dirname(os.path.abspath(env_path)) or "."
    tmp_fd, tmp_path = tempfile.mkstemp(dir=env_dir, prefix=".env.tmp")
    try:
        with os.fdopen(tmp_fd, "w") as f:
            for k, v in env_lines.items():
                f.write(f"{k}={v}\n")
        os.replace(tmp_path, env_path)
    except Exception as e:
        logger.debug(f"Secret validation error: {e}")
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _get_grouped_settings() -> dict:
    """Return all settings grouped by category with secrets masked."""
    trading = {}
    weather = {}
    risk = {}
    indicators = {}
    ai = {}
    api_keys = {}
    telegram = {}
    security = {}
    system = {}
    web_search = {}
    polymarket = {}
    kalshi = {}
    self_improve = {}
    signals = {}
    phase2 = {}

    field_groups = {
        # ── Trading ──
        "TRADING_MODE": trading,
        "INITIAL_BANKROLL": trading,
        "KELLY_FRACTION": trading,
        "MAX_TRADE_SIZE": trading,
        "DAILY_LOSS_LIMIT": trading,
        "MIN_EDGE_THRESHOLD": trading,
        "MAX_ENTRY_PRICE": trading,
        "MAX_TRADES_PER_WINDOW": trading,
        "MAX_TOTAL_PENDING_TRADES": trading,
        "STALE_TRADE_HOURS": trading,
        "BTC_PRICE_SOURCE": trading,
        "SCAN_INTERVAL_SECONDS": trading,
        "SETTLEMENT_INTERVAL_SECONDS": trading,
        # ── Signal Approval ──
        "SIGNAL_APPROVAL_MODE": signals,
        "AUTO_APPROVE_MIN_CONFIDENCE": signals,
        "SIGNAL_NOTIFICATION_DURATION_MS": signals,
        "AUTO_TRADER_ENABLED": signals,
        # ── Weather ──
        "WEATHER_ENABLED": weather,
        "WEATHER_CITIES": weather,
        "WEATHER_MIN_EDGE_THRESHOLD": weather,
        "WEATHER_MAX_ENTRY_PRICE": weather,
        "WEATHER_MAX_TRADE_SIZE": weather,
        "WEATHER_SCAN_INTERVAL_SECONDS": weather,
        "WEATHER_SETTLEMENT_INTERVAL_SECONDS": weather,
        # ── Risk Management ──
        "MAX_POSITION_FRACTION": risk,
        "MAX_TOTAL_EXPOSURE_FRACTION": risk,
        "SLIPPAGE_TOLERANCE": risk,
        "DAILY_DRAWDOWN_LIMIT_PCT": risk,
        "WEEKLY_DRAWDOWN_LIMIT_PCT": risk,
        "MIN_TIME_REMAINING": risk,
        "MAX_TIME_REMAINING": risk,
        "MIN_MARKET_VOLUME": risk,
        # ── Indicator Weights ──
        "WEIGHT_RSI": indicators,
        "WEIGHT_MOMENTUM": indicators,
        "WEIGHT_VWAP": indicators,
        "WEIGHT_SMA": indicators,
        "WEIGHT_MARKET_SKEW": indicators,
        # ── AI / LLM ──
        "AI_PROVIDER": ai,
        "AI_ENABLED": ai,
        "AI_LOG_ALL_CALLS": ai,
        "AI_DAILY_BUDGET_USD": ai,
        "AI_SIGNAL_WEIGHT": ai,
        "MIN_DEBATE_EDGE": ai,
        "GROQ_MODEL": ai,
        "ANTHROPIC_MODEL": ai,
        "LLM_DEFAULT_PROVIDER": ai,
        "LLM_DEBATE_PROVIDER": ai,
        "LLM_JUDGE_PROVIDER": ai,
        "AI_BASE_URL": ai,
        "AI_MODEL": ai,
        # ── Polymarket ──
        "POLYMARKET_SIGNATURE_TYPE": polymarket,
        "POLYMARKET_BUILDER_API_KEY": polymarket,
        "POLYMARKET_BUILDER_SECRET": polymarket,
        "POLYMARKET_BUILDER_PASSPHRASE": polymarket,
        "POLYMARKET_RELAYER_API_KEY": polymarket,
        "POLYMARKET_RELAYER_API_KEY_ADDRESS": polymarket,
        # ── Polymarket Auth (secrets) ──
        "POLYMARKET_API_KEY": api_keys,
        "POLYMARKET_PRIVATE_KEY": api_keys,
        "POLYMARKET_API_SECRET": api_keys,
        "POLYMARKET_API_PASSPHRASE": api_keys,
        # ── Kalshi ──
        "KALSHI_ENABLED": kalshi,
        "KALSHI_API_KEY_ID": api_keys,
        "KALSHI_PRIVATE_KEY_PATH": api_keys,
        # ── Other API Keys ──
        "GROQ_API_KEY": api_keys,
        "ANTHROPIC_API_KEY": api_keys,
        "AI_API_KEY": api_keys,
        "TAVILY_API_KEY": api_keys,
        "EXA_API_KEY": api_keys,
        "SERPER_API_KEY": api_keys,
        "CRW_API_KEY": api_keys,
        "CRW_API_URL": api_keys,
        # ── Telegram ──
        "TELEGRAM_BOT_TOKEN": telegram,
        "TELEGRAM_ADMIN_CHAT_IDS": telegram,
        "TELEGRAM_HIGH_CONFIDENCE_ALERTS": telegram,
        # ── Security ──
        "ADMIN_API_KEY": security,
        "CORS_ORIGINS": security,
        # ── System ──
        "DATABASE_URL": system,
        "JOB_WORKER_ENABLED": system,
        "JOB_QUEUE_URL": system,
        "JOB_TIMEOUT_SECONDS": system,
        "MAX_CONCURRENT_JOBS": system,
        "DB_EXECUTOR_MAX_WORKERS": system,
        "DATA_AGGREGATOR_MAX_STALE_AGE": system,
        "POLYGON_WS_URL": system,
        "CONDITIONAL_TOKENS_ADDRESS": system,
        "MIN_WHALE_TRADE_USD": system,
        "WHALE_LISTENER_ENABLED": system,
        "POLYGON_AMOY_RPC": system,
        "POLYGON_AMOY_CHAIN_ID": system,
        # ── Web Search ──
        "WEBSEARCH_PROVIDER": web_search,
        "WEBSEARCH_FALLBACK_PROVIDER": web_search,
        "WEBSEARCH_ENABLED": web_search,
        "WEBSEARCH_MAX_RESULTS": web_search,
        "WEBSEARCH_TIMEOUT_SECONDS": web_search,
        # ── Self-Improve ──
        "AUTO_IMPROVE_ENABLED": self_improve,
        "AUTO_IMPROVE_INTERVAL_DAYS": self_improve,
        "AUTO_IMPROVE_TRADE_LIMIT": self_improve,
        "SELF_REVIEW_ENABLED": self_improve,
        "SELF_REVIEW_INTERVAL_DAYS": self_improve,
        "RESEARCH_PIPELINE_ENABLED": self_improve,
        "RESEARCH_PIPELINE_INTERVAL_HOURS": self_improve,
        # ── Phase 2 Features ──
        "NEWS_FEED_ENABLED": phase2,
        "ARBITRAGE_DETECTOR_ENABLED": phase2,
        "NEWS_FEED_INTERVAL_SECONDS": phase2,
        "ARBITRAGE_SCAN_INTERVAL_SECONDS": phase2,
        # ── Cache ──
        "CACHE_URL": system,
        "CACHE_TTL_SECONDS": system,
        # ── Backup ──
        "DB_BACKUP_INTERVAL_HOURS": system,
        "DB_BACKUP_DIR": system,
        "DB_BACKUP_RETENTION_DAYS": system,
    }

    for field_name, group in field_groups.items():
        if hasattr(settings, field_name):
            raw = getattr(settings, field_name)
            group[field_name] = _mask_value(field_name, raw)

    return {
        "trading": trading,
        "signals": signals,
        "weather": weather,
        "risk": risk,
        "indicators": indicators,
        "ai": ai,
        "polymarket": polymarket,
        "kalshi": kalshi,
        "api_keys": api_keys,
        "telegram": telegram,
        "security": security,
        "system": system,
        "web_search": web_search,
        "self_improve": self_improve,
        "phase2": phase2,
    }


class SettingsUpdate(BaseModel):
    updates: dict


# ============================================================================
# Admin Authentication Routes
# ============================================================================


@router.get("/auth-required")
async def auth_required_endpoint():
    """Returns whether admin authentication is configured."""
    return {"auth_required": bool(settings.ADMIN_API_KEY)}


@router.post("/login")
async def admin_login(body: AdminLoginBody):
    """Verify admin password. Returns success; client stores the password as bearer token."""
    if not settings.ADMIN_API_KEY:
        return {"success": True, "auth_required": False}
    if body.password != settings.ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid password")
    return {"success": True, "auth_required": True}


@router.post("/change-password")
async def change_admin_password(
    body: ChangePasswordBody, _: None = Depends(require_admin)
):
    """Change the admin password (ADMIN_API_KEY). Persists to .env and hot-reloads."""
    new_pw = body.new_password.strip()
    if not new_pw:
        raise HTTPException(status_code=400, detail="Password cannot be empty")

    _persist_env_updates({"ADMIN_API_KEY": new_pw})
    settings.ADMIN_API_KEY = new_pw
    logger.info("Admin password changed")
    return {"status": "ok", "message": "Password updated — please re-login"}


# ============================================================================
# Admin Settings Routes (DEPRECATED - moved to backend/api/settings.py)
# ============================================================================
# Old endpoints removed to avoid conflict with new database-backed settings API


# ============================================================================
# Admin System Routes
# ============================================================================


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
        raise HTTPException(
            status_code=400, detail="mode must be paper, testnet, or live"
        )

    if body.active:
        if mode == "live":
            missing = [
                k for k, v in {
                    "POLYMARKET_PRIVATE_KEY": settings.POLYMARKET_PRIVATE_KEY,
                    "POLYMARKET_API_KEY": settings.POLYMARKET_API_KEY,
                    "POLYMARKET_API_SECRET": settings.POLYMARKET_API_SECRET,
                    "POLYMARKET_API_PASSPHRASE": settings.POLYMARKET_API_PASSPHRASE,
                }.items() if not v
            ]
            if missing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot activate live mode: missing credentials: {missing}",
                )
        elif mode == "testnet":
            if not settings.POLYMARKET_PRIVATE_KEY:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot activate testnet mode: POLYMARKET_PRIVATE_KEY required",
                )

    active = settings.active_modes_set
    if body.active:
        active.add(mode)
    else:
        if mode in active and len(active) <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot deactivate the last active mode. At least one mode must be active.",
            )
        active.discard(mode)

    new_value = ",".join(sorted(active))
    settings.ACTIVE_MODES = new_value
    _persist_env_updates({"ACTIVE_MODES": new_value, "TRADING_MODE": ""})

    logger.info(f"Trading mode toggled: {mode}={'ON' if body.active else 'OFF'}, active={sorted(active)}")
    return {"status": "ok", "mode": mode, "active": body.active, "active_modes": sorted(active)}


@router.post("/credentials")
async def update_credentials(body: ValidatedCredentialsUpdate, _: None = Depends(require_admin)):
    """Update Polymarket trading credentials, persist to .env, and hot-reload settings."""
    all_fields = {
        "POLYMARKET_PRIVATE_KEY": body.private_key,
        "POLYMARKET_API_KEY": body.api_key,
        "POLYMARKET_API_SECRET": body.api_secret,
        "POLYMARKET_API_PASSPHRASE": body.api_passphrase,
        "POLYMARKET_SIGNATURE_TYPE": str(body.signature_type)
        if body.signature_type is not None
        else None,
        "POLYMARKET_BUILDER_API_KEY": body.builder_api_key,
        "POLYMARKET_BUILDER_SECRET": body.builder_secret,
        "POLYMARKET_BUILDER_PASSPHRASE": body.builder_passphrase,
        "POLYMARKET_RELAYER_API_KEY": body.relayer_api_key,
        "POLYMARKET_RELAYER_API_KEY_ADDRESS": body.relayer_api_key_address,
    }
    env_updates = {k: v.strip() for k, v in all_fields.items() if v and v.strip()}

    _persist_env_updates(env_updates)

    # Hot-reload into running settings object
    if body.private_key and body.private_key.strip():
        settings.POLYMARKET_PRIVATE_KEY = body.private_key.strip()
    if body.api_key and body.api_key.strip():
        settings.POLYMARKET_API_KEY = body.api_key.strip()
    if body.api_secret and body.api_secret.strip():
        settings.POLYMARKET_API_SECRET = body.api_secret.strip()
    if body.api_passphrase and body.api_passphrase.strip():
        settings.POLYMARKET_API_PASSPHRASE = body.api_passphrase.strip()
    if body.signature_type is not None:
        settings.POLYMARKET_SIGNATURE_TYPE = body.signature_type
    if body.builder_api_key and body.builder_api_key.strip():
        settings.POLYMARKET_BUILDER_API_KEY = body.builder_api_key.strip()
    if body.builder_secret and body.builder_secret.strip():
        settings.POLYMARKET_BUILDER_SECRET = body.builder_secret.strip()
    if body.builder_passphrase and body.builder_passphrase.strip():
        settings.POLYMARKET_BUILDER_PASSPHRASE = body.builder_passphrase.strip()
    if body.relayer_api_key and body.relayer_api_key.strip():
        settings.POLYMARKET_RELAYER_API_KEY = body.relayer_api_key.strip()
    if body.relayer_api_key_address and body.relayer_api_key_address.strip():
        settings.POLYMARKET_RELAYER_API_KEY_ADDRESS = (
            body.relayer_api_key_address.strip()
        )

    has_private_key = bool(settings.POLYMARKET_PRIVATE_KEY)
    has_api_key = bool(settings.POLYMARKET_API_KEY)
    has_api_secret = bool(settings.POLYMARKET_API_SECRET)
    has_api_passphrase = bool(settings.POLYMARKET_API_PASSPHRASE)
    has_builder_key = bool(settings.POLYMARKET_BUILDER_API_KEY)

    logger.info(f"Credentials updated: {list(env_updates.keys())}")

    # Restart polyedge-bot to pick up new credentials
    import asyncio as _asyncio

    try:
        _proc = await _asyncio.create_subprocess_exec(
            "pm2",
            "restart",
            "polyedge-bot",
            stdout=_asyncio.subprocess.PIPE,
            stderr=_asyncio.subprocess.PIPE,
        )
        await _asyncio.wait_for(_proc.communicate(), timeout=10)
        logger.info("polyedge-bot restarted to apply new credentials")
    except Exception as _e:
        logger.warning(f"Could not restart polyedge-bot: {_e}")

    _sig = settings.POLYMARKET_SIGNATURE_TYPE
    _creds_live_ok = (
        has_private_key
        if _sig in (1, 2)
        else has_private_key and has_api_key and has_api_secret and has_api_passphrase
    )
    _missing_live = (
        [] if has_private_key else ["POLYMARKET_PRIVATE_KEY"]
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
        "signature_type": settings.POLYMARKET_SIGNATURE_TYPE,
    }


@router.get("/system")
async def get_admin_system(
    request: Request, db: Session = Depends(get_db), _: None = Depends(require_admin)
):
    """Return system health overview."""
    state = for_update(db, db.query(BotState)).first()
    pending_trades = (
        db.query(Trade)
        .filter(Trade.settled.is_(False), Trade.trading_mode.in_(settings.active_modes_set))
        .count()
    )
    db_trade_count = db.query(Trade).filter(Trade.trading_mode.in_(settings.active_modes_set)).count()
    db_signal_count = db.query(Signal).count()

    uptime = (
        datetime.now(timezone.utc)
        - (
            request.app.state.start_time
            if hasattr(request.app.state, "start_time")
            else datetime.now(timezone.utc)
        )
    ).total_seconds()

    has_private_key = bool(settings.POLYMARKET_PRIVATE_KEY)
    has_api_key = bool(settings.POLYMARKET_API_KEY)
    has_api_secret = bool(settings.POLYMARKET_API_SECRET)
    has_api_passphrase = bool(settings.POLYMARKET_API_PASSPHRASE)
    has_builder_key = bool(settings.POLYMARKET_BUILDER_API_KEY)

    # For signature types 1 (Poly-Proxy) and 2 (Poly-EOA), API credentials
    # are auto-derived from the private key at startup — separate env vars
    # are NOT required.  For type 0 (EOA), all three must be set explicitly.
    _sig_type = settings.POLYMARKET_SIGNATURE_TYPE
    if _sig_type in (1, 2):
        creds_live_ok = has_private_key
        missing_for_live = (
            [] if has_private_key else ["POLYMARKET_PRIVATE_KEY"]
        )
    else:
        creds_live_ok = (
            has_private_key
            and has_api_key
            and has_api_secret
            and has_api_passphrase
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

    return {
        "trading_mode": settings.TRADING_MODE,
        "active_modes": sorted(settings.active_modes_set),
        "bot_running": state.is_running if state else False,
        "uptime_seconds": int(uptime),
        "pending_trades": pending_trades,
        "telegram_configured": bool(settings.TELEGRAM_BOT_TOKEN),
        "kalshi_enabled": settings.KALSHI_ENABLED,
        "weather_enabled": settings.WEATHER_ENABLED,
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
        "signature_type": settings.POLYMARKET_SIGNATURE_TYPE,
        "signature_type_label": {
            0: "EOA (direct wallet)",
            1: "Poly-Proxy (email login)",
            2: "Poly-EOA (PK maps to proxy)",
        }.get(settings.POLYMARKET_SIGNATURE_TYPE, "Unknown"),
    }


@router.post("/alerts/test")
async def test_alert(_: None = Depends(require_admin)):
    """Send a test Telegram alert to verify bot configuration."""
    from backend.core.heartbeat import _send_telegram_alert_sync

    if not settings.TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=400, detail="TELEGRAM_BOT_TOKEN not configured")
    _send_telegram_alert_sync("✅ PolyEdge alert test — bot is configured correctly")
    return {"status": "ok", "message": "Test alert sent"}


@router.get("/ai/suggest")
async def ai_suggest_params(
    db: Session = Depends(get_db), _: None = Depends(require_admin)
):
    """Use AI to analyze recent performance and suggest parameter improvements."""
    from backend.ai.optimizer import ParameterOptimizer

    optimizer = ParameterOptimizer(settings)
    return await optimizer.get_suggestions(db)


@router.get("/scheduler/jobs")
async def get_scheduler_jobs_endpoint(_: None = Depends(require_admin)):
    """Return current APScheduler job list."""
    from backend.core.scheduler import get_scheduler_jobs

    return get_scheduler_jobs()
