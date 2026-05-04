import json
from unittest.mock import MagicMock
from dataclasses import dataclass

from backend.core.risk_manager import RiskManager


@dataclass
class MockSettings:
    INITIAL_BANKROLL: float = 1000.0
    DAILY_LOSS_LIMIT: float = 300.0
    MAX_POSITION_FRACTION: float = 0.05
    MAX_TOTAL_EXPOSURE_FRACTION: float = 0.50
    SLIPPAGE_TOLERANCE: float = 0.02
    DAILY_DRAWDOWN_LIMIT_PCT: float = 0.10
    WEEKLY_DRAWDOWN_LIMIT_PCT: float = 0.20
    TRADING_MODE: str = "paper"
    AUTO_APPROVE_MIN_CONFIDENCE: float = 0.50
    MIN_ORDER_USDC: float = 5.0
    PAPER_MIN_ORDER_USDC: float = 1.0
    DRAWDOWN_BREAKER_ENABLED_PER_MODE: dict = None
    DAILY_LOSS_LIMIT_ENABLED_PER_MODE: dict = None
    AGI_BANKROLL_ALLOCATION_ENABLED: bool = False

    def __post_init__(self):
        if self.DRAWDOWN_BREAKER_ENABLED_PER_MODE is None:
            self.DRAWDOWN_BREAKER_ENABLED_PER_MODE = {
                "paper": True,
                "testnet": True,
                "live": True,
            }
        if self.DAILY_LOSS_LIMIT_ENABLED_PER_MODE is None:
            self.DAILY_LOSS_LIMIT_ENABLED_PER_MODE = {
                "paper": True,
                "testnet": True,
                "live": True,
            }


class TestStrategyAllocation:
    """Tests for strategy allocation functionality (Task 9)."""
    
    def test_allocation_fallback_equal_weight(self):
        """Test equal-weight fallback when no AGI allocation exists."""
        s = MockSettings()
        s.AGI_BANKROLL_ALLOCATION_ENABLED = False  # Force fallback
        s.MAX_POSITION_FRACTION = 0.25
        s.MAX_TOTAL_EXPOSURE_FRACTION = 0.70
        
        rm = RiskManager(settings_obj=s)
        
        # Mock database with 4 enabled strategies
        mock_db = MagicMock()
        mock_strategy_query = MagicMock()
        mock_strategy_query.filter.return_value.count.return_value = 4
        mock_db.query.return_value = mock_strategy_query
        
        bankroll = 10000.0
        allocation = rm._get_strategy_allocation("BTC Momentum", bankroll, mock_db)
        
        # Expected: (10000 * 0.70) / 4 = 1750, capped at 10000 * 0.25 = 2500, so 1750
        expected = 1750.0
        assert allocation == expected
        
    def test_allocation_fallback_zero_strategies(self):
        """Test fallback when no strategies are enabled."""
        s = MockSettings()
        s.AGI_BANKROLL_ALLOCATION_ENABLED = False
        s.MAX_POSITION_FRACTION = 0.25
        
        rm = RiskManager(settings_obj=s)
        
        # Mock database with 0 enabled strategies
        mock_db = MagicMock()
        mock_strategy_query = MagicMock()
        mock_strategy_query.filter.return_value.count.return_value = 0
        mock_db.query.return_value = mock_strategy_query
        
        bankroll = 10000.0
        allocation = rm._get_strategy_allocation("BTC Momentum", bankroll, mock_db)
        
        # Expected: bankroll * MAX_POSITION_FRACTION = 10000 * 0.25 = 2500
        expected = 2500.0
        assert allocation == expected
        
    def test_allocation_agi_enabled_with_allocation(self):
        """Test AGI allocation when available."""
        s = MockSettings()
        s.AGI_BANKROLL_ALLOCATION_ENABLED = True
        s.MAX_POSITION_FRACTION = 0.25
        
        rm = RiskManager(settings_obj=s)
        
        # Mock database with BotState containing AGI allocation
        mock_bot_state = MagicMock()
        mock_bot_state.misc_data = json.dumps({
            "allocations": {
                "BTC Momentum": 500.0,
                "Market Maker": 1500.0
            }
        })
        
        mock_db = MagicMock()
        mock_db.query.return_value.first.return_value = mock_bot_state
        
        bankroll = 10000.0
        allocation = rm._get_strategy_allocation("BTC Momentum", bankroll, mock_db)
        
        # Expected: 500.0 (AGI allocation), capped at 10000 * 0.25 = 2500, so 500
        expected = 500.0
        assert allocation == expected
        
    def test_allocation_agi_enabled_no_allocation(self):
        """Test fallback to equal-weight when AGI enabled but no allocation exists."""
        s = MockSettings()
        s.AGI_BANKROLL_ALLOCATION_ENABLED = True
        s.MAX_POSITION_FRACTION = 0.25
        s.MAX_TOTAL_EXPOSURE_FRACTION = 0.70
        
        rm = RiskManager(settings_obj=s)
        
        # Mock database with BotState but no allocation for this strategy
        mock_bot_state = MagicMock()
        mock_bot_state.misc_data = json.dumps({
            "allocations": {
                "Market Maker": 1500.0  # But not BTC Momentum
            }
        })
        
        mock_db = MagicMock()
        
        # Mock for BotState query (first call)
        mock_bot_state_query = MagicMock()
        mock_bot_state_query.first.return_value = mock_bot_state
        
        # Mock for StrategyConfig query (second call)
        mock_strategy_query = MagicMock()
        mock_strategy_query.filter.return_value.count.return_value = 3  # 3 enabled strategies
        
        # Set up side effect to return different mocks for different queries
        mock_db.query.side_effect = [mock_bot_state_query, mock_strategy_query]
        
        bankroll = 10000.0
        allocation = rm._get_strategy_allocation("BTC Momentum", bankroll, mock_db)
        
        # Expected: fallback to equal-weight = (10000 * 0.70) / 3 ≈ 2333.33, capped at 2500
        expected = min(2333.33, 2500.0)
        assert abs(allocation - expected) < 0.01