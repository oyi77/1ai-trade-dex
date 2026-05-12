"""AI Provider plugin package.

Auto-discovers and registers all AI provider plugins on import.
"""
from backend.ai.provider_registry import provider_registry

# Trigger auto-discovery of all provider plugins in this package
provider_registry.auto_discover("backend.ai.providers")
