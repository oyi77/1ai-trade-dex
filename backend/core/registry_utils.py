"""Shared registry utility functions."""

import logging
import os
from typing import List

logger = logging.getLogger(__name__)


def check_env_vars(manifest, log: logging.Logger = None) -> List[str]:
    """Return list of required env vars that are missing (unset or empty).

    Args:
        manifest: any manifest object with a required_env_vars: List[str] attribute
        log: optional logger for debug output (defaults to module logger)

    Returns:
        list of missing env var names
    """
    _log = log or logger
    missing = [v for v in manifest.required_env_vars if not os.environ.get(v)]
    if missing:
        _log.debug(f"Missing env vars: {missing}")
    return missing
