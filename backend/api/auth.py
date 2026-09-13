"""Authentication and admin routes."""

import secrets
import shutil
import time
from fastapi import Depends, HTTPException, Header, APIRouter, Request, Response, Cookie
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import datetime, timezone
import os

from backend.config import settings
from backend.models.database import get_db, BotState, Trade, Signal
from backend.api.validation import (
    CredentialsUpdateRequest as ValidatedCredentialsUpdate,
)

from loguru import logger

router = APIRouter(prefix="/admin", tags=["admin"])
_SECRET_KEYWORDS = {"KEY", "SECRET", "PASSWORD", "PASSPHRASE", "TOKEN", "PRIVATE"}
_SESSION_STORE: dict[str, dict] = {}
_SESSION_TTL_SECONDS = 86400  # 24 hours
_SESSION_MAX_SIZE = 256  # E-95: cap in-memory session store
_COOKIE_NAME = "admin_session"

from ._auth_require_admin import (  # noqa: E402  (must follow the names it imports back)
    AdminLoginBody,
    ChangePasswordBody,
    CookieLoginBody,
    SettingsUpdate,
    _cleanup_expired_sessions,
    _get_grouped_settings,
    _get_valid_session,
    _is_secret,
    _mask_value,
    _persist_env_updates,
    admin_login,
    auth_required_endpoint,
    authorize_realtime_access,
    cookie_login,
    cookie_logout,
    require_admin,
    require_admin_from_cookie,
    require_csrf,
)

from ._auth_change_admin_password import (  # noqa: E402  (must follow the names it imports back)
    CredentialsUpdate,
    ModeToggle,
    ai_suggest_params,
    change_admin_password,
    get_admin_system,
    get_scheduler_jobs_endpoint,
    test_alert,
    toggle_mode,
    update_credentials,
)


__all__ = [
    "APIRouter",
    "AdminLoginBody",
    "BaseModel",
    "BotState",
    "ChangePasswordBody",
    "Cookie",
    "CookieLoginBody",
    "CredentialsUpdate",
    "Depends",
    "HTTPException",
    "Header",
    "ModeToggle",
    "Request",
    "Response",
    "Session",
    "SettingsUpdate",
    "Signal",
    "Trade",
    "ValidatedCredentialsUpdate",
    "_COOKIE_NAME",
    "_SECRET_KEYWORDS",
    "_SESSION_MAX_SIZE",
    "_SESSION_STORE",
    "_SESSION_TTL_SECONDS",
    "_cleanup_expired_sessions",
    "_get_grouped_settings",
    "_get_valid_session",
    "_is_secret",
    "_mask_value",
    "_persist_env_updates",
    "admin_login",
    "ai_suggest_params",
    "auth_required_endpoint",
    "authorize_realtime_access",
    "change_admin_password",
    "cookie_login",
    "cookie_logout",
    "datetime",
    "get_admin_system",
    "get_db",
    "get_scheduler_jobs_endpoint",
    "logger",
    "os",
    "require_admin",
    "require_admin_from_cookie",
    "require_csrf",
    "router",
    "secrets",
    "settings",
    "shutil",
    "test_alert",
    "time",
    "timezone",
    "toggle_mode",
    "update_credentials",
]
