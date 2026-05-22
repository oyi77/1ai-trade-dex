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

from loguru import logger

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsResponse(BaseModel):
    mirofish_enabled: bool
    mirofish_api_url: Optional[str]
    mirofish_api_key: Optional[str]
    strategies: Dict[str, bool]
    risk_params: Dict[str, Any]
    trading_mode: str


class SettingsUpdateRequest(BaseModel):
    mirofish_enabled: Optional[bool] = None
    mirofish_api_url: Optional[str] = None
    mirofish_api_key: Optional[str] = None
    strategies: Optional[Dict[str, bool]] = None
    risk_params: Optional[Dict[str, Any]] = None
    trading_mode: Optional[str] = None


class ToggleResponse(BaseModel):
    enabled: bool
    message: str


class TestMiroFishRequest(BaseModel):
    api_url: str
    api_key: str


class TestMiroFishResponse(BaseModel):
    success: bool
    message: str
    signals_count: Optional[int] = None
    error: Optional[str] = None


def _get_setting(db: Session, key: str, default: Any = None) -> Any:
    setting = db.query(SystemSettings).filter(SystemSettings.key == key).first()
    if setting:
        return setting.value
    return default


def _set_setting(db: Session, key: str, value: Any):
    setting = db.query(SystemSettings).filter(SystemSettings.key == key).first()
    if setting:
        setting.value = value
        setting.updated_at = datetime.now(timezone.utc)
    else:
        setting = SystemSettings(key=key, value=value)
        db.add(setting)


@router.get("", response_model=SettingsResponse)
async def get_settings(db: Session = Depends(get_db)):
    try:
        mirofish_enabled = _get_setting(db, "mirofish_enabled", False)
        mirofish_api_url = _get_setting(db, "mirofish_api_url", None)
        mirofish_api_key = _get_setting(db, "mirofish_api_key", None)
        strategies = _get_setting(db, "strategies_enabled", {})
        risk_params = _get_setting(
            db,
            "risk_params",
            {
                "max_position_size": app_settings.MAX_TRADE_SIZE,
                "max_daily_loss": app_settings.DAILY_LOSS_LIMIT,
                "max_total_pending": app_settings.MAX_TOTAL_PENDING_TRADES,
            },
        )
        trading_mode = _get_setting(db, "trading_mode", app_settings.TRADING_MODE)

        return SettingsResponse(
            mirofish_enabled=mirofish_enabled,
            mirofish_api_url=mirofish_api_url,
            mirofish_api_key=mirofish_api_key,
            strategies=strategies,
            risk_params=risk_params,
            trading_mode=trading_mode,
        )
    except Exception as e:
        logger.error(f"Failed to get settings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve settings")


