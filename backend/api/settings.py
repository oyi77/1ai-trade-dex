"""Settings API endpoints for system configuration."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional
from datetime import datetime, timezone
import asyncio

from backend.api.auth import require_admin
from backend.models.database import get_db, SystemSettings
from backend.config import settings as app_settings
from backend.db.utils import utcnow

from loguru import logger

router = APIRouter(prefix="/settings", tags=["settings"])
MIROFISH_BACKEND_DIR = "../../mirofish/backend"
MIROFISH_FRONTEND_DIR = "../../mirofish/frontend"
MIROFISH_BACKEND_PORT = 5001
MIROFISH_FRONTEND_PORT = 3200

from ._settings_settingsresponse import (  # noqa: E402  (must follow the names it imports back)
    BulkSettingUpdateRequest,
    SettingItemResponse,
    SettingsResponse,
    SettingsUpdateRequest,
    TestMiroFishRequest,
    TestMiroFishResponse,
    ToggleResponse,
    _get_setting,
    _set_setting,
    bulk_update_settings,
    get_settings,
    list_all_settings,
    toggle_mirofish,
    toggle_strategy,
    update_settings,
)

from ._settings_test_mirofish import (  # noqa: E402  (must follow the names it imports back)
    CreateRiskProfileRequest,
    ProcessStatus,
    RiskProfileListResponse,
    RiskProfileResponse,
    ServiceActionResponse,
    SetRiskProfileRequest,
    UpdateRiskProfileRequest,
    _find_process_by_port,
    _kill_process,
    _profile_to_response,
    _start_mirofish_backend,
    _start_mirofish_frontend,
    get_mirofish_processes,
    get_mirofish_service_status,
    get_risk_profiles,
    mirofish_service_pause,
    mirofish_service_restart,
    mirofish_service_start,
    mirofish_service_stop,
    restart_mirofish_processes,
    set_risk_profile,
    start_mirofish_processes,
    stop_mirofish_processes,
    test_mirofish,
    update_risk_profile,
)

from ._settings_create_risk_profile import (  # noqa: E402  (must follow the names it imports back)
    create_risk_profile,
    delete_risk_profile,
    get_mirofish_signals,
)


__all__ = [
    "APIRouter",
    "Any",
    "BaseModel",
    "BulkSettingUpdateRequest",
    "CreateRiskProfileRequest",
    "Depends",
    "Dict",
    "HTTPException",
    "MIROFISH_BACKEND_DIR",
    "MIROFISH_BACKEND_PORT",
    "MIROFISH_FRONTEND_DIR",
    "MIROFISH_FRONTEND_PORT",
    "Optional",
    "ProcessStatus",
    "RiskProfileListResponse",
    "RiskProfileResponse",
    "ServiceActionResponse",
    "Session",
    "SetRiskProfileRequest",
    "SettingItemResponse",
    "SettingsResponse",
    "SettingsUpdateRequest",
    "SystemSettings",
    "TestMiroFishRequest",
    "TestMiroFishResponse",
    "ToggleResponse",
    "UpdateRiskProfileRequest",
    "_find_process_by_port",
    "_get_setting",
    "_kill_process",
    "_profile_to_response",
    "_set_setting",
    "_start_mirofish_backend",
    "_start_mirofish_frontend",
    "app_settings",
    "asyncio",
    "bulk_update_settings",
    "create_risk_profile",
    "datetime",
    "delete_risk_profile",
    "get_db",
    "get_mirofish_processes",
    "get_mirofish_service_status",
    "get_mirofish_signals",
    "get_risk_profiles",
    "get_settings",
    "list_all_settings",
    "logger",
    "mirofish_service_pause",
    "mirofish_service_restart",
    "mirofish_service_start",
    "mirofish_service_stop",
    "require_admin",
    "restart_mirofish_processes",
    "router",
    "set_risk_profile",
    "start_mirofish_processes",
    "stop_mirofish_processes",
    "test_mirofish",
    "timezone",
    "toggle_mirofish",
    "toggle_strategy",
    "update_risk_profile",
    "update_settings",
    "utcnow",
]
