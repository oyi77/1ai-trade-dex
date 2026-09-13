"""Carved verbatim out of ``backend/api/settings.py`` — statements moved, no logic changed."""

from .settings import (
    Any,
    BaseModel,
    Depends,
    Session,
    get_db,
    require_admin,
    router,
)

from . import settings as _facade

class SettingsResponse(BaseModel):
    mirofish_enabled: bool
    mirofish_api_url: _facade.Optional[str]
    mirofish_api_key: _facade.Optional[str]
    strategies: _facade.Dict[str, bool]
    risk_params: _facade.Dict[str, _facade.Any]
    trading_mode: str
class SettingsUpdateRequest(BaseModel):
    mirofish_enabled: _facade.Optional[bool] = None
    mirofish_api_url: _facade.Optional[str] = None
    mirofish_api_key: _facade.Optional[str] = None
    strategies: _facade.Optional[_facade.Dict[str, bool]] = None
    risk_params: _facade.Optional[_facade.Dict[str, _facade.Any]] = None
    trading_mode: _facade.Optional[str] = None
class ToggleResponse(BaseModel):
    enabled: bool
    message: str
class TestMiroFishRequest(BaseModel):
    api_url: str
    api_key: str
class TestMiroFishResponse(BaseModel):
    success: bool
    message: str
    signals_count: _facade.Optional[int] = None
    error: _facade.Optional[str] = None
def _get_setting(db: Session, key: str, default: Any = None) -> Any:
    setting = db.query(_facade.SystemSettings).filter(_facade.SystemSettings.key == key).first()
    if setting:
        return setting.value
    return default
def _set_setting(db: Session, key: str, value: Any):
    setting = db.query(_facade.SystemSettings).filter(_facade.SystemSettings.key == key).first()
    if setting:
        setting.value = value
        setting.updated_at = _facade.utcnow()
    else:
        setting = _facade.SystemSettings(key=key, value=value)
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
                "max_position_size": _facade.app_settings.MAX_TRADE_SIZE,
                "max_daily_loss": _facade.app_settings.DAILY_LOSS_LIMIT,
                "max_total_pending": _facade.app_settings.MAX_TOTAL_PENDING_TRADES,
            },
        )
        trading_mode = _get_setting(db, "trading_mode", _facade.app_settings.TRADING_MODE)

        return SettingsResponse(
            mirofish_enabled=mirofish_enabled,
            mirofish_api_url=mirofish_api_url,
            mirofish_api_key=mirofish_api_key,
            strategies=strategies,
            risk_params=risk_params,
            trading_mode=trading_mode,
        )
    except Exception as e:
        _facade.logger.error(f"Failed to get settings: {e}", exc_info=True)
        raise _facade.HTTPException(status_code=500, detail="Failed to retrieve settings")
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
                raise _facade.HTTPException(status_code=400, detail="Invalid trading mode")
            old_value = _get_setting(db, "trading_mode", _facade.app_settings.TRADING_MODE)
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
        _facade.logger.info("Settings updated successfully")

        return {"status": "ok", "message": "Settings updated successfully"}

    except _facade.HTTPException:
        raise
    except Exception as e:
        db.rollback()
        _facade.logger.error(f"Failed to update settings: {e}", exc_info=True)
        raise _facade.HTTPException(status_code=500, detail="Failed to update settings")
class SettingItemResponse(BaseModel):
    id: int
    key: str
    value: _facade.Any
    description: _facade.Optional[str] = None
    type: str = "string"
    created_at: _facade.Optional[str] = None
    updated_at: _facade.Optional[str] = None
    updated_by_user_id: str = "admin"
class BulkSettingUpdateRequest(BaseModel):
    updates: list  # Array of {key: string, value: string}
@router.get("/list", response_model=list[SettingItemResponse])
async def list_all_settings(
    db: Session = Depends(get_db), _: None = Depends(require_admin)
):
    """Return all SystemSettings rows as an array for the SettingsEditor UI."""
    rows = db.query(_facade.SystemSettings).order_by(_facade.SystemSettings.key).all()
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
        "PAPER_MAX_DEPTH_CONSUMPTION_PCT",
        "PAPER_LONGSHOT_SLIPPAGE_MULTIPLIER",
        "PAPER_LONGSHOT_PRICE_THRESHOLD",
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
        row = db.query(_facade.SystemSettings).filter(_facade.SystemSettings.key == key).first()
        if row:
            # Try to preserve type
            if isinstance(row.value, bool):
                value = value in ("true", "True", "1", True)
            elif isinstance(row.value, int):
                try:
                    value = int(value)
                except (ValueError, TypeError):
                    _facade.logger.warning(
                        "Setting %s: could not convert '%s' to int, keeping as string",
                        key,
                        value,
                    )
            elif isinstance(row.value, float):
                try:
                    value = float(value)
                except (ValueError, TypeError):
                    _facade.logger.warning(
                        "Setting %s: could not convert '%s' to float, keeping as string",
                        key,
                        value,
                    )
            row.value = value
            row.updated_at = _facade.utcnow()
        else:
            db.add(_facade.SystemSettings(key=key, value=value))
        updated += 1

        # Propagate to app_settings for runtime effect
        if key in RUNTIME_MUTABLE_KEYS and hasattr(_facade.app_settings, key):
            try:
                current_val = getattr(_facade.app_settings, key)
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
                object.__setattr__(_facade.app_settings, key, coerced)
                mutated_app_settings.append((key, coerced))
            except (ValueError, TypeError) as e:
                _facade.logger.warning(f"Failed to setattr app_settings.{key}={value}: {e}")

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
        _facade.logger.info(f"Runtime settings updated: {mutated_app_settings}")

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

        object.__setattr__(_facade.app_settings, "MIROFISH_ENABLED", new_state)

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

        _facade.logger.info(f"MiroFish toggled: {current} -> {new_state}")

        return ToggleResponse(
            enabled=new_state,
            message=f"MiroFish {'enabled' if new_state else 'disabled'}",
        )
    except Exception as e:
        db.rollback()
        _facade.logger.error(f"Failed to toggle MiroFish: {e}", exc_info=True)
        raise _facade.HTTPException(status_code=500, detail="Failed to toggle MiroFish")
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

        _facade.logger.info(f"Strategy '{name}' toggled: {current} -> {new_state}")

        return ToggleResponse(
            enabled=new_state,
            message=f"Strategy '{name}' {'enabled' if new_state else 'disabled'}",
        )
    except Exception as e:
        db.rollback()
        _facade.logger.error(f"Failed to toggle strategy '{name}': {e}", exc_info=True)
        raise _facade.HTTPException(
            status_code=500, detail=f"Failed to toggle strategy '{name}'"
        )