@router.put("")
async def update_settings(
    updates: SettingsUpdateRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    from backend.models.audit_logger import log_audit_event

    try:
        # Track changes for audit logging
        changes = {}

        if updates.mirofish_enabled is not None:
            old_value = _get_setting(db, "mirofish_enabled", False)
            _set_setting(db, "mirofish_enabled", updates.mirofish_enabled)
            changes["mirofish_enabled"] = {
                "old": old_value,
                "new": updates.mirofish_enabled,
            }

        if updates.mirofish_api_url is not None:
            old_value = _get_setting(db, "mirofish_api_url", None)
            _set_setting(db, "mirofish_api_url", updates.mirofish_api_url)
            changes["mirofish_api_url"] = {"old": old_value, "new": "[REDACTED]"}

        if updates.mirofish_api_key is not None:
            old_value = _get_setting(db, "mirofish_api_key", None)
            _set_setting(db, "mirofish_api_key", updates.mirofish_api_key)
            changes["mirofish_api_key"] = {"old": "[REDACTED]", "new": "[REDACTED]"}

        if updates.strategies is not None:
            old_value = _get_setting(db, "strategies_enabled", {})
            _set_setting(db, "strategies_enabled", updates.strategies)
            changes["strategies_enabled"] = {
                "old": old_value,
                "new": updates.strategies,
            }

        if updates.risk_params is not None:
            old_value = _get_setting(db, "risk_params", {})
            _set_setting(db, "risk_params", updates.risk_params)
            changes["risk_params"] = {"old": old_value, "new": updates.risk_params}

        if updates.trading_mode is not None:
            if updates.trading_mode not in ["paper", "testnet", "live"]:
                raise HTTPException(status_code=400, detail="Invalid trading mode")
            old_value = _get_setting(db, "trading_mode", app_settings.TRADING_MODE)
            _set_setting(db, "trading_mode", updates.trading_mode)
            changes["trading_mode"] = {"old": old_value, "new": updates.trading_mode}

        # Log audit event for configuration changes
        if changes:
            log_audit_event(
                db=db,
                event_type="CONFIG_UPDATED",
                entity_type="SYSTEM_SETTINGS",
                entity_id="global",
                old_value={"changes": {k: v["old"] for k, v in changes.items()}},
                new_value={"changes": {k: v["new"] for k, v in changes.items()}},
                user_id="admin",
            )

        db.commit()
        logger.info("Settings updated successfully")

        return {"status": "ok", "message": "Settings updated successfully"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update settings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update settings")


class SettingItemResponse(BaseModel):
    id: int
    key: str
    value: Any
    description: Optional[str] = None
    type: str = "string"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by_user_id: str = "admin"


class BulkSettingUpdateRequest(BaseModel):
    updates: list  # Array of {key: string, value: string}


@router.get("/list", response_model=list[SettingItemResponse])
async def list_all_settings(
    db: Session = Depends(get_db), _: None = Depends(require_admin)
):
    """Return all SystemSettings rows as an array for the SettingsEditor UI."""
    rows = db.query(SystemSettings).order_by(SystemSettings.key).all()
    result = []
    for row in rows:
        val = row.value
        if isinstance(val, bool):
            stype = "bool"
        elif isinstance(val, int):
            stype = "int"
        elif isinstance(val, float):
            stype = "float"
        else:
            stype = "string"
        result.append(
            SettingItemResponse(
                id=row.id,
                key=row.key,
                value=str(val) if not isinstance(val, str) else val,
                description=None,
                type=stype,
                created_at=str(row.updated_at) if row.updated_at else None,
                updated_at=str(row.updated_at) if row.updated_at else None,
                updated_by_user_id="admin",
            )
        )
    return result


@router.put("/list")
async def bulk_update_settings(
    body: BulkSettingUpdateRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Bulk update settings from array of {key, value} pairs."""

    # Keys that should be propagated to app_settings at runtime
    RUNTIME_MUTABLE_KEYS = {
        "PAPER_SLIPPAGE_BPS",
        "PAPER_MIN_SLIPPAGE_BPS",
        "PAPER_SIZE_IMPACT_FACTOR",
        "PAPER_CLOB_FEE_RATE",
        "PAPER_MIN_DEPTH_USD",
        "PAPER_RANDOM_SLIPPAGE",
        "MIROFISH_ENABLED",
        "MIROFISH_API_URL",
        "MIROFISH_API_KEY",
        "TRADING_MODE",
        "SIGNAL_APPROVAL_MODE",
    }

    updated = 0
    mutated_app_settings = []

    for item in body.updates:
        key = item.get("key")
        value = item.get("value")
        if not key:
            continue
        # Parse value types
        row = db.query(SystemSettings).filter(SystemSettings.key == key).first()
        if row:
            # Try to preserve type
            if isinstance(row.value, bool):
                value = value in ("true", "True", "1", True)
            elif isinstance(row.value, int):
                try:
                    value = int(value)
                except (ValueError, TypeError):
                    logger.warning(
                        "Setting %s: could not convert '%s' to int, keeping as string",
                        key,
                        value,
                    )
            elif isinstance(row.value, float):
                try:
                    value = float(value)
                except (ValueError, TypeError):
                    logger.warning(
                        "Setting %s: could not convert '%s' to float, keeping as string",
                        key,
                        value,
                    )
            row.value = value
            row.updated_at = datetime.now(timezone.utc)
        else:
            db.add(SystemSettings(key=key, value=value))
        updated += 1

        # Propagate to app_settings for runtime effect
        if key in RUNTIME_MUTABLE_KEYS and hasattr(app_settings, key):
            try:
                current_val = getattr(app_settings, key)
                if isinstance(current_val, bool):
                    coerced = (
                        value in ("true", "True", "1", True)
                        if isinstance(value, str)
                        else bool(value)
                    )
                elif isinstance(current_val, int):
                    coerced = int(value)
                elif isinstance(current_val, float):
                    coerced = float(value)
                else:
                    coerced = str(value) if not isinstance(value, str) else value
                object.__setattr__(app_settings, key, coerced)
                mutated_app_settings.append((key, coerced))
            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to setattr app_settings.{key}={value}: {e}")

    db.commit()

    # Clear config_service cache so next reads pick up new values
    if mutated_app_settings:
        try:
            from backend.core.config_service import _settings_cache, _cache_lock

            with _cache_lock:
                for key, _ in mutated_app_settings:
                    _settings_cache.pop(key, None)
        except ImportError:
            pass
        logger.info(f"Runtime settings updated: {mutated_app_settings}")

    return {
        "status": "ok",
        "message": f"Updated {updated} settings",
        "updated": updated,
    }


@router.post("/mirofish/toggle", response_model=ToggleResponse)
async def toggle_mirofish(
    db: Session = Depends(get_db), _: None = Depends(require_admin)
):
    from backend.models.audit_logger import log_audit_event

    try:
        current = _get_setting(db, "mirofish_enabled", False)
        new_state = not current
        _set_setting(db, "mirofish_enabled", new_state)

        object.__setattr__(app_settings, "MIROFISH_ENABLED", new_state)

        log_audit_event(
            db=db,
            event_type="MIROFISH_TOGGLE",
            entity_type="CONFIG",
            entity_id="mirofish_enabled",
            old_value={"enabled": current},
            new_value={"enabled": new_state},
            user_id="admin",
        )

        db.commit()

        logger.info(f"MiroFish toggled: {current} -> {new_state}")

        return ToggleResponse(
            enabled=new_state,
            message=f"MiroFish {'enabled' if new_state else 'disabled'}",
        )
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to toggle MiroFish: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to toggle MiroFish")


@router.post("/strategy/{name}/toggle", response_model=ToggleResponse)
async def toggle_strategy(
    name: str, db: Session = Depends(get_db), _: None = Depends(require_admin)
):
    from backend.models.audit_logger import log_audit_event

    try:
        strategies = _get_setting(db, "strategies_enabled", {})
        current = strategies.get(name, False)
        new_state = not current
        strategies[name] = new_state
        _set_setting(db, "strategies_enabled", strategies)

        log_audit_event(
            db=db,
            event_type="STRATEGY_TOGGLE",
            entity_type="STRATEGY_CONFIG",
            entity_id=name,
            old_value={"enabled": current},
            new_value={"enabled": new_state},
            user_id="admin",
        )

        db.commit()

        logger.info(f"Strategy '{name}' toggled: {current} -> {new_state}")

        return ToggleResponse(
            enabled=new_state,
            message=f"Strategy '{name}' {'enabled' if new_state else 'disabled'}",
        )
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to toggle strategy '{name}': {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to toggle strategy '{name}'"
        )


@router.post("/test-mirofish", response_model=TestMiroFishResponse)
async def test_mirofish(
    request: TestMiroFishRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Test MiroFish API connection with provided credentials.

    Validates that the provided API URL and key can successfully fetch signals.
    Does not save credentials to database.
    """
    try:
        from backend.ai.mirofish_client import MiroFishClient

        logger.info(f"Testing MiroFish connection: {request.api_url}")

        client = MiroFishClient(api_url=request.api_url, api_key=request.api_key)

        # Test fetch_signals with timeout
        try:
            signals = await asyncio.wait_for(
                client.fetch_signals(market="polymarket"), timeout=10.0
            )

            logger.info(f"MiroFish test successful: {len(signals)} signals fetched")

            return TestMiroFishResponse(
                success=True,
                message=f"Connection successful. Fetched {len(signals)} signals.",
                signals_count=len(signals),
            )

        except asyncio.TimeoutError:
            logger.warning("MiroFish test timed out after 10 seconds")
            return TestMiroFishResponse(
                success=False,
                message="Connection test timed out after 10 seconds",
                error="timeout",
            )
        except Exception as e:
            error_msg = str(e)
            logger.error(f"MiroFish test failed: {error_msg}", exc_info=True)

            # Determine error type without exposing sensitive details
            if "401" in error_msg or "unauthorized" in error_msg.lower():
                return TestMiroFishResponse(
                    success=False,
                    message="Authentication failed. Check your API key.",
                    error="authentication",
                )
            elif "404" in error_msg or "not found" in error_msg.lower():
                return TestMiroFishResponse(
                    success=False,
                    message="API endpoint not found. Check your API URL.",
                    error="not_found",
                )
            elif "connection" in error_msg.lower():
                return TestMiroFishResponse(
                    success=False,
                    message="Connection failed. Check your API URL and network.",
                    error="connection",
                )
            else:
                return TestMiroFishResponse(
                    success=False,
                    message="Connection test failed. Please check your credentials.",
                    error=error_msg,
                )
    except Exception as e:
        logger.error(f"Unexpected error during MiroFish test: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="Failed to test MiroFish connection"
        )


class ServiceActionResponse(BaseModel):
    success: bool
    message: str
    state: str
    data: Optional[Dict[str, Any]] = None


@router.get("/mirofish/status")
async def get_mirofish_service_status():
    from backend.services.mirofish_service import get_mirofish_service

    service = get_mirofish_service()
    return service.get_status()


@router.post("/mirofish/start", response_model=ServiceActionResponse)
async def mirofish_service_start(_: None = Depends(require_admin)):
    from backend.services.mirofish_service import get_mirofish_service

    service = get_mirofish_service()
    result = service.start()
    logger.info(f"MiroFish service start: {result['message']}")

    return ServiceActionResponse(
        success=True,
        message=result["message"],
        state=result["state"],
        data=result,
    )


@router.post("/mirofish/stop", response_model=ServiceActionResponse)
async def mirofish_service_stop(_: None = Depends(require_admin)):
    from backend.services.mirofish_service import get_mirofish_service

    service = get_mirofish_service()
    result = service.stop()
    logger.info(f"MiroFish service stop: {result['message']}")

    return ServiceActionResponse(
        success=True,
        message=result["message"],
        state=result["state"],
        data=result,
    )


@router.post("/mirofish/pause", response_model=ServiceActionResponse)
async def mirofish_service_pause(_: None = Depends(require_admin)):
    from backend.services.mirofish_service import get_mirofish_service

    service = get_mirofish_service()
    result = service.pause()

    return ServiceActionResponse(
        success=True,
        message=result["message"],
        state=result["state"],
        data=result,
    )


# ============== MiroFish Process Management ==============

MIROFISH_BACKEND_DIR = "../../mirofish/backend"
MIROFISH_FRONTEND_DIR = "../../mirofish/frontend"
MIROFISH_BACKEND_PORT = 5001
MIROFISH_FRONTEND_PORT = 3200


def _find_process_by_port(port: int) -> Optional[int]:
    """Find PID listening on a given port."""
    try:
        import subprocess

        result = subprocess.run(
            ["lsof", "-ti", f":{port}"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            pids = result.stdout.strip().split("\n")
            return int(pids[0])
    except Exception:
        logger.exception(f"Failed to find process on port {port}")
        pass
    return None


def _kill_process(pid: int):
    """Kill a process by PID."""
    import subprocess

    try:
        subprocess.run(["kill", str(pid)], timeout=5)
    except Exception:
        logger.exception(f"Failed to kill process {pid}")


def _start_mirofish_backend():
    import subprocess
    import os

    venv_python = os.path.join(MIROFISH_BACKEND_DIR, "venv", "bin", "python")
    env = {**os.environ}
    # E-96: Pipe stderr to PIPE so startup errors are not silently swallowed
    return subprocess.Popen(
        [venv_python, "run.py"],
        cwd=MIROFISH_BACKEND_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def _start_mirofish_frontend():
    import subprocess

    # E-96: Pipe stderr to PIPE so startup errors are not silently swallowed
    return subprocess.Popen(
        ["npx", "vite", "preview", "--port", str(MIROFISH_FRONTEND_PORT), "--host"],
        cwd=MIROFISH_FRONTEND_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        shell=False,
    )


class ProcessStatus(BaseModel):
    backend_running: bool
    backend_pid: Optional[int]
    frontend_running: bool
    frontend_pid: Optional[int]


@router.get("/mirofish/processes")
async def get_mirofish_processes(_: None = Depends(require_admin)):
    """Check if MiroFish backend and frontend processes are running."""
    backend_pid = _find_process_by_port(MIROFISH_BACKEND_PORT)
    frontend_pid = _find_process_by_port(MIROFISH_FRONTEND_PORT)
    return ProcessStatus(
        backend_running=backend_pid is not None,
        backend_pid=backend_pid,
        frontend_running=frontend_pid is not None,
        frontend_pid=frontend_pid,
    )


@router.post("/mirofish/processes/start")
async def start_mirofish_processes(_: None = Depends(require_admin)):
    """Start both MiroFish backend and frontend processes."""
    results = {"backend": None, "frontend": None}

    backend_pid = _find_process_by_port(MIROFISH_BACKEND_PORT)
    if backend_pid is None:
        try:
            _start_mirofish_backend()
            results["backend"] = "started"
        except Exception as e:
            results["backend"] = f"failed: {e}"
    else:
        results["backend"] = f"already running (pid={backend_pid})"

    frontend_pid = _find_process_by_port(MIROFISH_FRONTEND_PORT)
    if frontend_pid is None:
        try:
            _start_mirofish_frontend()
            results["frontend"] = "started"
        except Exception as e:
            results["frontend"] = f"failed: {e}"
    else:
        results["frontend"] = f"already running (pid={frontend_pid})"

    return {"success": True, "results": results}


@router.post("/mirofish/processes/stop")
async def stop_mirofish_processes(_: None = Depends(require_admin)):
    """Stop both MiroFish backend and frontend processes."""
    results = {"backend": None, "frontend": None}

    backend_pid = _find_process_by_port(MIROFISH_BACKEND_PORT)
    if backend_pid:
        _kill_process(backend_pid)
        results["backend"] = f"stopped (was pid={backend_pid})"
    else:
        results["backend"] = "not running"

    frontend_pid = _find_process_by_port(MIROFISH_FRONTEND_PORT)
    if frontend_pid:
        _kill_process(frontend_pid)
        results["frontend"] = f"stopped (was pid={frontend_pid})"
    else:
        results["frontend"] = "not running"

    return {"success": True, "results": results}


@router.post("/mirofish/processes/restart")
async def restart_mirofish_processes(_: None = Depends(require_admin)):
    """Restart both MiroFish backend and frontend processes."""
    # Stop first
    backend_pid = _find_process_by_port(MIROFISH_BACKEND_PORT)
    if backend_pid:
        _kill_process(backend_pid)
    frontend_pid = _find_process_by_port(MIROFISH_FRONTEND_PORT)
    if frontend_pid:
        _kill_process(frontend_pid)

    await asyncio.sleep(1)

    # Start both
    results = {"backend": None, "frontend": None}
    try:
        _start_mirofish_backend()
        results["backend"] = "restarted"
    except Exception as e:
        results["backend"] = f"failed: {e}"

    try:
        _start_mirofish_frontend()
        results["frontend"] = "restarted"
    except Exception as e:
        results["frontend"] = f"failed: {e}"

    return {"success": True, "results": results}


@router.post("/mirofish/restart", response_model=ServiceActionResponse)
async def mirofish_service_restart(_: None = Depends(require_admin)):
    from backend.services.mirofish_service import get_mirofish_service

    service = get_mirofish_service()
    result = service.restart()
    logger.info(f"MiroFish service restart: {result['message']}")

    return ServiceActionResponse(
        success=True,
        message=result["message"],
        state=result["state"],
        data=result,
    )


class RiskProfileResponse(BaseModel):
    name: str
    display_name: str
    kelly_fraction: float
    min_edge_threshold: float
    max_trade_size: float
    max_position_fraction: float
    max_total_exposure_fraction: float
    daily_loss_limit: float
    daily_drawdown_limit_pct: float
    weekly_drawdown_limit_pct: float
    slippage_tolerance: float
    auto_approve_min_confidence: float
    is_preset: bool = False


class RiskProfileListResponse(BaseModel):
    active: str
    profiles: Dict[str, RiskProfileResponse]


class SetRiskProfileRequest(BaseModel):
    profile: str


class UpdateRiskProfileRequest(BaseModel):
    display_name: Optional[str] = None
    kelly_fraction: Optional[float] = None
    min_edge_threshold: Optional[float] = None
    max_trade_size: Optional[float] = None
    max_position_fraction: Optional[float] = None
    max_total_exposure_fraction: Optional[float] = None
    daily_loss_limit: Optional[float] = None
    daily_drawdown_limit_pct: Optional[float] = None
    weekly_drawdown_limit_pct: Optional[float] = None
    slippage_tolerance: Optional[float] = None
    auto_approve_min_confidence: Optional[float] = None


class CreateRiskProfileRequest(BaseModel):
    name: str
    display_name: str
    kelly_fraction: float = 0.3
    min_edge_threshold: float = 0.3
    max_trade_size: float = 8.0
    max_position_fraction: float = 0.08
    max_total_exposure_fraction: float = 0.7
    daily_loss_limit: float = 5.0
    daily_drawdown_limit_pct: float = 0.1
    weekly_drawdown_limit_pct: float = 0.2
    slippage_tolerance: float = 0.02
    auto_approve_min_confidence: float = 0.5


def _profile_to_response(p) -> RiskProfileResponse:
    return RiskProfileResponse(
        name=p.name,
        display_name=p.display_name,
        kelly_fraction=p.kelly_fraction,
        min_edge_threshold=p.min_edge_threshold,
        max_trade_size=p.max_trade_size,
        max_position_fraction=p.max_position_fraction,
        max_total_exposure_fraction=p.max_total_exposure_fraction,
        daily_loss_limit=p.daily_loss_limit,
        daily_drawdown_limit_pct=p.daily_drawdown_limit_pct,
        weekly_drawdown_limit_pct=p.weekly_drawdown_limit_pct,
        slippage_tolerance=p.slippage_tolerance,
        auto_approve_min_confidence=p.auto_approve_min_confidence,
        is_preset=getattr(p, "is_preset", False),
    )


@router.get("/risk/profile", response_model=RiskProfileListResponse)
async def get_risk_profiles(_: None = Depends(require_admin)):
    from backend.core.risk_profiles import list_profiles, get_active_profile_name

    active = get_active_profile_name()
    profiles = {k: _profile_to_response(p) for k, p in list_profiles().items()}
    return RiskProfileListResponse(active=active, profiles=profiles)


@router.put("/risk/profile")
async def set_risk_profile(
    body: SetRiskProfileRequest,
    _: None = Depends(require_admin),
):
    from backend.core.risk_profiles import list_profiles, apply_profile

    all_profiles = list_profiles()
    if body.profile not in all_profiles:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown profile: {body.profile}. Available: {list(all_profiles.keys())}",
        )
    profile = apply_profile(body.profile)
    logger.info("Risk profile changed to '%s'", profile.display_name)
    return {
        "status": "ok",
        "active_profile": profile.name,
        "display_name": profile.display_name,
    }


@router.put("/risk/profile/{name}")
async def update_risk_profile(
    name: str,
    body: UpdateRiskProfileRequest,
    _: None = Depends(require_admin),
):
    from backend.core.risk_profiles import update_profile

    try:
        updates = {k: v for k, v in body.model_dump().items() if v is not None}
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")
        profile = update_profile(name, updates)
        return {"status": "ok", "profile": _profile_to_response(profile).model_dump()}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/risk/profile")
async def create_risk_profile(
    body: CreateRiskProfileRequest,
    _: None = Depends(require_admin),
):
    from backend.core.risk_profiles import create_profile, RiskProfile

    try:
        profile = RiskProfile(
            name=body.name,
            display_name=body.display_name,
            kelly_fraction=body.kelly_fraction,
            min_edge_threshold=body.min_edge_threshold,
            max_trade_size=body.max_trade_size,
            max_position_fraction=body.max_position_fraction,
            max_total_exposure_fraction=body.max_total_exposure_fraction,
            daily_loss_limit=body.daily_loss_limit,
            daily_drawdown_limit_pct=body.daily_drawdown_limit_pct,
            weekly_drawdown_limit_pct=body.weekly_drawdown_limit_pct,
            slippage_tolerance=body.slippage_tolerance,
            auto_approve_min_confidence=body.auto_approve_min_confidence,
        )
        created = create_profile(profile)
        return {"status": "ok", "profile": _profile_to_response(created).model_dump()}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.delete("/risk/profile/{name}")
async def delete_risk_profile(
    name: str,
    _: None = Depends(require_admin),
):
    from backend.core.risk_profiles import delete_profile

    deleted = delete_profile(name)
    if not deleted:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete preset profile or profile not found: {name}",
        )
    return {"status": "ok", "deleted": name}


@router.get("/mirofish/signals")
async def get_mirofish_signals(
    market: str = "polymarket",
    question: str = "",
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Get AI-powered trading signals — routes to external MiroFish or built-in debate engine.

    Behaviour controlled by MIROFISH_ENABLED and MIROFISH_API_URL in settings:
    - If MIROFISH_ENABLED=true and MIROFISH_API_URL points external → calls external MiroFish API
    - Otherwise → uses built-in Bull/Bear/Judge debate engine (Groq/Claude LLMs)
    """
    import json as _json
    from backend.config import settings as app

    if app.MIROFISH_ENABLED and app.MIROFISH_API_URL:
        try:
            from backend.ai.mirofish_client import MiroFishClient

            client = MiroFishClient()
            raw_signals = await client.fetch_signals(market=market, question=question)
            if raw_signals:
                signals = [
                    {
                        "market_id": s.market_id,
                        "market_question": getattr(s, "market_question", ""),
                        "prediction": s.prediction,
                        "confidence": s.confidence,
                        "reasoning": s.reasoning,
                        "source": s.source,
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "signal_id": f"mirofish_{hash(s.market_id) % 100000:05d}",
                    }
                    for s in raw_signals
                ]
                return {
                    "signals": signals,
                    "count": len(signals),
                    "source": "external_mirofish",
                }
        except Exception as e:
            logger.warning(
                f"External MiroFish failed, falling back to debate engine: {e}"
            )

    from backend.ai.debate_engine import run_debate
    from backend.data.gamma import fetch_markets

    try:
        markets = await fetch_markets(limit=5)
        signals = []
        for m in markets[:1]:
            question = m.get("question", "Unknown market")
            prices_str = m.get("outcomePrices", "[]")
            try:
                prices = (
                    _json.loads(prices_str)
                    if isinstance(prices_str, str)
                    else prices_str
                )
                yes_price = float(prices[0]) if prices else 0.5
            except (_json.JSONDecodeError, IndexError, ValueError, TypeError):
                yes_price = 0.5
            volume = float(m.get("volume", 0) or m.get("liquidity", 0) or 0)

            result = await run_debate(
                question=question,
                market_price=yes_price,
                volume=volume,
                category=m.get("category", ""),
                max_rounds=1,
            )
            if result:
                bull_reasoning = (
                    result.bull_arguments[0].reasoning if result.bull_arguments else ""
                )
                bear_reasoning = (
                    result.bear_arguments[0].reasoning if result.bear_arguments else ""
                )
                signals.append(
                    {
                        "market_id": str(m.get("id", "")),
                        "market_question": question,
                        "market_type": m.get("category", "crypto"),
                        "prediction": result.consensus_probability,
                        "confidence": result.confidence,
                        "edge": abs(result.consensus_probability - yes_price),
                        "fair_value": result.consensus_probability,
                        "current_price": yes_price,
                        "reasoning": result.reasoning,
                        "bull_args": bull_reasoning,
                        "bear_args": bear_reasoning,
                        "sources": result.data_sources or ["debate_engine"],
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "signal_id": f"debate_{hash(question) % 100000:05d}",
                        "latency_ms": result.latency_ms,
                        "rounds": result.rounds_completed,
                    }
                )
            else:
                signals.append(
                    {
                        "market_id": str(m.get("id", "")),
                        "market_question": question,
                        "market_type": m.get("category", "crypto"),
                        "prediction": yes_price,
                        "confidence": 0.3,
                        "edge": 0.0,
                        "fair_value": yes_price,
                        "current_price": yes_price,
                        "reasoning": "Debate engine returned no result",
                        "sources": ["debate_engine"],
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "signal_id": f"nodata_{hash(question) % 100000:05d}",
                    }
                )

        return {"signals": signals, "count": len(signals), "source": "debate_engine"}
    except Exception as e:
        logger.error(f"MiroFish signals failed: {e}")
        return {"signals": [], "count": 0, "source": "error", "error": str(e)}
