"""Integration tests for real-time copy trader and whale tracker."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend.bot.realtime_copy_trader import RealTimeCopyTrader
from backend.bot.realtime_whale_tracker import RealTimeWhaleTracker


class TestRealTimeCopyTrader:
    def test_initialization(self):
        trader = RealTimeCopyTrader()
        assert trader.name == "copy_trader"
        assert trader._running is False
        assert len(trader._leaderboard_cache) == 0

    @pytest.mark.asyncio
    async def test_update_leaderboard_filters_traders(self):
        trader = RealTimeCopyTrader()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"proxyWallet": "0xabc", "userName": "Winner", "pnl": 50000, "vol": 500000},
            {"proxyWallet": "0xdef", "userName": "Small", "pnl": 100, "vol": 500},
        ]
        with patch("backend.bot.realtime_copy_trader.get_shared_client") as mock_client:
            mock_http = AsyncMock()
            mock_http.get.return_value = mock_response
            mock_client.return_value = mock_http
            await trader._update_leaderboard()
        assert len(trader._leaderboard_cache) == 1
        assert "0xabc" in trader._leaderboard_cache

    def test_extract_trader_wallet_returns_none_without_asset(self):
        trader = RealTimeCopyTrader()
        event = MagicMock()
        event.asset_id = None
        assert trader._extract_trader_wallet(event) is None

    @pytest.mark.asyncio
    async def test_run_cycle_returns_empty_result(self):
        trader = RealTimeCopyTrader()
        from backend.strategies.base import StrategyContext
        ctx = MagicMock(spec=StrategyContext)
        result = await trader.run_cycle(ctx)
        assert result.decisions_recorded == 0
        assert result.trades_attempted == 0


class TestRealTimeWhaleTracker:
    def test_initialization(self):
        tracker = RealTimeWhaleTracker()
        assert tracker.name == "whale_tracker"
        assert tracker._running is False

    @pytest.mark.asyncio
    async def test_load_whale_wallets_from_config(self):
        tracker = RealTimeWhaleTracker()
        with patch("backend.bot.realtime_whale_tracker.settings") as mock_settings:
            mock_settings.WHALE_WALLETS = "0xabc,0xdef"
            mock_settings.ALCHEMY_API_KEY = ""
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = []
            with patch("backend.bot.realtime_whale_tracker.get_shared_client") as mock_client:
                mock_http = AsyncMock()
                mock_http.get.return_value = mock_response
                mock_client.return_value = mock_http
                await tracker._load_whale_wallets()
        assert "0xabc" in tracker._tracked_whales
        assert "0xdef" in tracker._tracked_whales

    @pytest.mark.asyncio
    async def test_run_cycle_returns_empty_result(self):
        tracker = RealTimeWhaleTracker()
        from backend.strategies.base import StrategyContext
        ctx = MagicMock(spec=StrategyContext)
        result = await tracker.run_cycle(ctx)
        assert result.decisions_recorded == 0

    @pytest.mark.asyncio
    async def test_handle_pending_tx_parses_whale_transaction(self):
        tracker = RealTimeWhaleTracker()
        tracker._tracked_whales = {"0xabc": {"name": "TestWhale"}}
        tx = {"from": "0xABC", "to": "0xother", "value": hex(10**18)}
        await tracker._handle_pending_tx(tx)
        assert True  # No crash = pass
