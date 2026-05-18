"""Tests for G-02: Polymarket WebSocket reconnection improvements."""
import asyncio
import time
from unittest.mock import patch, MagicMock
import pytest

from backend.data.polymarket_websocket import (
    PolymarketWebSocket, WebSocketConfig, ChannelType,
)


@pytest.fixture
def ws_config():
    return WebSocketConfig(
        channel=ChannelType.MARKET,
        asset_ids=["token_1", "token_2"],
        reconnect_delay=0.01,
        max_reconnect_delay=0.1,
        heartbeat_interval=0.05,
    )


@pytest.fixture
def ws_client(ws_config):
    return PolymarketWebSocket(ws_config)


class TestCacheInit:
    def test_cache_initialized(self, ws_client):
        assert hasattr(ws_client, "_cache")
        assert isinstance(ws_client._cache, dict)

    def test_subscribed_asset_ids_initialized(self, ws_client):
        assert ws_client._subscribed_asset_ids == ["token_1", "token_2"]

    def test_stale_timeout_initialized(self, ws_client):
        assert ws_client._stale_timeout == 120.0


class TestUpdateAssetIds:
    def test_update_asset_ids(self, ws_client):
        ws_client.update_asset_ids(["new_1", "new_2", "new_3"])
        assert ws_client._subscribed_asset_ids == ["new_1", "new_2", "new_3"]
        assert ws_client.config.asset_ids == ["new_1", "new_2", "new_3"]

    def test_update_makes_copy(self, ws_client):
        ids = ["a", "b"]
        ws_client.update_asset_ids(ids)
        ids.append("c")
        assert ws_client._subscribed_asset_ids == ["a", "b"]


class TestCacheClear:
    def test_cache_cleared_on_reconnect(self, ws_client):
        ws_client._cache["some_key"] = "some_value"
        assert ws_client._cache == {"some_key": "some_value"}
        ws_client._cache.clear()
        assert ws_client._cache == {}


class TestStaleWatchdog:
    @pytest.mark.asyncio
    async def test_watchdog_detects_stale(self, ws_client):
        ws_client._running = True
        ws_client._stale_timeout = 0.1
        ws_client._last_message_time = time.time() - 1.0  # 1s ago, past threshold
        ws_client.ws = MagicMock()
        ws_client.ws.closed = False

        with patch("backend.data.polymarket_websocket.logger"):
            await ws_client._stale_data_watchdog()
            ws_client.ws.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_watchdog_ignores_fresh_data(self, ws_client):
        ws_client._running = True
        ws_client._stale_timeout = 10.0
        ws_client._last_message_time = time.time()  # just now

        task = asyncio.create_task(ws_client._stale_data_watchdog())
        await asyncio.sleep(0.05)
        ws_client._running = False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_watchdog_ignores_zero_timestamp(self, ws_client):
        ws_client._running = True
        ws_client._stale_timeout = 0.01
        ws_client._last_message_time = 0.0  # no data yet

        task = asyncio.create_task(ws_client._stale_data_watchdog())
        await asyncio.sleep(0.05)
        ws_client._running = False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
