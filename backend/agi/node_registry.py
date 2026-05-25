"""Node registry for the AGI plugin system — uses configurable PluginRegistry instance."""

import logging
from backend.core.plugin_registry import PluginRegistry
from backend.agi.base_node import NodeManifest, BaseAGINode

logger = logging.getLogger(__name__)

# Plain PluginRegistry instance — no subclass needed.
# env_var_check=False allows nodes without env vars (dev/tests).
node_registry = PluginRegistry[NodeManifest, BaseAGINode](
    name="node_registry", env_var_check=False, health_interval=30.0
)
