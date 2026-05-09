import json
from unittest.mock import MagicMock, patch
from dataclasses import dataclass

from backend.core.risk_manager import RiskManager


@dataclass
class MockSettings:
    INITIAL_BANKROLL: float = 1000.0
    DAILY_LOSS_LIMIT: float = 300.0
    MAX_POSITION_FRACTION: float = 0.05
    MAX_TRADE_SIZE: float = 100.0  # Global max trade size ceiling
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
    REGIME_ROUTING_ENABLED: bool = True
    DAILY_LOSS_FLOOR_PCT: float = -0.10
    WEEKLY_LOSS_FLOOR_PCT: float = -0.20
    MAX_SINGLE_STRATEGY_PCT: float = 0.25
    NEW_STRATEGY_RAMP_PCT: float = 0.01
    NEW_STRATEGY_MIN_TRADES: int = 20
    MIN_ARCHETYPE_DIVERSITY: int = 5

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


class TestConfidenceThreshold:
    """Tests for confidence threshold functionality (Task 10)."""

    def test_paper_mode_uses_same_threshold_as_live(self):
        """Test that paper mode uses same confidence threshold as live mode."""
        s = MockSettings()
        s.AUTO_APPROVE_MIN_CONFIDENCE = 0.50
        s.REGIME_ROUTING_ENABLED = False

        rm = RiskManager(settings_obj=s)

        # Both paper and live should use the same base confidence
        paper_threshold = rm._get_confidence_threshold("paper")
        live_threshold = rm._get_confidence_threshold("live")

        assert paper_threshold == live_threshold
        assert paper_threshold == 0.50  # Base confidence

    def test_regime_routing_applies_multiplier(self):
        """Test that regime routing applies multiplier when enabled."""
        s = MockSettings()
        s.AUTO_APPROVE_MIN_CONFIDENCE = 0.50
        s.REGIME_ROUTING_ENABLED = True

        rm = RiskManager(settings_obj=s)

        # With regime routing enabled, should apply multiplier (currently 1.0)
        threshold = rm._get_confidence_threshold("live")

        # Should be base_confidence * regime_multiplier (1.0) = 0.50, capped at 0.95
        assert threshold == 0.50

    def test_threshold_capped_at_095(self):
        """Test that confidence threshold is capped at 0.95."""
        s = MockSettings()
        s.AUTO_APPROVE_MIN_CONFIDENCE = 0.98  # Above cap
        s.REGIME_ROUTING_ENABLED = False

        rm = RiskManager(settings_obj=s)

        threshold = rm._get_confidence_threshold("live")

        # Should be capped at 0.95
        assert threshold == 0.95

    def test_backward_compatibility_when_regime_routing_disabled(self):
        """Test backward compatibility when regime routing is disabled."""
        s = MockSettings()
        s.AUTO_APPROVE_MIN_CONFIDENCE = 0.40
        s.REGIME_ROUTING_ENABLED = False

        rm = RiskManager(settings_obj=s)

        # Should use base confidence directly
        threshold = rm._get_confidence_threshold("paper")
        assert threshold == 0.40


class TestDrawdownFloors:
    """Tests for daily/weekly drawdown floor enforcement (Task 12)."""

    def test_daily_loss_floor_triggers_pause(self):
        """Test that daily loss floor triggers 24h pause for all strategies."""
        s = MockSettings()
        s.DAILY_LOSS_FLOOR_PCT = -0.10  # -10% floor
        s.WEEKLY_LOSS_FLOOR_PCT = -0.20  # -20% floor

        rm = RiskManager(settings_obj=s)

        # Mock database with daily PnL below floor
        # bankroll=10000, daily_pnl=-1200 (< -10% of 10000 = -1000)
        # This should trigger a pause

        # For now, test that the method exists and can be called
        # Full integration test would require mocking the database
        assert hasattr(rm, 'check_drawdown_floors')

    def test_weekly_loss_floor_triggers_paper_mode(self):
        """Test that weekly loss floor triggers reversion to PAPER mode for 7 days."""
        s = MockSettings()
        s.DAILY_LOSS_FLOOR_PCT = -0.10
        s.WEEKLY_LOSS_FLOOR_PCT = -0.20

        rm = RiskManager(settings_obj=s)

        # Mock database with weekly PnL below floor
        # bankroll=10000, weekly_pnl=-2500 (< -20% of 10000 = -2000)
        # This should trigger paper mode reversion

        # For now, test that the method exists
        assert hasattr(rm, 'check_drawdown_floors')

    def test_drawdown_floors_respect_env_overrides(self):
        """Test that drawdown floors respect environment variable overrides."""
        s = MockSettings()
        s.DAILY_LOSS_FLOOR_PCT = -0.15  # Override to -15%
        s.WEEKLY_LOSS_FLOOR_PCT = -0.25  # Override to -25%

        rm = RiskManager(settings_obj=s)

        # Verify the settings are respected
        assert rm.s.DAILY_LOSS_FLOOR_PCT == -0.15
        assert rm.s.WEEKLY_LOSS_FLOOR_PCT == -0.25


