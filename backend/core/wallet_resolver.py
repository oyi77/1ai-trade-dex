"""
Wallet Resolver -- Resolve ANY wallet input format to structured wallet info.

Input formats:
- ``0x...`` (hex address) -- auto-detect EOA vs proxy via closed positions / proxy_finder
- ``@username`` -- strip @, fetch Polymarket profile page
- bare ``username`` -- fetch Polymarket profile page

Resolution returns a ``WalletInfo`` dataclass with EOA, proxy, and metadata.
"""

import json
import logging
import re
from dataclasses import dataclass
from typing import Optional

import httpx

from backend.config import settings
from backend.core.proxy_finder import find_proxy_wallet
from backend.data.wallet_history import get_all_closed_positions

logger = logging.getLogger(__name__)

PROFILE_URL = f"{settings.POLYMARKET_BASE_URL}/@{{username}}"
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__".*?>(.*?)</script>', re.DOTALL
)


@dataclass
class WalletInfo:
    """Resolved wallet information."""

    eoa: Optional[str] = None
    proxy: Optional[str] = None
    username: Optional[str] = None
    method: str = "unknown"
    is_proxy: bool = False
    has_traded: bool = False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def resolve_wallet(input_str: str) -> WalletInfo:
    """Resolve any wallet input format to structured wallet info.

    Parameters
    ----------
    input_str:
        One of: ``0x...`` hex address, ``@username``, or bare ``username``.

    Returns
    -------
    WalletInfo
        Resolved wallet details. Fields may be ``None`` when the
        corresponding data could not be determined.
    """
    input_str = input_str.strip()

    if input_str.startswith("0x"):
        return await _resolve_hex(input_str)

    # Strip leading @
    username = input_str.lstrip("@")
    return await _resolve_username(username)


# ---------------------------------------------------------------------------
# Hex address resolution
# ---------------------------------------------------------------------------


async def _resolve_hex(address: str) -> WalletInfo:
    """Resolve a 0x... address -- check if proxy, else try proxy_finder."""
    # Step 1: check if it's already a proxy (has closed positions)
    try:
        positions = await get_all_closed_positions(address)
        if positions:
            logger.debug(
                "Address %s has closed positions; treating as proxy", address
            )
            return WalletInfo(
                proxy=address,
                method="closed_positions",
                is_proxy=True,
                has_traded=True,
            )
    except Exception as exc:
        logger.debug("Closed-position check failed for %s: %s", address, exc)

    # Step 2: try proxy_finder to see if it's an EOA with an associated proxy
    try:
        proxy = await find_proxy_wallet(address)
        if proxy:
            logger.debug("proxy_finder resolved %s -> %s", address, proxy)
            return WalletInfo(
                eoa=address,
                proxy=proxy,
                method="proxy_finder",
                is_proxy=False,
                has_traded=True,
            )
    except Exception as exc:
        logger.debug("proxy_finder failed for %s: %s", address, exc)

    # Step 3: unknown -- return bare address as EOA
    logger.debug("No resolution for hex %s; returning as bare EOA", address)
    return WalletInfo(eoa=address, method="hex_passthrough", has_traded=False)


# ---------------------------------------------------------------------------
# Username resolution
# ---------------------------------------------------------------------------


async def _resolve_username(username: str) -> WalletInfo:
    """Resolve a username by fetching the Polymarket profile page."""
    url = PROFILE_URL.format(username=username)
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.warning(
                    "Profile page returned %d for @%s", resp.status_code, username
                )
                return WalletInfo(
                    username=username, method="profile_page_error", has_traded=False
                )

            return _parse_profile_html(resp.text, username)

    except Exception as exc:
        logger.warning("Profile fetch failed for @%s: %s", username, exc)
        return WalletInfo(
            username=username, method="profile_fetch_error", has_traded=False
        )


def _parse_profile_html(html: str, username: str) -> WalletInfo:
    """Extract EOA and proxy wallet from Polymarket profile page __NEXT_DATA__."""
    match = _NEXT_DATA_RE.search(html)
    if not match:
        logger.warning("No __NEXT_DATA__ found for @%s", username)
        return WalletInfo(
            username=username, method="no_next_data", has_traded=False
        )

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        logger.warning("Invalid JSON in __NEXT_DATA__ for @%s", username)
        return WalletInfo(
            username=username, method="invalid_json", has_traded=False
        )

    eoa: Optional[str] = None
    proxy: Optional[str] = None

    queries = (
        data.get("props", {})
        .get("pageProps", {})
        .get("dehydratedState", {})
        .get("queries", [])
    )

    for q in queries:
        key = str(q.get("queryKey", ""))
        state_data = q.get("state", {}).get("data", {})
        if not isinstance(state_data, dict):
            continue

        if "user-clob" in key.lower():
            eoa = state_data.get("address") or eoa
            proxy = state_data.get("polygonAddress") or proxy

        if "user" in key.lower() and "address" in state_data:
            proxy = proxy or state_data.get("address")

    if not eoa and not proxy:
        logger.warning(
            "Parsed __NEXT_DATA__ but found no wallet for @%s", username
        )
        return WalletInfo(
            username=username, method="no_wallet_in_data", has_traded=False
        )

    return WalletInfo(
        eoa=eoa,
        proxy=proxy,
        username=username,
        method="profile_page",
        is_proxy=False,
        has_traded=True,
    )
