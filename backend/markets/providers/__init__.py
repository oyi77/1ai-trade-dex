"""Market provider plugin package.

Auto-discovers and registers all market provider plugins on import.
"""
from backend.markets.provider_registry import market_registry

market_registry.auto_discover("backend.markets.providers")
