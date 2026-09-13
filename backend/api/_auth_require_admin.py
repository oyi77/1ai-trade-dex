"""Carved verbatim out of ``backend/api/auth.py`` — statements moved, no logic changed."""

from .auth import (
    BaseModel,
    Cookie,
    Header,
    Response,
    router,
)

from . import auth as _facade

def require_admin(authorization: str | None = Header(None)):
    """Require admin API key if ADMIN_API_KEY is configured."""
    key = _facade.settings.ADMIN_API_KEY
    if not key:
        raise _facade.HTTPException(
            status_code=403,
            detail="Admin access denied — ADMIN_API_KEY not configured",
        )
    if not authorization or authorization != f"Bearer {key}":
        raise _facade.HTTPException(
            status_code=401,
            detail="Unauthorized — set Authorization: Bearer <ADMIN_API_KEY>",
        )
class AdminLoginBody(BaseModel):
    password: str
class ChangePasswordBody(BaseModel):
    new_password: str
def _is_secret(field_name: str) -> bool:
    upper = field_name.upper()
    return any(kw in upper for kw in _facade._SECRET_KEYWORDS)
def _mask_value(field_name: str, value) -> str:
    if value is None or value == "" or value == "None":
        return ""
    if _is_secret(field_name):
        return "****"
    return value
def _cleanup_expired_sessions() -> None:
    """Remove sessions older than TTL and enforce max store size."""
    now = _facade.time.time()
    expired = [
        tok
        for tok, data in _facade._SESSION_STORE.items()
        if now - data["created_at"] > _facade._SESSION_TTL_SECONDS
    ]
    for tok in expired:
        del _facade._SESSION_STORE[tok]
    # E-95: Evict oldest sessions if store exceeds max size
    if len(_facade._SESSION_STORE) > _facade._SESSION_MAX_SIZE:
        sorted_sessions = sorted(
            _facade._SESSION_STORE.items(), key=lambda x: x[1]["created_at"]
        )
        for tok, _ in sorted_sessions[: len(_facade._SESSION_STORE) - _facade._SESSION_MAX_SIZE]:
            del _facade._SESSION_STORE[tok]
class CookieLoginBody(BaseModel):
    admin_key: str
@router.post("/auth/login")
def cookie_login(body: CookieLoginBody, response: Response):
    """Login with admin_key, receive httpOnly cookie + CSRF token."""
    _cleanup_expired_sessions()
    key = _facade.settings.ADMIN_API_KEY
    if not key:
        raise _facade.HTTPException(
            status_code=400,
            detail="No ADMIN_API_KEY configured — cookie auth unavailable",
        )
    if body.admin_key != key:
        raise _facade.HTTPException(status_code=401, detail="Invalid credentials")

    session_token = _facade.secrets.token_urlsafe(32)
    csrf_token = _facade.secrets.token_urlsafe(32)
    _facade._SESSION_STORE[session_token] = {"created_at": _facade.time.time(), "csrf": csrf_token}

    response.set_cookie(
        key=_facade._COOKIE_NAME,
        value=session_token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=_facade._SESSION_TTL_SECONDS,
        path="/api",
    )
    return {"csrf_token": csrf_token, "message": "Login successful"}
@router.post("/auth/logout")
def cookie_logout(response: Response, admin_session: str | None = Cookie(None)):
    """Clear the session cookie."""
    if admin_session and admin_session in _facade._SESSION_STORE:
        del _facade._SESSION_STORE[admin_session]
    response.delete_cookie(key=_facade._COOKIE_NAME, path="/api")
    return {"message": "Logged out"}
