"""Provider registry — auto-discovers all providers on import."""

from backend.strategies.unified_arb.providers.polymarket_provider import PolymarketProvider
from backend.strategies.unified_arb.providers.kalshi_provider import KalshiProvider
from backend.strategies.unified_arb.providers.hyperliquid_provider import HyperliquidProvider
from backend.strategies.unified_arb.providers.aster_provider import AsterProvider
from backend.strategies.unified_arb.providers.lighter_provider import LighterProvider
from backend.strategies.unified_arb.providers.ostium_provider import OstiumProvider

PM_PROVIDERS = [PolymarketProvider, KalshiProvider]
DEX_PROVIDERS = [HyperliquidProvider, AsterProvider, LighterProvider, OstiumProvider]
ALL_PROVIDERS = PM_PROVIDERS + DEX_PROVIDERS

__all__ = [
    "PolymarketProvider",
    "KalshiProvider",
    "HyperliquidProvider",
    "AsterProvider",
    "LighterProvider",
    "OstiumProvider",
    "PM_PROVIDERS",
    "DEX_PROVIDERS",
    "ALL_PROVIDERS",
]
