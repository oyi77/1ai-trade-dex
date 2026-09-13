"""Carved verbatim out of ``backend/api/settings.py`` — statements moved, no logic changed."""

from ._settings_settingsresponse import (
    TestMiroFishRequest,
    TestMiroFishResponse,
)

from .settings import (
    BaseModel,
    Depends,
    Optional,
    Session,
    get_db,
    require_admin,
    router,
)

from . import settings as _facade

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

        _facade.logger.info(f"Testing MiroFish connection: {request.api_url}")

        client = MiroFishClient(api_url=request.api_url, api_key=request.api_key)

        # Test fetch_signals with timeout
        try:
            signals = await _facade.asyncio.wait_for(
                client.fetch_signals(market="polymarket"), timeout=10.0
            )

            _facade.logger.info(f"MiroFish test successful: {len(signals)} signals fetched")

            return _facade.TestMiroFishResponse(
                success=True,
                message=f"Connection successful. Fetched {len(signals)} signals.",
                signals_count=len(signals),
            )

        except _facade.asyncio.TimeoutError:
            _facade.logger.warning("MiroFish test timed out after 10 seconds")
            return _facade.TestMiroFishResponse(
                success=False,
                message="Connection test timed out after 10 seconds",
                error="timeout",
            )
        except Exception as e:
            error_msg = str(e)
            _facade.logger.error(f"MiroFish test failed: {error_msg}", exc_info=True)

            # Determine error type without exposing sensitive details
            if "401" in error_msg or "unauthorized" in error_msg.lower():
                return _facade.TestMiroFishResponse(
                    success=False,
                    message="Authentication failed. Check your API key.",
                    error="authentication",
                )
            elif "404" in error_msg or "not found" in error_msg.lower():
                return _facade.TestMiroFishResponse(
                    success=False,
                    message="API endpoint not found. Check your API URL.",
                    error="not_found",
                )
            elif "connection" in error_msg.lower():
                return _facade.TestMiroFishResponse(
                    success=False,
                    message="Connection failed. Check your API URL and network.",
                    error="connection",
                )
            else:
                return _facade.TestMiroFishResponse(
                    success=False,
                    message="Connection test failed. Please check your credentials.",
                    error=error_msg,
                )
    except Exception as e:
        _facade.logger.error(f"Unexpected error during MiroFish test: {e}", exc_info=True)
        raise _facade.HTTPException(
            status_code=500, detail="Failed to test MiroFish connection"
        )
class ServiceActionResponse(BaseModel):
    success: bool
    message: str
    state: str
    data: _facade.Optional[_facade.Dict[str, _facade.Any]] = None
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
    _facade.logger.info(f"MiroFish service start: {result['message']}")

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
    _facade.logger.info(f"MiroFish service stop: {result['message']}")

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
        _facade.logger.exception(f"Failed to find process on port {port}")
    return None
def _kill_process(pid: int):
    """Kill a process by PID."""
    import subprocess

    try:
        subprocess.run(["kill", str(pid)], timeout=5)
    except Exception:
        _facade.logger.exception(f"Failed to kill process {pid}")
