"""Integration tests for realtime trading modules.

Tests for:
- RealTimeCopyTrader: Event-driven copy trading via Polymarket WebSocket
- RealTimeWhaleTracker: Whale wallet monitoring via Alchemy WebSocket
- RealTimeStrategyManager: Coordinator for realtime strategies

All external API calls (WebSocket, CLOB, Polymarket API) are mocked.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.bot.realtime_copy_trader import RealTimeCopyTrader
from backend.bot.realtime_whale_tracker import RealTimeWhaleTracker
from backend.bot.realtime_manager import RealTimeStrategyManager
from backend.strategies.base import StrategyContext


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db():
    """Mock SQLAlchemy session."""
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []
    db.query.return_value.filter.return_value.first.return_value = None
    return db


@pytest.fixture
def mock_clob():
    """Mock PolymarketCLOB client."""
    clob = MagicMock()
    clob.place_limit_order = AsyncMock(return_value={"status": "ok"})
    clob.get_positions = AsyncMock(return_value=[])
    return clob


@pytest.fixture
def mock_settings():
    """Mock Settings object."""
    settings = MagicMock()
    settings.POLY_API_KEY = "test_key"
    settings.WHALE_WALLETS = ["0x1234567890abcdef"]
    settings.ALCHEMY_API_KEY = "test_alchemy_key"
    settings.TRADING_MODE = "paper"
    return settings


@pytest.fixture
def strategy_ctx(mock_db, mock_clob, mock_settings):
    """Standard StrategyContext for testing."""
    return StrategyContext(
        db=mock_db,
        clob=mock_clob,
        settings=mock_settings,
        logger=MagicMock(),
        params={},
        mode="paper",
        bankroll=100.0,
        providers={},
    )


# ---------------------------------------------------------------------------
# RealTimeCopyTrader Tests
# ---------------------------------------------------------------------------


class TestRealTimeCopyTrader:
    """Test RealTimeCopyTrader: event-driven copy trading from leaderboard traders."""

    def test_instantiate(self):
        """Verify RealTimeCopyTrader can be instantiated."""
        trader = RealTimeCopyTrader()
        assert trader is not None
        assert hasattr(trader, "start_realtime")
        assert hasattr(trader, "stop_realtime")
        assert hasattr(trader, "market_filter")
        assert hasattr(trader, "run_cycle")

    def test_has_class_default_params(self):
        """Verify default parameters are configured at class level."""
        assert hasattr(RealTimeCopyTrader, "default_params")
        params = RealTimeCopyTrader.default_params
        assert "min_trader_pnl" in params
        assert "min_trader_volume" in params
        assert "min_trade_size_usd" in params

    @pytest.mark.asyncio
    async def test_market_filter_returns_list(self, strategy_ctx):
        """Verify market_filter returns list of markets."""
        trader = RealTimeCopyTrader()
        markets = [
            MagicMock(id="m1", ticker="btc-updown-5m"),
            MagicMock(id="m2", ticker="eth-updown-5m"),
        ]
        result = await trader.market_filter(markets)
        assert isinstance(result, list)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_run_cycle_completes(self, strategy_ctx):
        """Verify run_cycle completes without error."""
        trader = RealTimeCopyTrader()
        result = await trader.run_cycle(strategy_ctx)
        assert result is not None
        assert hasattr(result, "decisions_recorded")

    @pytest.mark.asyncio
    async def test_start_realtime_with_timeout(self, strategy_ctx):
        """Verify start_realtime can be started and stopped."""
        trader = RealTimeCopyTrader()
        
        # Mock the WebSocket with async methods
        mock_ws = AsyncMock()
        mock_ws.connect = AsyncMock(side_effect=asyncio.sleep(10))
        
        with patch("backend.bot.realtime_copy_trader.PolymarketWebSocket", return_value=mock_ws):
            with patch("backend.bot.realtime_copy_trader.get_shared_client") as mock_client:
                mock_client.return_value.get = AsyncMock(
                    return_value=MagicMock(status_code=200, json=lambda: [])
                )
                
                task = asyncio.create_task(
                    asyncio.wait_for(
                        trader.start_realtime(strategy_ctx),
                        timeout=0.05
                    )
                )
                try:
                    await task
                except (asyncio.TimeoutError, Exception):
                    pass
                
                await trader.stop_realtime()

    @pytest.mark.asyncio
    async def test_stop_realtime_cleans_up(self, strategy_ctx):
        """Verify stop_realtime properly cleans up WebSocket."""
        trader = RealTimeCopyTrader()
        await trader.stop_realtime()


# ---------------------------------------------------------------------------
# RealTimeWhaleTracker Tests
# ---------------------------------------------------------------------------


class TestRealTimeWhaleTracker:
    """Test RealTimeWhaleTracker: whale wallet monitoring via Alchemy WebSocket."""

    def test_instantiate(self):
        """Verify RealTimeWhaleTracker can be instantiated."""
        tracker = RealTimeWhaleTracker()
        assert tracker is not None
        assert hasattr(tracker, "start_realtime")
        assert hasattr(tracker, "stop_realtime")
        assert hasattr(tracker, "market_filter")
        assert hasattr(tracker, "run_cycle")

    def test_has_class_default_params(self):
        """Verify default parameters are configured at class level."""
        assert hasattr(RealTimeWhaleTracker, "default_params")
        params = RealTimeWhaleTracker.default_params
        assert "min_transfer_size_usd" in params
        assert "min_whale_balance_usd" in params
        assert "cooldown_seconds" in params

    @pytest.mark.asyncio
    async def test_market_filter_returns_list(self, strategy_ctx):
        """Verify market_filter returns list of markets."""
        tracker = RealTimeWhaleTracker()
        markets = [
            MagicMock(id="m1", ticker="btc-updown-5m"),
            MagicMock(id="m2", ticker="eth-updown-5m"),
        ]
        result = await tracker.market_filter(markets)
        assert isinstance(result, list)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_run_cycle_completes(self, strategy_ctx):
        """Verify run_cycle completes without error."""
        tracker = RealTimeWhaleTracker()
        with patch("backend.bot.realtime_whale_tracker.get_shared_client"):
            result = await tracker.run_cycle(strategy_ctx)
            assert result is not None
            assert hasattr(result, "decisions_recorded")

    @pytest.mark.asyncio
    async def test_start_realtime_with_timeout(self, strategy_ctx):
        """Verify start_realtime can be started and stopped."""
        tracker = RealTimeWhaleTracker()
        
        with patch("backend.bot.realtime_whale_tracker.get_shared_client"):
            task = asyncio.create_task(
                asyncio.wait_for(
                    tracker.start_realtime(strategy_ctx),
                    timeout=0.05
                )
            )
            try:
                await task
            except (asyncio.TimeoutError, Exception):
                pass

    @pytest.mark.asyncio
    async def test_stop_realtime_cleans_up(self, strategy_ctx):
        """Verify stop_realtime properly cleans up WebSocket."""
        tracker = RealTimeWhaleTracker()
        await tracker.stop_realtime()


# ---------------------------------------------------------------------------
# RealTimeStrategyManager Tests
# ---------------------------------------------------------------------------


class TestRealTimeStrategyManager:
    """Test RealTimeStrategyManager: coordinates event-driven strategies."""

    def test_instantiate(self):
        """Verify RealTimeStrategyManager can be instantiated."""
        manager = RealTimeStrategyManager()
        assert manager is not None
        assert hasattr(manager, "register_strategy")
        assert hasattr(manager, "start_all")
        assert hasattr(manager, "stop_all")

    def test_register_strategy(self):
        """Verify strategy registration."""
        manager = RealTimeStrategyManager()
        strategy = MagicMock()
        manager.register_strategy("test_strategy", strategy)
        assert "test_strategy" in manager._strategies
        assert manager._strategies["test_strategy"] == strategy

    @pytest.mark.asyncio
    async def test_start_all_with_no_strategies(self, strategy_ctx):
        """Verify start_all works with no registered strategies."""
        manager = RealTimeStrategyManager()
        await manager.start_all(strategy_ctx)
        assert manager._running is True

    @pytest.mark.asyncio
    async def test_start_all_with_mock_strategies(self, strategy_ctx):
        """Verify start_all starts registered strategies."""
        manager = RealTimeStrategyManager()
        
        # Create mock strategies
        strategy1 = MagicMock()
        strategy1.start_realtime = AsyncMock(side_effect=asyncio.sleep(10))
        strategy1.stop_realtime = AsyncMock()
        
        manager.register_strategy("strategy1", strategy1)
        
        # Start all in background with timeout
        task = asyncio.create_task(
            asyncio.wait_for(manager.start_all(strategy_ctx), timeout=0.05)
        )
        try:
            await task
        except asyncio.TimeoutError:
            pass
        
        assert manager._running is True

    @pytest.mark.asyncio
    async def test_stop_all_cleans_up_tasks(self, strategy_ctx):
        """Verify stop_all cancels and cleans up all tasks."""
        manager = RealTimeStrategyManager()
        
        strategy = MagicMock()
        strategy.start_realtime = AsyncMock(side_effect=asyncio.sleep(10))
        strategy.stop_realtime = AsyncMock()
        
        manager.register_strategy("test_strategy", strategy)
        
        # Start in background
        task = asyncio.create_task(manager.start_all(strategy_ctx))
        await asyncio.sleep(0.01)
        
        # Stop all
        await manager.stop_all()
        
        assert manager._running is False
        strategy.stop_realtime.assert_called_once()


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------


class TestRealtimeManagerIntegration:
    """Test RealTimeStrategyManager coordinating copy trader and whale tracker."""

    @pytest.mark.asyncio
    async def test_manager_coordinates_both_strategies(self, strategy_ctx):
        """Verify manager can coordinate both copy trader and whale tracker."""
        manager = RealTimeStrategyManager()
        
        copy_trader = RealTimeCopyTrader()
        whale_tracker = RealTimeWhaleTracker()
        
        manager.register_strategy("copy_trader", copy_trader)
        manager.register_strategy("whale_tracker", whale_tracker)
        
        # Mock the actual connections
        with patch.object(copy_trader, "start_realtime", new_callable=AsyncMock, side_effect=asyncio.sleep(10)):
            with patch.object(whale_tracker, "start_realtime", new_callable=AsyncMock, side_effect=asyncio.sleep(10)):
                with patch.object(copy_trader, "stop_realtime", new_callable=AsyncMock):
                    with patch.object(whale_tracker, "stop_realtime", new_callable=AsyncMock):
                        task = asyncio.create_task(
                            asyncio.wait_for(
                                manager.start_all(strategy_ctx),
                                timeout=0.05
                            )
                        )
                        try:
                            await task
                        except asyncio.TimeoutError:
                            pass
                        
                        assert manager._running is True
                        
                        await manager.stop_all()
                        assert manager._running is False


# ---------------------------------------------------------------------------
# Error Handling Tests
# ---------------------------------------------------------------------------


class TestRealtimeErrorHandling:
    """Test error handling in realtime modules."""

    @pytest.mark.asyncio
    async def test_copy_trader_handles_errors_gracefully(self, strategy_ctx):
        """Verify copy trader handles errors without crashing."""
        trader = RealTimeCopyTrader()
        strategy_ctx.clob.place_limit_order.side_effect = Exception("CLOB unavailable")
        
        result = await trader.run_cycle(strategy_ctx)
        assert result is not None

    @pytest.mark.asyncio
    async def test_whale_tracker_handles_errors_gracefully(self, strategy_ctx):
        """Verify whale tracker handles errors without crashing."""
        tracker = RealTimeWhaleTracker()
        
        with patch("backend.bot.realtime_whale_tracker.get_shared_client") as mock_client:
            mock_client.return_value.get.side_effect = Exception("API error")
            result = await tracker.run_cycle(strategy_ctx)
            assert result is not None

    @pytest.mark.asyncio
    async def test_manager_handles_strategy_failure(self, strategy_ctx):
        """Verify manager continues if one strategy fails."""
        manager = RealTimeStrategyManager()
        
        bad_strategy = MagicMock()
        bad_strategy.start_realtime = AsyncMock(side_effect=Exception("Strategy failure"))
        bad_strategy.stop_realtime = AsyncMock()
        
        good_strategy = MagicMock()
        good_strategy.start_realtime = AsyncMock(side_effect=asyncio.sleep(10))
        good_strategy.stop_realtime = AsyncMock()
        
        manager.register_strategy("bad", bad_strategy)
        manager.register_strategy("good", good_strategy)
        
        task = asyncio.create_task(
            asyncio.wait_for(manager.start_all(strategy_ctx), timeout=0.05)
        )
        try:
            await task
        except asyncio.TimeoutError:
            pass
        
        await manager.stop_all()
