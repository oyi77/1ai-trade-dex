"""Data source plugin package.

Auto-discovers and registers all data source plugins on import.
"""
from backend.data.source_registry import source_registry

source_registry.auto_discover("backend.data.sources")