"""Configuration validation and startup checks."""

from loguru import logger

from backend.config import settings


def validate_startup() -> None:
    """Run startup validation — fail fast if config is invalid."""
    issues = settings.validate()
    if issues:
        print("Configuration validation errors:")
        for issue in issues:
            print(f"  - {issue}")
        raise ValueError(f"Configuration validation failed: {issues[:3]}")
    print("PolyEdge Configuration Loaded Successfully")


def log_missing_optional_keys() -> None:
    """Log warnings for optional API keys that are not set."""
    for key in ["ANTHROPIC_API_KEY", "EXA_API_KEY", "SERPER_API_KEY"]:
        if not getattr(settings, key, None):
            logger.debug(f"[Config] {key} not set — fallback provider disabled")