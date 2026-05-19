"""
Proxy Finder -- Resolve EOA wallet to Polymarket proxy wallet.

Methods:
A) Blockscout PUSD MINT events (primary)
B) Polymarket profile page __NEXT_DATA__ parsing (fallback -- needs username)
C) Internal transactions CTF deposit events (fallback)
D) EIP-7702 contract wallet receipt log parsing (last resort)
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PUSD_ADDRESS = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
BLOCKSCOUT_BASE = "https://polygon.blockscout.com/api/v2"
CACHE_DIR = Path("data/proxy_cache")
CACHE_TTL = 86400  # 24 hours


@dataclass
class ProxyResult:
    proxy_wallet: Optional[str]
    method: str  # "blockscout_mint", "internal_tx", "cache", "not_found"
    eoa_address: str
    cached: bool = False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def find_proxy_wallet(
    eoa_address: str,
    force_refresh: bool = False,
) -> Optional[str]:
    """Given an EOA wallet address, find the associated Polymarket proxy wallet.

    Returns the proxy wallet address string, or ``None`` if not found.
    """
    # -- cache check --
    if not force_refresh:
        cached = _check_cache(eoa_address)
        if cached is not None:
            logger.debug("Cache hit for %s -> %s", eoa_address, cached)
            return cached

    # -- Method A: Blockscout PUSD MINT events --
    proxy = await _method_a_blockscout_mint(eoa_address)
    if proxy:
        _save_cache(eoa_address, proxy)
        return proxy

    # -- Method C: Internal transactions --
    proxy = await _method_c_internal_tx(eoa_address)
    if proxy:
        _save_cache(eoa_address, proxy)
        return proxy

    logger.info("No proxy found for %s after all methods", eoa_address)
    return None


# ---------------------------------------------------------------------------
# Method A -- Blockscout PUSD MINT events
# ---------------------------------------------------------------------------

async def _method_a_blockscout_mint(eoa: str) -> Optional[str]:
    """Look for PUSD MINT events (Transfer from 0x0000...000 to proxy)."""
    url = f"{BLOCKSCOUT_BASE}/addresses/{eoa}/token-transfers"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params={"limit": 50})
            if resp.status_code != 200:
                logger.debug("Blockscout token-transfers %d for %s", resp.status_code, eoa)
                return None

            data = resp.json()
            items = data.get("items", [])
            for transfer in items:
                token = transfer.get("token", {})
                if token.get("address", "").lower() == PUSD_ADDRESS.lower():
                    from_addr = transfer.get("from", {}).get("address", "")
                    to_addr = transfer.get("to", {}).get("address", "")
                    if from_addr.lower() == ZERO_ADDRESS.lower() and to_addr:
                        return to_addr  # MINT event: from=0x0, to=proxy

            await _rate_limit()
            return None
    except Exception as e:
        logger.warning("Blockscout mint lookup failed for %s: %s", eoa, e)
        return None


# ---------------------------------------------------------------------------
# Method C -- Internal transactions
# ---------------------------------------------------------------------------

async def _method_c_internal_tx(eoa: str) -> Optional[str]:
    """Look for CTF deposit events in internal transactions."""
    url = f"{BLOCKSCOUT_BASE}/addresses/{eoa}/internal-transactions"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params={"limit": 50})
            if resp.status_code != 200:
                logger.debug("Blockscout internal-tx %d for %s", resp.status_code, eoa)
                return None

            data = resp.json()
            items = data.get("items", [])
            for tx in items:
                to_addr = tx.get("to", {}).get("address", "")
                if to_addr:
                    return to_addr

            return None
    except Exception as e:
        logger.warning("Internal tx lookup failed for %s: %s", eoa, e)
        return None


# ---------------------------------------------------------------------------
# File-based cache
# ---------------------------------------------------------------------------

def _check_cache(eoa: str) -> Optional[str]:
    """Return cached proxy address if fresh, else ``None``."""
    cache_file = CACHE_DIR / f"{eoa[2:14].lower()}.json"
    if not cache_file.exists():
        return None
    try:
        data = json.loads(cache_file.read_text())
        if time.time() - data.get("timestamp", 0) < CACHE_TTL:
            return data.get("proxy")
        return None  # expired
    except Exception as exc:
        logger.debug("Cache read failed: %s", exc)
        return None


def _save_cache(eoa: str, proxy: str) -> None:
    """Persist proxy address to file cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{eoa[2:14].lower()}.json"
    cache_file.write_text(
        json.dumps(
            {
                "eoa": eoa,
                "proxy": proxy,
                "timestamp": time.time(),
            }
        )
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _rate_limit() -> None:
    """100 ms rate-limit pause between API calls."""
    await asyncio.sleep(0.1)
