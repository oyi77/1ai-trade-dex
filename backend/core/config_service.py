"""Dynamic configuration service with DB > .env > default fallback."""

import os
import threading
from typing import Any, Optional
from sqlalchemy.orm import Session
import logging

logger = logging.getLogger("trading_bot")

# Thread-safe in-memory cache
_settings_cache: dict[str, Any] = {}
_cache_lock = threading.Lock()


def get_setting(key: str, default: Any = None, db: Optional[Session] = None) -> Any:
    """
    Get a setting value with priority: DB > .env > default.

    Args:
        key: Setting key (e.g., "MIROFISH_API_TIMEOUT")
        default: Default value if not found in DB or .env
        db: Optional database session (if None, uses cache only)

    Returns:
        Setting value with type coercion based on default type
    """
    # Check cache first
    with _cache_lock:
        if key in _settings_cache:
            return _settings_cache[key]

    # If DB session provided, query database
    if db:
        try:
            from backend.models.database import Setting
            setting = db.query(Setting).filter(Setting.key == key).first()
            if setting:
                value = _coerce_type(setting.value, setting.type, default)
                # Update cache
                with _cache_lock:
                    _settings_cache[key] = value
                return value
        except Exception as e:
            logger.warning(f"Failed to query setting '{key}' from DB: {e}")

    # Fall back to .env
    env_value = os.getenv(key)
    if env_value is not None:
        value = _coerce_type(env_value, _infer_type(default), default)
        # Cache .env value
        with _cache_lock:
            _settings_cache[key] = value
        return value

    # Use default
    return default


def reload_settings_from_db(db: Session) -> int:
    """
    Reload all settings from database into cache.

    Args:
        db: Database session

    Returns:
        Number of settings loaded into cache
    """
    try:
        from backend.models.database import Setting
        settings = db.query(Setting).all()

        with _cache_lock:
            _settings_cache.clear()
            for setting in settings:
                _settings_cache[setting.key] = _coerce_type(
                    setting.value,
                    setting.type,
                    None
                )

        logger.info(f"Reloaded {len(settings)} settings from database into cache")
        return len(settings)
    except Exception as e:
        logger.error(f"Failed to reload settings from DB: {e}", exc_info=True)
        return 0


def _infer_type(default: Any) -> str:
    """Infer type string from default value."""
    if isinstance(default, bool):
        return "bool"
    elif isinstance(default, int):
        return "int"
    elif isinstance(default, float):
        return "float"
    else:
        return "string"


def _coerce_type(value: str, type_hint: str, default: Any) -> Any:
    """
    Coerce string value to appropriate type.

    Args:
        value: String value from DB or .env
        type_hint: Type hint ("string", "int", "bool", "float")
        default: Default value for type inference fallback

    Returns:
        Coerced value
    """
    try:
        if type_hint == "bool":
            return str(value).lower() in ("true", "1", "yes", "on")
        elif type_hint == "int":
            return int(value)
        elif type_hint == "float":
            return float(value)
        else:
            return str(value)
    except (ValueError, TypeError):
        logger.warning(
            f"Failed to coerce value '{value}' to type '{type_hint}', using default"
        )
        return default
