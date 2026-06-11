"""Tests for wallet_history — Polymarket Data API position/PnL fetching."""

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.data.wallet_history import (
    CACHE_TTL,
    get_all_closed_positions,
    get_open_positions,
    get_pnl_history,
    get_user_activity_summary,
)

WALLET = "0xabcdef1234567890abcdef1234567890abcdef12"


def _positions_page(start: int, count: int) -> list[dict]:
    """Generate a page of mock closed positions."""
    return [
        {
            "title": f"Market {start + i}",
            "realizedPnl": str(10.0 + i),
            "totalBought": str(50.0 + i * 5),
            "timestamp": 1700000000 + (start + i) * 100,
        }
        for i in range(count)
    ]


def _make_response(data):
    """Create a MagicMock that behaves like an httpx.Response (sync json())."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = data
    return resp


# ---------------------------------------------------------------------------
# 1. Pagination: 3 pages -> all 100 positions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pagination_returns_all_positions(tmp_path):
    """Mock 3 pages (offset 0/50/100) and verify all 100 positions returned."""
    page0 = _positions_page(0, 50)
    page1 = _positions_page(50, 50)
    page2 = []  # empty page terminates

    responses = [page0, page1, page2]
    call_count = 0

    class FakeClient:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, url, params=None):
            nonlocal call_count
            resp = _make_response(responses[call_count])
            call_count += 1
            return resp

    with patch("backend.data.wallet_history.get_shared_client", lambda: FakeClient()):
        with patch("backend.data.wallet_history.CACHE_DIR", tmp_path):
            result = await get_all_closed_positions(WALLET, force_refresh=True)

    assert len(result) == 100
    assert result[0]["title"] == "Market 0"
    assert result[99]["title"] == "Market 99"


# ---------------------------------------------------------------------------
# 2. Empty wallet -> empty list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_wallet_returns_empty(tmp_path):
    class FakeClient:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, url, params=None):
            return _make_response([])

    with patch("backend.data.wallet_history.get_shared_client", lambda: FakeClient()):
        with patch("backend.data.wallet_history.CACHE_DIR", tmp_path):
            result = await get_all_closed_positions(WALLET, force_refresh=True)

    assert result == []


# ---------------------------------------------------------------------------
# 3. Cache hit returns cached data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_hit_skips_network(tmp_path):
    cached_data = [{"title": "Cached", "realizedPnl": "5"}]
    cache_file = tmp_path / f"{WALLET[2:14].lower()}_positions.json"
    cache_file.write_text(json.dumps({"data": cached_data, "timestamp": time.time()}))

    with patch("backend.data.wallet_history.CACHE_DIR", tmp_path):
        result = await get_all_closed_positions(WALLET, force_refresh=False)

    assert result == cached_data


# ---------------------------------------------------------------------------
# 4. PnL history: peak, min, current, drawdown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pnl_history_calculations():
    positions = [
        {"title": "A", "realizedPnl": "100", "totalBought": "500", "timestamp": 1000},
        {"title": "B", "realizedPnl": "-250", "totalBought": "300", "timestamp": 2000},
        {"title": "C", "realizedPnl": "400", "totalBought": "600", "timestamp": 3000},
    ]

    mock_fetch = AsyncMock(return_value=positions)
    with patch("backend.data.wallet_history.get_all_closed_positions", mock_fetch):
        pnl = await get_pnl_history(WALLET)

    # Running: 100 -> -150 -> 250
    # Peak updates at each new high: 100 (A), then 250 (C)
    assert pnl.peak == 250.0
    assert pnl.peak_trade["title"] == "C"
    assert pnl.min == -150.0
    assert pnl.min_trade["title"] == "B"
    assert pnl.current == 250.0
    assert pnl.total_positions == 3
    assert pnl.max_drawdown == 400.0  # 250 - (-150)
    assert len(pnl.pnl_history) == 3


# ---------------------------------------------------------------------------
# 5. Activity summary: total_trades, total_volume, avg
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_activity_summary():
    positions = [
        {"totalBought": "100", "timestamp": 1000},
        {"totalBought": "200", "timestamp": 2000},
        {"totalBought": "300", "timestamp": 3000},
    ]

    mock_fetch = AsyncMock(return_value=positions)
    with patch("backend.data.wallet_history.get_all_closed_positions", mock_fetch):
        summary = await get_user_activity_summary(WALLET)

    assert summary.total_trades == 3
    assert summary.total_volume == 600.0
    assert summary.avg_trade_size == 200.0
    assert summary.last_active == 3000


# ---------------------------------------------------------------------------
# 6. Network error -> empty gracefully
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_network_error_returns_empty(tmp_path):
    class FailClient:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, url, params=None):
            raise ConnectionError("network down")

    with patch("backend.data.wallet_history.get_shared_client", lambda: FailClient()):
        with patch("backend.data.wallet_history.CACHE_DIR", tmp_path):
            result = await get_all_closed_positions(WALLET, force_refresh=True)

    assert result == []


# ---------------------------------------------------------------------------
# 7. Cache expiry: stale cache -> network fetch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_cache_triggers_refresh(tmp_path):
    stale_data = [{"title": "Old"}]
    p = tmp_path / f"{WALLET[2:14].lower()}_positions.json"
    p.write_text(
        json.dumps({"data": stale_data, "timestamp": time.time() - CACHE_TTL - 1})
    )

    fresh_data = [{"title": "Fresh"}]
    calls = 0

    class FakeClient:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, url, params=None):
            nonlocal calls
            calls += 1
            # First call returns data, second returns empty to stop pagination
            return _make_response(fresh_data if calls == 1 else [])

    with patch("backend.data.wallet_history.get_shared_client", lambda: FakeClient()):
        with patch("backend.data.wallet_history.CACHE_DIR", tmp_path):
            result = await get_all_closed_positions(WALLET, force_refresh=False)

    assert result == fresh_data


# ---------------------------------------------------------------------------
# 8. Open positions fetch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_open_positions():
    mock_positions = [{"title": "Open1", "size": "10"}]

    class FakeClient:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, url, params=None):
            return _make_response(mock_positions)

    with patch("backend.data.wallet_history.get_shared_client", lambda: FakeClient()):
        result = await get_open_positions(WALLET)

    assert result == mock_positions


# ---------------------------------------------------------------------------
# 9. Recovery count in PnL history
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recovery_count():
    """Positions that go below -200 then back above 0 should count as recovery."""
    positions = [
        {"title": "A", "realizedPnl": "50", "totalBought": "100", "timestamp": 1000},
        {"title": "B", "realizedPnl": "-300", "totalBought": "200", "timestamp": 2000},
        {"title": "C", "realizedPnl": "400", "totalBought": "300", "timestamp": 3000},
    ]

    mock_fetch = AsyncMock(return_value=positions)
    with patch("backend.data.wallet_history.get_all_closed_positions", mock_fetch):
        pnl = await get_pnl_history(WALLET)

    # Running: 50 -> -250 (below -200) -> 150 (back above 0) = 1 recovery
    assert pnl.recovery_count == 1
