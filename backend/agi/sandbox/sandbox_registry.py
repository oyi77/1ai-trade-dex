"""Sandbox registry - mock-only registry for sandboxed validation."""
import asyncio
import logging
from typing import List, Optional

from backend.core.plugin_registry import PluginRegistry
from backend.agi.base_node import NodeManifest, BaseAGINode
from backend.agi.sandbox.results import SandboxResult

logger = logging.getLogger(__name__)


class SandboxNodeRegistry(PluginRegistry[NodeManifest, BaseAGINode]):
    """Registry that only allows sandbox-safe nodes (no DB, no live data)."""

    _instance: Optional["SandboxNodeRegistry"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.__initialized = False
        return cls._instance

    def __init__(self):
        if self.__initialized:
            return
        super().__init__(name="sandbox_node_registry")
        self.__initialized = True

    @classmethod
    def reset(cls) -> None:
        if cls._instance is not None:
            super(SandboxNodeRegistry, cls._instance).reset()
            cls._instance.__initialized = False
            cls._instance = None

    def register(self, node_class: type) -> None:
        """Register a sandbox-safe node class.

        Rejects nodes that require DB access or live data.
        """
        manifest = node_class.manifest()
        name = manifest.name

        if manifest.requires_db:
            logger.warning(f"Sandbox rejected node '{name}': requires_db=True")
            raise ValueError(f"Node '{name}' requires database access - not allowed in sandbox")
        if manifest.requires_live_data:
            logger.warning(f"Sandbox rejected node '{name}': requires_live_data=True")
            raise ValueError(f"Node '{name}' requires live data - not allowed in sandbox")

        try:
            instance = node_class()
            self._plugins[name] = instance
            self._manifests[name] = manifest
            self._enabled[name] = True
            self._health_status[name] = True
            logger.info(f"Registered sandbox node: {name}")
        except Exception as e:
            logger.warning(f"Failed to instantiate sandbox node {name}: {e}")

    def get(self, name: str) -> BaseAGINode:
        """Get a sandbox node by name."""
        if name not in self._plugins:
            raise KeyError(f"Sandbox node '{name}' not found")
        if not self._enabled.get(name, False):
            raise KeyError(f"Sandbox node '{name}' is disabled")
        return self._plugins[name]

    def list_all(self) -> List[NodeManifest]:
        """Return all sandbox node manifests."""
        return [self._manifests[n] for n in self._plugins if self._enabled.get(n, False)]

    async def run_health_checks(self) -> dict:
        """All sandbox nodes are always healthy (no external deps)."""
        return {name: True for name in self._plugins if self._enabled.get(name, False)}


# Module-level singleton
sandbox_registry = SandboxNodeRegistry()