def require_admin_from_cookie(
    admin_session: str | None = Cookie(None),
    x_csrf_token: str | None = Header(None),
    authorization: str | None = Header(None),
):
    """Authenticate via cookie + CSRF OR via Bearer header (backward compat)."""
    key = _facade.settings.ADMIN_API_KEY
    if not key:
        raise _facade.HTTPException(
            status_code=403, detail="Admin access denied — ADMIN_API_KEY not configured"
        )

    # Backward compat: Bearer header auth
    if authorization and authorization == f"Bearer {key}":
        return

    # Cookie-based auth
    if not admin_session or admin_session not in _facade._SESSION_STORE:
        raise _facade.HTTPException(
            status_code=401, detail="Unauthorized — invalid or expired session"
        )

    session = _facade._SESSION_STORE[admin_session]

    # Check session expiry
    if _facade.time.time() - session["created_at"] > _facade._SESSION_TTL_SECONDS:
        del _facade._SESSION_STORE[admin_session]
        raise _facade.HTTPException(status_code=401, detail="Session expired")

    # CSRF validation for mutating requests (caller must validate via require_csrf)
    # This dep just ensures the session is valid
    return session
def require_csrf(
    x_csrf_token: str | None = Header(None),
    admin_session: str | None = Cookie(None),
    authorization: str | None = Header(None),
):
    """Validate CSRF token for cookie-authenticated mutating requests."""
    key = _facade.settings.ADMIN_API_KEY
    if not key:
        raise _facade.HTTPException(
            status_code=403, detail="Admin access denied — ADMIN_API_KEY not configured"
        )
    if authorization and authorization == f"Bearer {key}":
        return
    if not admin_session or admin_session not in _facade._SESSION_STORE:
        raise _facade.HTTPException(status_code=401, detail="Unauthorized — no valid session")
    session = _facade._SESSION_STORE[admin_session]
    if not x_csrf_token or x_csrf_token != session.get("csrf"):
        raise _facade.HTTPException(status_code=403, detail="CSRF token missing or invalid")
def _get_valid_session(admin_session: str | None) -> dict | None:
    """Return session dict when cookie session exists and is not expired."""
    if not admin_session:
        return None
    session = _facade._SESSION_STORE.get(admin_session)
    if not session:
        return None
    if _facade.time.time() - session["created_at"] > _facade._SESSION_TTL_SECONDS:
        del _facade._SESSION_STORE[admin_session]
        return None
    return session
def authorize_realtime_access(
    token: str | None = None, admin_session: str | None = None
) -> bool:
    """Authorize SSE/WebSocket access — requires valid auth.

    Checks: Bearer token matches ADMIN_API_KEY, or a valid cookie session exists.
    Returns False (rejects) when no valid credential is provided.
    """
    key = _facade.settings.ADMIN_API_KEY

    # If no admin key is configured, reject all realtime access
    if not key:
        return False

    # Check Bearer token
    if token and token == key:
        return True

    # Check cookie-based session
    session = _get_valid_session(admin_session)
    if session:
        return True

    return False
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
    if _facade.os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line_stripped = line.strip()
                if "=" in line_stripped and not line_stripped.startswith("#"):
                    k, v = line_stripped.split("=", 1)
                    env_lines[k.strip()] = v.strip()

    # Merge updates
    env_lines.update(updates)

    # Atomic write: write to temp file in same dir, then rename
    env_dir = _facade.os.path.dirname(_facade.os.path.abspath(env_path)) or "."
    tmp_fd, tmp_path = tempfile.mkstemp(dir=env_dir, prefix=".env.tmp")
    try:
        with _facade.os.fdopen(tmp_fd, "w") as f:
            for k, v in env_lines.items():
                f.write(f"{k}={v}\n")
        _facade.os.replace(tmp_path, env_path)
    except Exception as e:
        _facade.logger.debug(f"Secret validation error: {e}")
        try:
            _facade.os.unlink(tmp_path)
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
        if hasattr(_facade.settings, field_name):
            raw = getattr(_facade.settings, field_name)
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
@router.get("/auth-required")
async def auth_required_endpoint():
    """Returns whether admin authentication is configured."""
    return {"auth_required": bool(_facade.settings.ADMIN_API_KEY)}
@router.post("/login")
async def admin_login(body: AdminLoginBody):
    """Verify admin password. Returns success; client stores the password as bearer token."""
    if not _facade.settings.ADMIN_API_KEY:
        return {"success": True, "auth_required": False}
    if body.password != _facade.settings.ADMIN_API_KEY:
        raise _facade.HTTPException(status_code=401, detail="Invalid password")
    return {"success": True, "auth_required": True}
