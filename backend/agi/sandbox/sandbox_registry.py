"""Sandbox registry — rejects nodes that require DB or live data access."""

import logging

from backend.core.plugin_registry import PluginRegistry
from backend.agi.base_node import NodeManifest, BaseAGINode

logger = logging.getLogger(__name__)


def _reject_unsafe(plugin_class: type) -> None:
    manifest = plugin_class.manifest()
    if manifest.requires_db:
        raise ValueError(
            f"Node '{manifest.name}' requires database access - not allowed in sandbox"
        )
    if manifest.requires_live_data:
        raise ValueError(
            f"Node '{manifest.name}' requires live data - not allowed in sandbox"
        )


sandbox_registry: PluginRegistry[NodeManifest, BaseAGINode] = PluginRegistry(
    name="sandbox_node_registry", pre_register=_reject_unsafe, env_var_check=False
)
