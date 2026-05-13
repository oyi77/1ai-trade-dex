"""AGI nodes package - auto-discovery setup."""
from backend.agi.node_registry import node_registry

node_registry.auto_discover("backend.agi.nodes")
