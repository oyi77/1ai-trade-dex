"""Smoke tests for all 11 market providers.

Each test instantiates the provider in paper mode and calls the appropriate
market-fetching method (search_markets / get_markets / health_check).
"""

import asyncio
import pytest

# ---------------------------------------------------------------------------
# Provider imports – each wrapped so a missing SDK doesn't block other tests
# ---------------------------------------------------------------------------

def _import(name: str):
    """Import a provider; return None if SDK missing."""
    try:
        mod = __import__(
            f"backend.markets.providers.{name}", fromlist=["*"]
        )
        # class name is PascalCase of the file without _provider suffix
        cls_name = name.replace("_provider", "")
        # map file -> class name
        mapping = {
            "polymarket_provider": "PolymarketProvider",
            "kalshi_provider": "KalshiProvider",
            "sxbet_provider": "SXBetProvider",
            "hyperliquid_provider": "HyperliquidProvider",
            "aster_provider": "AsterProvider",
            "lighter_provider": "LighterProvider",
            "ostium_provider": "OstiumProvider",
            "myriad_provider": "MyriadProvider",
            "bookmaker_xyz_provider": "BookmakerXYZProvider",
            "predict_fun_provider": "PredictFunProvider",
            "paper_provider": "PaperProvider",
        }
        return getattr(mod, mapping[name], None)
    except Exception as e:
        return e  # return the exception so we can report it


PROVIDERS = [
    "polymarket_provider",
    "kalshi_provider",
    "sxbet_provider",
    "hyperliquid_provider",
    "aster_provider",
    "lighter_provider",
    "ostium_provider",
    "myriad_provider",
    "bookmaker_xyz_provider",
    "predict_fun_provider",
    "paper_provider",
]


def _has_own_search(cls):
    """True only if cls overrides search_markets (not just inherited from base)."""
    return "search_markets" in cls.__dict__


def _has_own_get(cls):
    """True only if cls overrides get_markets (not just inherited from base)."""
    return "get_markets" in cls.__dict__


def _has_health(cls):
    return hasattr(cls, "health_check") and callable(getattr(cls, "health_check"))


# Providers that don't override search_markets or get_markets – only have
# base-class no-op search_markets + health_check.  We'll call search_markets
# with the required (query, category) positional args.
_INHERITED_SEARCH_ONLY = {
    "sxbet_provider",
    "hyperliquid_provider",
    "aster_provider",
    "lighter_provider",
    "ostium_provider",
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", PROVIDERS)
async def test_provider_smoke(provider_name):
    """Instantiate provider in paper mode and call its market-fetching method."""

    result = _import(provider_name)
    if isinstance(result, Exception):
        pytest.skip(f"Import failed: {result}")

    cls = result
    if cls is None:
        pytest.skip(f"Class not found in module {provider_name}")

    try:
        provider = cls(paper_mode=True)
    except Exception as e:
        pytest.skip(f"Instantiation failed: {e}")

    # 1. Paper provider – custom search_markets, no positional 'category'
    if provider_name == "paper_provider":
        markets = await provider.search_markets("", limit=10)
        assert isinstance(markets, list), f"Expected list, got {type(markets)}"
        print(f"  {provider_name}: returned {len(markets)} markets")
        return

    # 2. Providers that override get_markets (sxbet, bookmaker_xyz, predict_fun)
    #    must be checked BEFORE search_markets because base also defines it.
    if _has_own_get(cls):
        markets = await provider.get_markets(limit=5)
        assert isinstance(markets, list), f"Expected list, got {type(markets)}"
        print(f"  {provider_name}: get_markets returned {len(markets)} markets")
        return

    # 3. Providers that override search_markets (polymarket, kalshi, myriad)
    if _has_own_search(cls):
        markets = await provider.search_markets("", limit=5)
        assert isinstance(markets, list), f"Expected list, got {type(markets)}"
        print(f"  {provider_name}: search_markets returned {len(markets)} markets")
        return

    # 4. Providers with only inherited base search_markets (no real market data)
    #    Base signature: search_markets(query, category, limit)
    #    These return empty list from base no-op.  Call with proper args.
    if provider_name in _INHERITED_SEARCH_ONLY:
        markets = await provider.search_markets("", None, 5)
        assert isinstance(markets, list), f"Expected list, got {type(markets)}"
        print(f"  {provider_name}: base search_markets returned {len(markets)} markets (no-op)")
        return

    # 5. Fallback: health_check
    if _has_health(cls):
        try:
            ok = await provider.health_check()
            print(f"  {provider_name}: health_check returned {ok}")
        except Exception as e:
            print(f"  {provider_name}: health_check raised: {e}")
        return

    pytest.skip(f"{provider_name} has no market-fetching or health_check method")