def _start_mirofish_backend():
    import subprocess
    import os

    venv_python = os.path.join(_facade.MIROFISH_BACKEND_DIR, "venv", "bin", "python")
    env = {**os.environ}
    # E-96: Pipe stderr to PIPE so startup errors are not silently swallowed
    return subprocess.Popen(
        [venv_python, "run.py"],
        cwd=_facade.MIROFISH_BACKEND_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
def _start_mirofish_frontend():
    import subprocess

    # E-96: Pipe stderr to PIPE so startup errors are not silently swallowed
    return subprocess.Popen(
        ["npx", "vite", "preview", "--port", str(_facade.MIROFISH_FRONTEND_PORT), "--host"],
        cwd=_facade.MIROFISH_FRONTEND_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        shell=False,
    )
class ProcessStatus(BaseModel):
    backend_running: bool
    backend_pid: _facade.Optional[int]
    frontend_running: bool
    frontend_pid: _facade.Optional[int]
@router.get("/mirofish/processes")
async def get_mirofish_processes(_: None = Depends(require_admin)):
    """Check if MiroFish backend and frontend processes are running."""
    backend_pid = _find_process_by_port(_facade.MIROFISH_BACKEND_PORT)
    frontend_pid = _find_process_by_port(_facade.MIROFISH_FRONTEND_PORT)
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

    backend_pid = _find_process_by_port(_facade.MIROFISH_BACKEND_PORT)
    if backend_pid is None:
        try:
            _start_mirofish_backend()
            results["backend"] = "started"
        except Exception as e:
            results["backend"] = f"failed: {e}"
    else:
        results["backend"] = f"already running (pid={backend_pid})"

    frontend_pid = _find_process_by_port(_facade.MIROFISH_FRONTEND_PORT)
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

    backend_pid = _find_process_by_port(_facade.MIROFISH_BACKEND_PORT)
    if backend_pid:
        _kill_process(backend_pid)
        results["backend"] = f"stopped (was pid={backend_pid})"
    else:
        results["backend"] = "not running"

    frontend_pid = _find_process_by_port(_facade.MIROFISH_FRONTEND_PORT)
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
    backend_pid = _find_process_by_port(_facade.MIROFISH_BACKEND_PORT)
    if backend_pid:
        _kill_process(backend_pid)
    frontend_pid = _find_process_by_port(_facade.MIROFISH_FRONTEND_PORT)
    if frontend_pid:
        _kill_process(frontend_pid)

    await _facade.asyncio.sleep(1)

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
    _facade.logger.info(f"MiroFish service restart: {result['message']}")

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
    max_concentration_pct: float
    max_correlated_exposure_pct: float
    longshot_no_bias_weight: float
    is_preset: bool = False
class RiskProfileListResponse(BaseModel):
    active: str
    profiles: _facade.Dict[str, RiskProfileResponse]
class SetRiskProfileRequest(BaseModel):
    profile: str
class UpdateRiskProfileRequest(BaseModel):
    display_name: _facade.Optional[str] = None
    kelly_fraction: _facade.Optional[float] = None
    min_edge_threshold: _facade.Optional[float] = None
    max_trade_size: _facade.Optional[float] = None
    max_position_fraction: _facade.Optional[float] = None
    max_total_exposure_fraction: _facade.Optional[float] = None
    daily_loss_limit: _facade.Optional[float] = None
    daily_drawdown_limit_pct: _facade.Optional[float] = None
    weekly_drawdown_limit_pct: _facade.Optional[float] = None
    slippage_tolerance: _facade.Optional[float] = None
    auto_approve_min_confidence: _facade.Optional[float] = None
    max_concentration_pct: _facade.Optional[float] = None
    max_correlated_exposure_pct: _facade.Optional[float] = None
    longshot_no_bias_weight: _facade.Optional[float] = None
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
    max_concentration_pct: float = 0.3
    max_correlated_exposure_pct: float = 0.8
    longshot_no_bias_weight: float = 0.1
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
        max_concentration_pct=getattr(p, "max_concentration_pct", 0.3),
        max_correlated_exposure_pct=getattr(p, "max_correlated_exposure_pct", 0.8),
        longshot_no_bias_weight=p.longshot_no_bias_weight,
        is_preset=getattr(p, "is_preset", False),
    )
@router.get("/risk/profile", response_model=RiskProfileListResponse)
async def get_risk_profiles(_: None = Depends(require_admin)):
    from backend.core.risk.risk_profiles import list_profiles, get_active_profile_name

    active = get_active_profile_name()
    profiles = {k: _profile_to_response(p) for k, p in list_profiles().items()}
    return RiskProfileListResponse(active=active, profiles=profiles)
@router.put("/risk/profile")
async def set_risk_profile(
    body: SetRiskProfileRequest,
    _: None = Depends(require_admin),
):
    from backend.core.risk.risk_profiles import list_profiles, apply_profile

    all_profiles = list_profiles()
    if body.profile not in all_profiles:
        raise _facade.HTTPException(
            status_code=400,
            detail=f"Unknown profile: {body.profile}. Available: {list(all_profiles.keys())}",
        )
    profile = apply_profile(body.profile)
    _facade.logger.info("Risk profile changed to '%s'", profile.display_name)
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
    from backend.core.risk.risk_profiles import update_profile

    try:
        updates = {k: v for k, v in body.model_dump().items() if v is not None}
        if not updates:
            raise _facade.HTTPException(status_code=400, detail="No fields to update")
        profile = update_profile(name, updates)
        return {"status": "ok", "profile": _profile_to_response(profile).model_dump()}
    except ValueError as e:
        raise _facade.HTTPException(status_code=404, detail=str(e))
