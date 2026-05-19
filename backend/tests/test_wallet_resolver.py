"""Tests for backend.core.wallet_resolver module."""

import json

import pytest

from backend.core.wallet_resolver import resolve_wallet


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_profile_html(eoa: str, proxy: str, username: str = "testuser") -> str:
    """Build a minimal Polymarket profile page HTML with __NEXT_DATA__."""
    next_data = {
        "props": {
            "pageProps": {
                "dehydratedState": {
                    "queries": [
                        {
                            "queryKey": ["user-clob", username],
                            "state": {
                                "data": {
                                    "address": eoa,
                                    "polygonAddress": proxy,
                                }
                            },
                        },
                        {
                            "queryKey": ["user", username],
                            "state": {
                                "data": {
                                    "address": proxy,
                                }
                            },
                        },
                    ]
                }
            }
        }
    }
    return (
        "<html><head>"
        f'<script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(next_data)}</script>"
        "</head><body></body></html>"
    )


# ---------------------------------------------------------------------------
# 1. Username input: mock profile page -> returns WalletInfo with eoa + proxy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_username_resolves_eoa_and_proxy(monkeypatch):
    """Bare username fetches profile page and extracts both wallets."""
    eoa = "0xAbCdEf0123456789AbCdEf0123456789AbCdEf01"
    proxy = "0x1234567890aBcDeF1234567890aBcDeF12345678"
    html = _make_profile_html(eoa, proxy, "alice")

    class FakeResponse:
        status_code = 200
        text = html

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, url, **kw):
            return FakeResponse()

    import backend.core.wallet_resolver as mod

    monkeypatch.setattr(mod, "httpx", type("H", (), {"AsyncClient": lambda **kw: FakeClient()}))

    info = await resolve_wallet("alice")

    assert info.eoa == eoa
    assert info.proxy == proxy
    assert info.username == "alice"
    assert info.method == "profile_page"
    assert info.has_traded is True


# ---------------------------------------------------------------------------
# 2. EOA input: mock proxy_finder -> returns WalletInfo with proxy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_eoa_resolves_via_proxy_finder(monkeypatch):
    """0x address without closed positions falls through to proxy_finder."""
    eoa = "0xAbCdEf0123456789AbCdEf0123456789AbCdEf01"
    proxy = "0x1234567890aBcDeF1234567890aBcDeF12345678"

    import backend.core.wallet_resolver as mod

    async def fake_closed(wallet, **kw):
        return []

    async def fake_proxy(wallet, **kw):
        return proxy

    monkeypatch.setattr(mod, "get_all_closed_positions", fake_closed)
    monkeypatch.setattr(mod, "find_proxy_wallet", fake_proxy)

    info = await resolve_wallet(eoa)

    assert info.eoa == eoa
    assert info.proxy == proxy
    assert info.method == "proxy_finder"
    assert info.has_traded is True


# ---------------------------------------------------------------------------
# 3. Proxy input: mock closed positions check -> returns WalletInfo with is_proxy=True
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_proxy_detected_via_closed_positions(monkeypatch):
    """0x address with closed positions is classified as a proxy wallet."""
    proxy = "0x1234567890aBcDeF1234567890aBcDeF12345678"

    import backend.core.wallet_resolver as mod

    async def fake_closed(wallet, **kw):
        return [{"id": "pos1", "title": "BTC > 100k"}]

    monkeypatch.setattr(mod, "get_all_closed_positions", fake_closed)

    info = await resolve_wallet(proxy)

    assert info.proxy == proxy
    assert info.is_proxy is True
    assert info.method == "closed_positions"
    assert info.has_traded is True


# ---------------------------------------------------------------------------
# 4. @username input: strip @ and resolve
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_at_username_strips_at_and_resolves(monkeypatch):
    """@username is treated identically to bare username."""
    eoa = "0xAbCdEf0123456789AbCdEf0123456789AbCdEf01"
    proxy = "0x1234567890aBcDeF1234567890aBcDeF12345678"
    html = _make_profile_html(eoa, proxy, "bob")

    class FakeResponse:
        status_code = 200
        text = html

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, url, **kw):
            return FakeResponse()

    import backend.core.wallet_resolver as mod

    monkeypatch.setattr(mod, "httpx", type("H", (), {"AsyncClient": lambda **kw: FakeClient()}))

    info = await resolve_wallet("@bob")

    assert info.username == "bob"
    assert info.eoa == eoa
    assert info.proxy == proxy


# ---------------------------------------------------------------------------
# 5. Unknown wallet: mock empty responses -> returns WalletInfo with has_traded=False
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_wallet_returns_empty(monkeypatch):
    """Unknown 0x address with no closed positions and no proxy returns bare info."""
    addr = "0x000000000000000000000000000000000000dEaD"

    import backend.core.wallet_resolver as mod

    async def fake_closed(wallet, **kw):
        return []

    async def fake_proxy(wallet, **kw):
        return None

    monkeypatch.setattr(mod, "get_all_closed_positions", fake_closed)
    monkeypatch.setattr(mod, "find_proxy_wallet", fake_proxy)

    info = await resolve_wallet(addr)

    assert info.eoa == addr
    assert info.proxy is None
    assert info.has_traded is False
    assert info.method == "hex_passthrough"


# ---------------------------------------------------------------------------
# 6. Network error: graceful fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_network_error_graceful_fallback(monkeypatch):
    """Network errors during profile fetch return a fallback WalletInfo."""
    import backend.core.wallet_resolver as mod

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, url, **kw):
            raise ConnectionError("network down")

    monkeypatch.setattr(mod, "httpx", type("H", (), {"AsyncClient": lambda **kw: FakeClient()}))

    info = await resolve_wallet("someuser")

    assert info.username == "someuser"
    assert info.method == "profile_fetch_error"
    assert info.has_traded is False
    assert info.eoa is None
    assert info.proxy is None
