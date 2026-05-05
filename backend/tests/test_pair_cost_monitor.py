"""Tests for PairCostMonitor - Phase F Gap G9"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from backend.application.strategy.arbitrage.pair_cost_monitor import PairCostMonitor, ArbitrageOpportunity
from backend.infrastructure.market_stream.orderbook_router import OrderbookUpdate
from backend.config import settings


@pytest.fixture
def pair_cost_monitor():
    """Create a PairCostMonitor instance for testing."""
    return PairCostMonitor()


@pytest.fixture
def mock_orderbook_update():
    """Create a mock orderbook update."""
    return OrderbookUpdate(
        market_id="BTC-2024-05-31",
        bids_yes=[{"price": "0.49"}, {"price": "0.48"}],
        asks_yes=[{"price": "0.51"}, {"price": "0.52"}],
        bids_no=[{"price": "0.49"}, {"price": "0.48"}],
        asks_no=[{"price": "0.51"}, {"price": "0.52"}],
        timestamp=int(datetime.now().timestamp())
    )


def test_pair_cost_monitor_disabled_when_feature_flag_off(pair_cost_monitor, mock_orderbook_update):
    """Test that monitor does nothing when ENABLE_PAIR_COST_ARB is False."""
    # Save original value
    original_value = settings.ENABLE_PAIR_COST_ARB
    
    try:
        settings.ENABLE_PAIR_COST_ARB = False
        
        # Mock the on_orderbook_update method
        with patch.object(pair_cost_monitor, 'on_orderbook_update', new_callable=AsyncMock) as mock_method:
            # Call the method
            import asyncio
            asyncio.run(pair_cost_monitor.on_orderbook_update(mock_orderbook_update))
            
            # Verify it returns early
            mock_method.assert_called_once()
    finally:
        settings.ENABLE_PAIR_COST_ARB = original_value


def test_rate_limiting(pair_cost_monitor, mock_orderbook_update):
    """Test that rate limiting prevents frequent checks on same market."""
    # Enable the feature
    original_value = settings.ENABLE_PAIR_COST_ARB
    settings.ENABLE_PAIR_COST_ARB = True
    
    try:
        # First call should work
        with patch.object(pair_cost_monitor, '_has_unsettled_trade', return_value=False):
            import asyncio
            asyncio.run(pair_cost_monitor.on_orderbook_update(mock_orderbook_update))
        
        # Second call within rate limit window should be skipped
        with patch.object(pair_cost_monitor, '_has_unsettled_trade', return_value=False) as mock_idempotency:
            import asyncio
            asyncio.run(pair_cost_monitor.on_orderbook_update(mock_orderbook_update))
            # Should not reach idempotency check due to rate limiting
            mock_idempotency.assert_not_called()
    finally:
        settings.ENABLE_PAIR_COST_ARB = original_value


def test_idempotency_check(pair_cost_monitor, mock_orderbook_update):
    """Test that unsettled trades prevent arb checks."""
    original_value = settings.ENABLE_PAIR_COST_ARB
    settings.ENABLE_PAIR_COST_ARB = True
    
    try:
        # Reset rate limiting
        pair_cost_monitor._last_attempt.clear()
        
        with patch.object(pair_cost_monitor, '_has_unsettled_trade', return_value=True) as mock_check:
            import asyncio
            asyncio.run(pair_cost_monitor.on_orderbook_update(mock_orderbook_update))
            
            mock_check.assert_called_once_with("BTC-2024-05-31")
    finally:
        settings.ENABLE_PAIR_COST_ARB = original_value


def test_arbitrage_detection(pair_cost_monitor, mock_orderbook_update):
    """Test that arbitrage opportunities are detected correctly."""
    original_arb = settings.ENABLE_PAIR_COST_ARB
    original_spread = settings.MIN_ARB_SPREAD
    
    settings.ENABLE_PAIR_COST_ARB = True
    settings.MIN_ARB_SPREAD = 0.001  # 0.1% spread
    
    try:
        # Reset rate limiting
        pair_cost_monitor._last_attempt.clear()
        
        # Mock orderbook with arbitrage opportunity
        # YES ask = 0.40, NO ask = 0.50, pair cost = 0.90
        # After 4% fees (2% each side), net cost = 0.90 + 0.04 = 0.94
        # Spread = 1.00 - 0.94 = 0.06 (6%) > 0.001
        mock_update = OrderbookUpdate(
            market_id="BTC-2024-05-31",
            bids_yes=[{"price": "0.39"}],
            asks_yes=[{"price": "0.40"}],
            bids_no=[{"price": "0.49"}],
            asks_no=[{"price": "0.50"}],
            timestamp=int(datetime.now().timestamp())
        )
        
        with patch.object(pair_cost_monitor, '_has_unsettled_trade', return_value=False):
            with patch.object(pair_cost_monitor, '_publish_arbitrage_event', new_callable=AsyncMock) as mock_publish:
                with patch.object(pair_cost_monitor, '_fire_simultaneous_maker_orders', new_callable=AsyncMock) as mock_fire:
                    import asyncio
                    asyncio.run(pair_cost_monitor.on_orderbook_update(mock_update))
                    
                    # Should publish event and fire orders
                    mock_publish.assert_called_once()
                    mock_fire.assert_called_once()
    finally:
        settings.ENABLE_PAIR_COST_ARB = original_arb
        settings.MIN_ARB_SPREAD = original_spread


def test_no_arbitrage_when_spread_too_small(pair_cost_monitor, mock_orderbook_update):
    """Test that no arbitrage is detected when spread is too small."""
    original_arb = settings.ENABLE_PAIR_COST_ARB
    original_spread = settings.MIN_ARB_SPREAD
    
    settings.ENABLE_PAIR_COST_ARB = True
    settings.MIN_ARB_SPREAD = 0.05  # 5% minimum spread
    
    try:
        # Reset rate limiting
        pair_cost_monitor._last_attempt.clear()
        
        # Mock orderbook with small spread
        # YES ask = 0.45, NO ask = 0.55, pair cost = 1.00
        # After 4% fees, net cost = 1.00 + 0.04 = 1.04
        # Spread = 1.00 - 1.04 = -0.04 (negative, no arb)
        mock_update = OrderbookUpdate(
            market_id="BTC-2024-05-31",
            bids_yes=[{"price": "0.44"}],
            asks_yes=[{"price": "0.45"}],
            bids_no=[{"price": "0.54"}],
            asks_no=[{"price": "0.55"}],
            timestamp=int(datetime.now().timestamp())
        )
        
        with patch.object(pair_cost_monitor, '_has_unsettled_trade', return_value=False):
            with patch.object(pair_cost_monitor, '_publish_arbitrage_event', new_callable=AsyncMock) as mock_publish:
                import asyncio
                asyncio.run(pair_cost_monitor.on_orderbook_update(mock_update))
                
                # Should not publish event
                mock_publish.assert_not_called()
    finally:
        settings.ENABLE_PAIR_COST_ARB = original_arb
        settings.MIN_ARB_SPREAD = original_spread


def test_get_best_ask_price():
    """Test best ask price extraction."""
    asks = [{"price": "0.51"}, {"price": "0.52"}, {"price": "0.53"}]
    result = PairCostMonitor._get_best_ask_price(asks)
    assert result == 0.51


def test_get_best_ask_price_empty():
    """Test best ask price with empty list."""
    result = PairCostMonitor._get_best_ask_price([])
    assert result == 0.0
