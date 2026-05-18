"""ETH and SOL 5-minute market discovery convenience functions.

Thin wrapper around the generalized btc_markets.py (which already supports
BTC, ETH, and SOL via the asset parameter). Provides ETH/SOL-specific
aliases and keyword defaults for easier imports.

Usage:
    from backend.data.eth_sol_markets import (
        fetch_active_eth_markets,
        fetch_active_sol_markets,
        fetch_eth_market_by_slug,
        fetch_sol_market_by_slug,
    )
"""
from typing import List, Optional

from backend.data.btc_markets import (
    CryptoMarket,
    fetch_active_crypto_markets,
    fetch_crypto_market_by_slug,
    fetch_crypto_market_for_settlement,
    is_valid_crypto_slug,
)


# --- ETH ---

async def fetch_active_eth_markets(keywords: List[str] = None) -> List[CryptoMarket]:
    """Fetch current and upcoming ETH 5-min markets from Polymarket."""
    return await fetch_active_crypto_markets(asset="eth", keywords=keywords)


async def fetch_eth_market_by_slug(slug: str) -> Optional[CryptoMarket]:
    """Fetch a single ETH 5-min market by its event slug."""
    return await fetch_crypto_market_by_slug(slug, asset="eth")


async def fetch_eth_market_for_settlement(slug: str) -> Optional[CryptoMarket]:
    """Fetch an ETH market for settlement purposes (includes closed markets)."""
    return await fetch_crypto_market_for_settlement(slug, asset="eth")


def is_valid_eth_slug(slug: str) -> bool:
    """Return True only if slug matches the exact ETH 5-min pattern."""
    return is_valid_crypto_slug(slug, asset="eth")


# --- SOL ---

async def fetch_active_sol_markets(keywords: List[str] = None) -> List[CryptoMarket]:
    """Fetch current and upcoming SOL 5-min markets from Polymarket."""
    return await fetch_active_crypto_markets(asset="sol", keywords=keywords)


async def fetch_sol_market_by_slug(slug: str) -> Optional[CryptoMarket]:
    """Fetch a single SOL 5-min market by its event slug."""
    return await fetch_crypto_market_by_slug(slug, asset="sol")


async def fetch_sol_market_for_settlement(slug: str) -> Optional[CryptoMarket]:
    """Fetch a SOL market for settlement purposes (includes closed markets)."""
    return await fetch_crypto_market_for_settlement(slug, asset="sol")


def is_valid_sol_slug(slug: str) -> bool:
    """Return True only if slug matches the exact SOL 5-min pattern."""
    return is_valid_crypto_slug(slug, asset="sol")
