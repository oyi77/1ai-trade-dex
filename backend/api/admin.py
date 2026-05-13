"""Admin API — grouped settings view and system status.

Provides two endpoints:
  GET  /api/admin/settings  — grouped, secret-masked settings snapshot
  POST /api/admin/settings  — update one or more settings at runtime
  GET  /api/admin/system    — lightweight system / bot status

These endpoints complement the more granular /api/v1/settings routes by
exposing all config in a single grouped response that mirrors the
.env / settings object structure.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.api.auth import require_admin
from backend.config import settings
from backend.models.database import BotState, get_db
from sqlalchemy.orm import Session

from loguru import logger
router = APIRouter(prefix="/admin", tags=["admin"])

# ---------------------------------------------------------------------------
# Secret field names whose values must be masked in GET responses
# ---------------------------------------------------------------------------
_SECRET_FIELDS = {
    "POLYMARKET_API_KEY",
    "POLYMARKET_PRIVATE_KEY",
    "KALSHI_API_KEY",
    "KALSHI_API_SECRET",
    "ADMIN_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "ANTHROPIC_API_KEY",
    "GROQ_API_KEY",
    "OPENAI_API_KEY",
    "BIGBRAIN_API_KEY",
    "REDIS_PASSWORD",
}

_MASK = "****"


def _mask(key: str, value: Any) -> Any:
    """Return **** for non-empty secret values, raw value otherwise."""
    if key in _SECRET_FIELDS and value:
        return _MASK
    return value


def _grouped_settings() -> Dict[str, Dict[str, Any]]:
    """Build the grouped settings response from live settings object."""
    s = settings
    # Build grouped response
    grouped = {
        "trading": {
            "TRADING_MODE": s.TRADING_MODE,
            "ACTIVE_MODES": s.ACTIVE_MODES,
            "KELLY_FRACTION": s.KELLY_FRACTION,
            "MIN_EDGE_THRESHOLD": s.MIN_EDGE_THRESHOLD,
            "MAX_TRADE_SIZE": s.MAX_TRADE_SIZE,
            "DAILY_LOSS_LIMIT": s.DAILY_LOSS_LIMIT,
            "MAX_TOTAL_PENDING_TRADES": s.MAX_TOTAL_PENDING_TRADES,
            "MAX_TRADES_PER_WINDOW": s.MAX_TRADES_PER_WINDOW,
            "AI_ENABLED": s.AI_ENABLED,
        },
        "weather": {
            "WEATHER_ENABLED": s.WEATHER_ENABLED,
            "WEATHER_SCAN_INTERVAL_SECONDS": s.WEATHER_SCAN_INTERVAL_SECONDS,
            "WEATHER_SETTLEMENT_INTERVAL_SECONDS": s.WEATHER_SETTLEMENT_INTERVAL_SECONDS,
            "WEATHER_MIN_EDGE_THRESHOLD": s.WEATHER_MIN_EDGE_THRESHOLD,
            "WEATHER_MAX_ENTRY_PRICE": s.WEATHER_MAX_ENTRY_PRICE,
            "WEATHER_MAX_TRADE_SIZE": s.WEATHER_MAX_TRADE_SIZE,
            "WEATHER_CITIES": s.WEATHER_CITIES,
        },
        "api_keys": {
            "POLYMARKET_API_KEY": _mask("POLYMARKET_API_KEY", s.POLYMARKET_API_KEY),
            "POLYMARKET_PRIVATE_KEY": _mask("POLYMARKET_PRIVATE_KEY", getattr(s, "POLYMARKET_PRIVATE_KEY", None)),
            "KALSHI_API_KEY": _mask("KALSHI_API_KEY", getattr(s, "KALSHI_API_KEY", None)),
            "ADMIN_API_KEY": _mask("ADMIN_API_KEY", s.ADMIN_API_KEY),
            "ANTHROPIC_API_KEY": _mask("ANTHROPIC_API_KEY", getattr(s, "ANTHROPIC_API_KEY", None)),
            "GROQ_API_KEY": _mask("GROQ_API_KEY", getattr(s, "GROQ_API_KEY", None)),
        },
        "telegram": {
            "TELEGRAM_BOT_TOKEN": _mask("TELEGRAM_BOT_TOKEN", s.TELEGRAM_BOT_TOKEN),
            "TELEGRAM_ADMIN_CHAT_IDS": s.TELEGRAM_ADMIN_CHAT_IDS,
            "TELEGRAM_HIGH_CONFIDENCE_ALERTS": s.TELEGRAM_HIGH_CONFIDENCE_ALERTS,
        },
    }
    # Also return flat format for frontend compatibility
    grouped["mirofish_enabled"] = getattr(s, "MIROFISH_ENABLED", False)
    grouped["mirofish_api_url"] = getattr(s, "MIROFISH_API_URL", settings.MIROFISH_API_URL)
    grouped["mirofish_api_key"] = _mask("MIROFISH_API_KEY", getattr(s, "MIROFISH_API_KEY", ""))
    grouped["trading_mode"] = s.TRADING_MODE
    grouped["strategies"] = {
        "btc_momentum": getattr(s, "BTC_MOMENTUM_ENABLED", False),
        "btc_oracle": getattr(s, "BTC_ORACLE_ENABLED", False),
        "weather_emos": s.WEATHER_ENABLED,
        "copy_trader": getattr(s, "COPY_TRADER_ENABLED", False),
        "market_maker": getattr(s, "MARKET_MAKER_ENABLED", False),
        "kalshi_arb": s.KALSHI_ENABLED,
        "bond_scanner": getattr(s, "BOND_SCANNER_ENABLED", False),
        "whale_pnl": getattr(s, "WHALE_PNL_ENABLED", False),
        "realtime_scanner": getattr(s, "REALTIME_SCANNER_ENABLED", False),
    }
    grouped["risk"] = {
        "max_position_size": s.MAX_TRADE_SIZE,
        "max_portfolio_exposure": getattr(s, "MAX_POSITION_FRACTION", 0.15),
        "kelly_fraction": s.KELLY_FRACTION,
        "min_edge_threshold": s.MIN_EDGE_THRESHOLD,
    }
    return grouped


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class SettingsUpdateRequest(BaseModel):
    updates: Dict[str, Any]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/settings", dependencies=[Depends(require_admin)])
async def admin_get_settings():
    """Return all settings grouped by category.  Secrets are masked as ****."""
    return _grouped_settings()


@router.post("/settings", dependencies=[Depends(require_admin)])
async def admin_post_settings(body: SettingsUpdateRequest):
    """Update one or more settings at runtime.

    - Values of ``****`` are ignored (placeholder, do not overwrite secrets).
    - Newlines are stripped to prevent env-file injection.
    - Type coercion is attempted to match the existing field type.
    """
    applied: Dict[str, Any] = {}
    skipped: Dict[str, str] = {}

    for raw_key, raw_value in body.updates.items():
        key = raw_key.strip()

        # Skip placeholder / masked values
        if raw_value == _MASK:
            skipped[key] = "placeholder value ignored"
            continue

        # Strip newlines (env-file injection prevention)
        if isinstance(raw_value, str):
            raw_value = re.sub(r"[\r\n]", "", raw_value)

        if not hasattr(settings, key):
            skipped[key] = "unknown setting"
            continue

        current = getattr(settings, key)
        # Attempt type coercion to match existing field type
        try:
            if current is not None:
                target_type = type(current)
                coerced = target_type(raw_value)
            else:
                coerced = raw_value
            object.__setattr__(settings, key, coerced)
            applied[key] = coerced

            # Persist to .env if it exists (best-effort)
            _update_env_file(key, str(coerced))
        except Exception as exc:
            skipped[key] = f"type coercion failed: {exc}"

    return {"applied": applied, "skipped": skipped}


@router.get("/system", dependencies=[Depends(require_admin)])
async def admin_get_system(db: Session = Depends(get_db)):
    """Return lightweight system / bot status."""
    bot_state = db.query(BotState).first()
    response = {
        "trading_mode": settings.TRADING_MODE,
        "bot_running": bot_state.is_running if bot_state else False,
        "active_modes": settings.ACTIVE_MODES,
        "bankroll": bot_state.bankroll if bot_state else 0.0,
        "total_trades": bot_state.total_trades if bot_state else 0,
        "total_pnl": bot_state.total_pnl if bot_state else 0.0,
    }
    db.rollback()
    return response


# ---------------------------------------------------------------------------
# .env helper
# ---------------------------------------------------------------------------


def _update_env_file(key: str, value: str) -> None:
    """Update or append a key=value line in .env (best-effort, no crash)."""
    env_path = ".env"
    try:
        if not os.path.exists(env_path):
            return
        with open(env_path) as f:
            lines = f.readlines()
        pattern = re.compile(rf"^{re.escape(key)}\s*=")
        new_line = f"{key}={value}\n"
        replaced = False
        new_lines = []
        for line in lines:
            if pattern.match(line):
                new_lines.append(new_line)
                replaced = True
            else:
                new_lines.append(line)
        if not replaced:
            new_lines.append(new_line)
        with open(env_path, "w") as f:
            f.writelines(new_lines)
    except Exception as exc:
        logger.debug("Could not update .env: %s", exc)