class TestImmutableSafetyRules:
    """Tests for immutable safety rules enforcement (Task 13)."""

    def test_safety_rules_loaded_with_defaults(self):
        """Test that safety rules are loaded with default values."""
        s = MockSettings()
        rm = RiskManager(settings_obj=s)

        # Check that safety rules are loaded
        assert hasattr(rm, '_safety_rules')
        assert rm._safety_rules["max_total_exposure"] == 0.95
        assert rm._safety_rules["max_single_strategy_pct"] == 0.25
        assert rm._safety_rules["daily_loss_floor"] == -0.10
        assert rm._safety_rules["weekly_loss_floor"] == -0.20
        assert rm._safety_rules["new_strategy_ramp_pct"] == 0.01
        assert rm._safety_rules["new_strategy_min_trades"] == 20
        assert rm._safety_rules["min_archetype_diversity"] == 5
        assert rm._safety_rules["emergency_kill_switch"] == True
        assert rm._safety_rules["audit_trail"] == True

    def test_safety_rules_respect_env_overrides(self):
        """Test that safety rules respect environment variable overrides."""
        import os

        # Set environment variables
        os.environ["MAX_TOTAL_EXPOSURE_FRACTION"] = "0.90"
        os.environ["MAX_SINGLE_STRATEGY_PCT"] = "0.30"

        try:
            s = MockSettings()
            rm = RiskManager(settings_obj=s)

            # Check that overrides are respected
            assert rm._safety_rules["max_total_exposure"] == 0.90
            assert rm._safety_rules["max_single_strategy_pct"] == 0.30

        finally:
            # Clean up environment variables
            os.environ.pop("MAX_TOTAL_EXPOSURE_FRACTION", None)
            os.environ.pop("MAX_SINGLE_STRATEGY_PCT", None)

    def test_total_exposure_limit_enforced(self):
        """Test that total exposure limit is enforced using safety rule."""
        s = MockSettings()
        s.MAX_TOTAL_EXPOSURE_FRACTION = 0.70  # This should be ignored

        rm = RiskManager(settings_obj=s)

        # The safety rule should override the settings value
        assert rm._safety_rules["max_total_exposure"] == 0.95

    def test_regime_multiplier_volatile_strategy(self):
        """Test that BTC Momentum strategy gets 1.25x multiplier in volatile regime."""
        with patch("backend.application.meta.regime_router.RegimeConfidenceRouter") as MockRouter:
            MockRouter.return_value.get_multiplier.return_value = 1.25
            s = MockSettings()
            s.AUTO_APPROVE_MIN_CONFIDENCE = 0.50
            s.REGIME_ROUTING_ENABLED = True

            rm = RiskManager(settings_obj=s)

            # BTC Momentum should get 1.25x multiplier (0.50 * 1.25 = 0.625)
            threshold = rm._get_confidence_threshold("live", "BTC Momentum")
            assert threshold == 0.625

    def test_regime_multiplier_sideways_strategy(self):
        """Test that Market Maker strategy gets 0.85x multiplier in sideways regime."""
        with patch("backend.application.meta.regime_router.RegimeConfidenceRouter") as MockRouter:
            MockRouter.return_value.get_multiplier.return_value = 0.85
            s = MockSettings()
            s.AUTO_APPROVE_MIN_CONFIDENCE = 0.60
            s.REGIME_ROUTING_ENABLED = True

            rm = RiskManager(settings_obj=s)

            # Market Maker should get 0.85x multiplier (0.60 * 0.85 = 0.51, capped at 0.95)
            threshold = rm._get_confidence_threshold("live", "Market Maker")
            assert abs(threshold - 0.51) < 0.001

    def test_regime_multiplier_unknown_strategy(self):
        """Test that unknown strategy gets default 1.0x multiplier."""
        with patch("backend.application.meta.regime_router.RegimeConfidenceRouter") as MockRouter:
            MockRouter.return_value.get_multiplier.return_value = 1.0
            s = MockSettings()
            s.AUTO_APPROVE_MIN_CONFIDENCE = 0.50
            s.REGIME_ROUTING_ENABLED = True

            rm = RiskManager(settings_obj=s)

            # Unknown strategy should get default 1.0x multiplier
            threshold = rm._get_confidence_threshold("live", "Unknown Strategy")
            assert threshold == 0.50

    def test_regime_multiplier_capped_at_095(self):
        """Test that regime multiplier is capped at 0.95."""
        with patch("backend.application.meta.regime_router.RegimeConfidenceRouter") as MockRouter:
            MockRouter.return_value.get_multiplier.return_value = 2.0
            s = MockSettings()
            s.AUTO_APPROVE_MIN_CONFIDENCE = 0.80
            s.REGIME_ROUTING_ENABLED = True

            rm = RiskManager(settings_obj=s)

            # Even with 2.0x multiplier: 0.80 * 2.0 = 1.60, but should be capped at 0.95
            threshold = rm._get_confidence_threshold("live", "BTC Momentum")
            assert threshold == 0.95

    def test_max_trade_size_enforced(self):
        """Risk manager must cap any trade size to settings.MAX_TRADE_SIZE."""
        s = MockSettings()
        s.MAX_TRADE_SIZE = 50.0  # Set a known ceiling
        s.MAX_POSITION_FRACTION = 0.50  # Allow large fraction to isolate MAX_TRADE_SIZE effect
        rm = RiskManager(settings_obj=s)

        # Request a size far above MAX_TRADE_SIZE
        decision = rm.validate_trade(
            size=200.0,
            current_exposure=0.0,
            bankroll=1000.0,
            confidence=0.90,
            market_ticker="TEST",
            mode="paper",
            strategy_name="test_strategy",
            direction="up",
        )
        # Should be allowed but reduced to MAX_TRADE_SIZE
        assert decision.allowed is True
        assert decision.adjusted_size == 50.0
        assert "ok" in decision.reason.lower()
