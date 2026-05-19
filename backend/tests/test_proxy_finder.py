"""Tests for backend.core.proxy_finder -- EOA-to-proxy resolution."""

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.proxy_finder import (
    CACHE_TTL,
    PUSD_ADDRESS,
    ZERO_ADDRESS,
    _save_cache,
    find_proxy_wallet,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

EOA = "0xAbCdEf0123456789AbCdEf0123456789AbCdEf01"
PROXY = "0x1111111111111111111111111111111111111111"


@pytest.fixture(autouse=True)
def _clean_cache(tmp_path, monkeypatch):
    """Redirect CACHE_DIR to a temp dir so tests never touch real data."""
    monkeypatch.setattr("backend.core.proxy_finder.CACHE_DIR", tmp_path / "proxy_cache")
    return tmp_path / "proxy_cache"


# ---------------------------------------------------------------------------
# 1. Happy path -- Blockscout returns PUSD MINT transfer
# ---------------------------------------------------------------------------

class TestHappyPathMint:
    """Method A: PUSD MINT event yields proxy address."""

    async def test_mint_returns_proxy(self):
        transfer_item = {
            "token": {"address": PUSD_ADDRESS},
            "from": {"address": ZERO_ADDRESS},
            "to": {"address": PROXY},
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"items": [transfer_item]}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.core.proxy_finder.httpx.AsyncClient", return_value=mock_client):
            result = await find_proxy_wallet(EOA)

        assert result == PROXY


# ---------------------------------------------------------------------------
# 2. No transfers -- empty response returns None
# ---------------------------------------------------------------------------

class TestNoTransfers:
    """Both methods return empty -> None."""

    async def test_empty_token_transfers_returns_none(self):
        empty_resp = MagicMock()
        empty_resp.status_code = 200
        empty_resp.json.return_value = {"items": []}

        empty_internal = MagicMock()
        empty_internal.status_code = 200
        empty_internal.json.return_value = {"items": []}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[empty_resp, empty_internal])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.core.proxy_finder.httpx.AsyncClient", return_value=mock_client):
            result = await find_proxy_wallet(EOA)

        assert result is None


# ---------------------------------------------------------------------------
# 3. Cache hit -- pre-populated cache returns value without API call
# ---------------------------------------------------------------------------

class TestCacheHit:
    """Cached value is returned without hitting the network."""

    async def test_cache_hit_skips_api(self, _clean_cache):
        # Pre-populate cache
        _save_cache(EOA, PROXY)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock()  # should never be called

        with patch("backend.core.proxy_finder.httpx.AsyncClient", return_value=mock_client):
            result = await find_proxy_wallet(EOA)

        assert result == PROXY
        mock_client.get.assert_not_called()


# ---------------------------------------------------------------------------
# 4. Cache expiry -- stale entry triggers fresh API call
# ---------------------------------------------------------------------------

class TestCacheExpiry:
    """Expired cache is ignored; fresh API result is used."""

    async def test_expired_cache_refreshes(self, _clean_cache):
        # Write an expired cache entry
        cache_file = _clean_cache / f"{EOA[2:14].lower()}.json"
        _clean_cache.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({
            "eoa": EOA,
            "proxy": "0xSTALE",
            "timestamp": time.time() - CACHE_TTL - 100,
        }))

        transfer_item = {
            "token": {"address": PUSD_ADDRESS},
            "from": {"address": ZERO_ADDRESS},
            "to": {"address": PROXY},
        }
        fresh_resp = MagicMock()
        fresh_resp.status_code = 200
        fresh_resp.json.return_value = {"items": [transfer_item]}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=fresh_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.core.proxy_finder.httpx.AsyncClient", return_value=mock_client):
            result = await find_proxy_wallet(EOA)

        assert result == PROXY  # fresh value, not 0xSTALE
        mock_client.get.assert_called_once()


# ---------------------------------------------------------------------------
# 5. Network error -- httpx exception returns None gracefully
# ---------------------------------------------------------------------------

class TestNetworkError:
    """Network failures are caught and return None."""

    async def test_httpx_exception_returns_none(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.core.proxy_finder.httpx.AsyncClient", return_value=mock_client):
            result = await find_proxy_wallet(EOA)

        assert result is None

    async def test_non_200_returns_none(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.core.proxy_finder.httpx.AsyncClient", return_value=mock_client):
            result = await find_proxy_wallet(EOA)

        assert result is None


# ---------------------------------------------------------------------------
# 6. Force refresh -- ignores cache
# ---------------------------------------------------------------------------

class TestForceRefresh:
    """force_refresh=True bypasses the cache."""

    async def test_force_refresh_ignores_cache(self, _clean_cache):
        _save_cache(EOA, "0xCACHED")

        transfer_item = {
            "token": {"address": PUSD_ADDRESS},
            "from": {"address": ZERO_ADDRESS},
            "to": {"address": PROXY},
        }
        fresh_resp = MagicMock()
        fresh_resp.status_code = 200
        fresh_resp.json.return_value = {"items": [transfer_item]}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=fresh_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.core.proxy_finder.httpx.AsyncClient", return_value=mock_client):
            result = await find_proxy_wallet(EOA, force_refresh=True)

        assert result == PROXY
        mock_client.get.assert_called_once()


# ---------------------------------------------------------------------------
# 7. Method C fallback -- internal tx used when Method A fails
# ---------------------------------------------------------------------------

class TestMethodCFallback:
    """Internal-tx method is called when mint method returns nothing."""

    async def test_internal_tx_fallback(self):
        empty_mint = MagicMock()
        empty_mint.status_code = 200
        empty_mint.json.return_value = {"items": []}

        internal_resp = MagicMock()
        internal_resp.status_code = 200
        internal_resp.json.return_value = {
            "items": [{"to": {"address": PROXY}}]
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[empty_mint, internal_resp])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.core.proxy_finder.httpx.AsyncClient", return_value=mock_client):
            result = await find_proxy_wallet(EOA)

        assert result == PROXY
        assert mock_client.get.call_count == 2
