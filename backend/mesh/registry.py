"""SourceRegistry — runtime discovery and management of DataSource plugins."""
from __future__ import annotations
from typing import Dict, Optional
from backend.mesh.base import DataSource

from loguru import logger

_registry: Dict[str, DataSource] = {}
_quarantined: Dict[str, str] = {}


def register(source: DataSource) -> None:
    if source.source_id in _registry:
        logger.warning(f"Source '{source.source_id}' already registered — replacing")
    _registry[source.source_id] = source
    logger.info(f"DataSource registered: {source.source_id} (v{source.schema_version})")


def unregister(source_id: str) -> None:
    _registry.pop(source_id, None)
    _quarantined.pop(source_id, None)


def get(source_id: str) -> Optional[DataSource]:
    return _registry.get(source_id)


def list_active() -> Dict[str, DataSource]:
    return {k: v for k, v in _registry.items() if k not in _quarantined}


def quarantine(source_id: str, reason: str = "") -> None:
    _quarantined[source_id] = reason
    logger.warning(f"Source '{source_id}' quarantined: {reason}")


def release(source_id: str) -> None:
    if source_id in _quarantined:
        del _quarantined[source_id]
        logger.info(f"Source '{source_id}' released from quarantine")


def is_quarantined(source_id: str) -> bool:
    return source_id in _quarantined


def discover() -> int:
    import importlib
    import pkgutil
    import os
    sources_dir = os.path.join(os.path.dirname(__file__), "..", "sources")
    count = 0
    if os.path.isdir(sources_dir):
        for finder, name, ispkg in pkgutil.iter_modules([sources_dir]):
            if not name.startswith("_"):
                try:
                    importlib.import_module(f"backend.sources.{name}")
                    count += 1
                except Exception as e:
                    logger.warning(f"Failed to load source '{name}': {e}")
    return count
