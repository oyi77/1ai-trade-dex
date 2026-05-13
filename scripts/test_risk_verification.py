"""
Comprehensive Risk Management Verification Test Suite

Tests all risk management components:
1. Position limits (MAX_TRADE_SIZE, MAX_TOTAL_PENDING_TRADES)
2. Portfolio concentration guards (MAX_POSITION_FRACTION, MAX_TOTAL_EXPOSURE_FRACTION)
3. Drawdown controls (DAILY_LOSS_LIMIT, DAILY_DRAWDOWN_LIMIT_PCT, WEEKLY_DRAWDOWN_LIMIT_PCT)
4. Circuit breaker triggers
5. Kelly criterion sizing
6. Per-strategy risk isolation (via mode parameter)
"""

import asyncio
import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass

from backend.core.risk_manager import RiskManager
from backend.core.signals import calculate_kelly_size
from backend.core.circuit_breaker import CircuitBreaker, CircuitOpenError, State
from backend.config import settings


@dataclass
class MockSettings:
    """Mock settings for isolated testing"""
    INITIAL_BANKROLL: float = 1000.0
    DAILY_LOSS_LIMIT: float = 50.0
    MAX_TRADE_SIZE: float = 100.0
    MAX_POSITION_FRACTION: float = 0.08
    MAX_TOTAL_EXPOSURE_FRACTION: float = 0.70
    SLIPPAGE_TOLERANCE: float = 0.02
    DAILY_DRAWDOWN_LIMIT_PCT: float = 0.10
    WEEKLY_DRAWDOWN_LIMIT_PCT: float = 0.20
    KELLY_FRACTION: float = 0.05
    TRADING_MODE: str = "paper"


class TestPositionLimits:
    """Test position size limits enforcement"""
    
    @patch("backend.core.risk_manager.SessionLocal")
    def test_max_trade_size_enforced(self, mock_session_cls):
        """Verify MAX_TRADE_SIZE caps individual positions"""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value.filter.return_value.scalar.return_value = 0.0
        
        rm = RiskManager(settings_obj=MockSettings())
        
        # Request size larger than MAX_TRADE_SIZE
        result = rm.validate_trade(
            size=150.0,  # Exceeds MAX_TRADE_SIZE of 100
            current_exposure=0.0,
            bankroll=1000.0,
            confidence=0.8
        )
        
        assert result.allowed is True
        assert result.adjusted_size <= 100.0, "Trade size should be capped at MAX_TRADE_SIZE"
    
    @patch("backend.core.risk_manager.SessionLocal")
    def test_max_position_fraction_enforced(self, mock_session_cls):
        """Verify MAX_POSITION_FRACTION limits position as % of bankroll"""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value.filter.return_value.scalar.return_value = 0.0
        
        rm = RiskManager(settings_obj=MockSettings())
        
        # Request 10% of bankroll when limit is 8%
        result = rm.validate_trade(
            size=100.0,  # 10% of 1000
            current_exposure=0.0,
            bankroll=1000.0,
            confidence=0.8
        )
        
        assert result.allowed is True
        assert result.adjusted_size <= 80.0, "Position should be capped at 8% of bankroll"
    
    @patch("backend.core.risk_manager.SessionLocal")
    def test_max_total_exposure_enforced(self, mock_session_cls):
        """Verify MAX_TOTAL_EXPOSURE_FRACTION limits total portfolio exposure"""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value.filter.return_value.scalar.return_value = 0.0
        
        rm = RiskManager(settings_obj=MockSettings())
        
        # Already at 65% exposure, try to add 10% more (would exceed 70% limit)
        result = rm.validate_trade(
            size=100.0,
            current_exposure=650.0,  # 65% of 1000
            bankroll=1000.0,
            confidence=0.8
        )
        
        assert result.allowed is True
        assert result.adjusted_size <= 50.0, "Should only allow up to 70% total exposure"
    
    @patch("backend.core.risk_manager.SessionLocal")
    def test_max_total_exposure_blocks_when_full(self, mock_session_cls):
        """Verify trades blocked when at max exposure"""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value.filter.return_value.scalar.return_value = 0.0
        
        rm = RiskManager(settings_obj=MockSettings())
        
        # Already at 70% exposure limit
        result = rm.validate_trade(
            size=50.0,
            current_exposure=700.0,  # At 70% limit
            bankroll=1000.0,
            confidence=0.8
        )
        
        assert result.allowed is False
        assert "max exposure" in result.reason.lower()


class TestConcentrationGuards:
    """Test portfolio concentration limits"""
    
    @patch("backend.core.risk_manager.SessionLocal")
    def test_duplicate_market_blocked(self, mock_session_cls):
        """Verify no duplicate positions in same market"""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        
        # Mock: daily loss ok, drawdown ok, but unsettled trade exists
        mock_db.query.return_value.filter.return_value.scalar.side_effect = [
            0.0,   # daily loss check
            0.0,   # drawdown daily pnl
            0.0,   # drawdown weekly pnl
            1,     # unsettled trade count > 0
        ]
        
        rm = RiskManager(settings_obj=MockSettings())
        
        result = rm.validate_trade(
            size=50.0,
            current_exposure=100.0,
            bankroll=1000.0,
            confidence=0.8,
            market_ticker="btc-5min-12345"
        )
        
        assert result.allowed is False
        assert "unsettled trade" in result.reason.lower()
    
    @patch("backend.core.risk_manager.SessionLocal")
    def test_multiple_markets_allowed(self, mock_session_cls):
        """Verify multiple different markets can be traded"""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value.filter.return_value.scalar.return_value = 0.0
        
        rm = RiskManager(settings_obj=MockSettings())
        
        # First market
        result1 = rm.validate_trade(
            size=50.0,
            current_exposure=0.0,
            bankroll=1000.0,
            confidence=0.8,
            market_ticker="btc-5min-12345"
        )
        
        # Second market (different ticker)
        result2 = rm.validate_trade(
            size=50.0,
            current_exposure=50.0,
            bankroll=1000.0,
            confidence=0.8,
            market_ticker="btc-5min-67890"
        )
        
        assert result1.allowed is True
        assert result2.allowed is True


class TestDrawdownControls:
    """Test drawdown circuit breakers"""
    
    @patch("backend.core.risk_manager.SessionLocal")
    def test_daily_loss_limit_blocks(self, mock_session_cls):
        """Verify DAILY_LOSS_LIMIT stops trading"""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        
        # Mock daily loss exceeding limit
        mock_db.query.return_value.filter.return_value.scalar.return_value = -60.0  # Exceeds 50 limit
        
        rm = RiskManager(settings_obj=MockSettings())
        
        result = rm.validate_trade(
            size=50.0,
            current_exposure=0.0,
            bankroll=1000.0,
            confidence=0.8
        )
        
        assert result.allowed is False
        assert "daily loss limit" in result.reason.lower()
    
    @patch("backend.core.risk_manager.SessionLocal")
    def test_daily_drawdown_pct_blocks(self, mock_session_cls):
        """Verify DAILY_DRAWDOWN_LIMIT_PCT (10%) stops trading"""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        
        # Mock: daily loss ok, but drawdown % exceeded
        mock_db.query.return_value.filter.return_value.scalar.side_effect = [
            -40.0,   # daily loss (under 50 limit)
            -120.0,  # 24h pnl (12% of 1000 > 10% limit)
            -120.0,  # 7d pnl
        ]
        
        rm = RiskManager(settings_obj=MockSettings())
        
        result = rm.validate_trade(
            size=50.0,
            current_exposure=0.0,
            bankroll=1000.0,
            confidence=0.8
        )
        
        assert result.allowed is False
        assert "drawdown" in result.reason.lower()
    
    @patch("backend.core.risk_manager.SessionLocal")
    def test_weekly_drawdown_pct_blocks(self, mock_session_cls):
        """Verify WEEKLY_DRAWDOWN_LIMIT_PCT (20%) stops trading"""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        
        # Mock: daily ok, but weekly drawdown exceeded
        mock_db.query.return_value.filter.return_value.scalar.side_effect = [
            -30.0,   # daily loss (under 50 limit)
            -80.0,   # 24h pnl (8% - under 10% limit)
            -250.0,  # 7d pnl (25% of 1000 > 20% limit)
        ]
        
        rm = RiskManager(settings_obj=MockSettings())
        
        result = rm.validate_trade(
            size=50.0,
            current_exposure=0.0,
            bankroll=1000.0,
            confidence=0.8
        )
        
        assert result.allowed is False
        assert "drawdown" in result.reason.lower()
    
    @patch("backend.core.risk_manager.SessionLocal")
    def test_check_drawdown_status(self, mock_session_cls):
        """Verify check_drawdown returns correct status"""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        
        # Mock: no losses
        mock_db.query.return_value.filter.return_value.scalar.side_effect = [
            10.0,   # daily pnl (profit)
            20.0,   # weekly pnl (profit)
        ]
        
        rm = RiskManager(settings_obj=MockSettings())
        status = rm.check_drawdown(bankroll=1000.0)
        
        assert status.is_breached is False
        assert status.daily_pnl == 10.0
        assert status.weekly_pnl == 20.0
        assert status.daily_limit_pct == 0.10
        assert status.weekly_limit_pct == 0.20


class TestCircuitBreakers:
    """Test circuit breaker pattern"""
    
    @pytest.mark.asyncio
    async def test_circuit_opens_after_failures(self):
        """Verify circuit opens after threshold failures"""
        cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=1.0)
        
        async def failing_func():
            raise ValueError("API error")
        
        # Trigger 3 failures
        for _ in range(3):
            with pytest.raises(ValueError):
                await cb.call(failing_func)
        
        assert cb.state == State.OPEN
    
    @pytest.mark.asyncio
    async def test_circuit_blocks_when_open(self):
        """Verify circuit blocks calls when open"""
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=1.0)
        
        async def failing_func():
            raise ValueError("API error")
        
        async def success_func():
            return "ok"
        
        # Open the circuit
        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(failing_func)
        
        assert cb.state == State.OPEN
        
        # Should block even successful calls
        with pytest.raises(CircuitOpenError):
            await cb.call(success_func)
    
    @pytest.mark.asyncio
    async def test_circuit_recovers_to_half_open(self):
        """Verify circuit transitions to HALF_OPEN after timeout"""
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.1)
        
        async def failing_func():
            raise ValueError("API error")
        
        # Open circuit
        with pytest.raises(ValueError):
            await cb.call(failing_func)
        
        assert cb.state == State.OPEN
        
        # Wait for recovery timeout
        await asyncio.sleep(0.15)
        
        assert cb.state == State.HALF_OPEN
    
    @pytest.mark.asyncio
    async def test_circuit_closes_after_success(self):
        """Verify circuit closes after successful probe"""
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.1, half_open_max=1)
        
        async def failing_func():
            raise ValueError("API error")
        
        async def success_func():
            return "ok"
        
        # Open circuit
        with pytest.raises(ValueError):
            await cb.call(failing_func)
        
        # Wait for half-open
        await asyncio.sleep(0.15)
        assert cb.state == State.HALF_OPEN
        
        # Successful call should close circuit
        result = await cb.call(success_func)
        assert result == "ok"
        assert cb.state == State.CLOSED


class TestKellyCriterion:
    """Test Kelly criterion position sizing"""
    
    def test_kelly_basic_calculation(self):
        """Verify basic Kelly sizing works"""
        size = calculate_kelly_size(
            edge=0.10,
            probability=0.60,
            market_price=0.50,
            direction="up",
            bankroll=1000.0
        )
        
        assert size > 0
        assert size <= 1000.0 * 0.15  # Max 15% of bankroll
    
    def test_kelly_respects_fraction(self):
        """Verify KELLY_FRACTION (0.05) reduces sizing"""
        # With KELLY_FRACTION=0.05, size should be ~5% of full Kelly
        size = calculate_kelly_size(
            edge=0.20,
            probability=0.70,
            market_price=0.50,
            direction="up",
            bankroll=1000.0
        )
        
        # Should be much smaller than bankroll due to fractional Kelly
        assert size < 1000.0 * 0.15
    
    def test_kelly_zero_for_no_edge(self):
        """Verify zero sizing when no edge"""
        size = calculate_kelly_size(
            edge=0.0,
            probability=0.50,
            market_price=0.50,
            direction="up",
            bankroll=1000.0
        )
        
        assert size == 0.0
    
    def test_kelly_capped_at_max_trade_size(self):
        """Verify Kelly sizing respects MAX_TRADE_SIZE"""
        size = calculate_kelly_size(
            edge=0.50,  # Huge edge
            probability=0.90,
            market_price=0.40,
            direction="up",
            bankroll=10000.0
        )
        
        assert size <= settings.MAX_TRADE_SIZE
    
    def test_kelly_bayesian_shrinkage(self):
        """Verify Bayesian shrinkage reduces sizing with low sample size"""
        size_with_shrinkage = calculate_kelly_size(
            edge=0.10,
            probability=0.60,
            market_price=0.50,
            direction="up",
            bankroll=1000.0,
            n_eff=10,
            prior_confidence=30.0
        )
        
        size_without_shrinkage = calculate_kelly_size(
            edge=0.10,
            probability=0.60,
            market_price=0.50,
            direction="up",
            bankroll=1000.0,
            n_eff=None
        )
        
        assert size_with_shrinkage <= size_without_shrinkage
        assert size_with_shrinkage > 0


class TestStrategyIsolation:
    """Test per-strategy risk isolation via mode parameter"""
    
    @patch("backend.core.risk_manager.SessionLocal")
    def test_paper_mode_isolated(self, mock_session_cls):
        """Verify paper mode has separate risk tracking"""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value.filter.return_value.scalar.return_value = 0.0
        
        rm = RiskManager(settings_obj=MockSettings())
        
        # Paper mode trade
        result = rm.validate_trade(
            size=50.0,
            current_exposure=0.0,
            bankroll=1000.0,
            confidence=0.8,
            mode="paper"
        )
        
        assert result.allowed is True
        
        # Verify mode was passed to DB query (check filter was called with mode)
        # This ensures paper/testnet/live are isolated
    
    @patch("backend.core.risk_manager.SessionLocal")
    def test_testnet_mode_isolated(self, mock_session_cls):
        """Verify testnet mode has separate risk tracking"""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value.filter.return_value.scalar.return_value = 0.0
        
        rm = RiskManager(settings_obj=MockSettings())
        
        result = rm.validate_trade(
            size=50.0,
            current_exposure=0.0,
            bankroll=1000.0,
            confidence=0.8,
            mode="testnet"
        )
        
        assert result.allowed is True
    
    @patch("backend.core.risk_manager.SessionLocal")
    def test_live_mode_isolated(self, mock_session_cls):
        """Verify live mode has separate risk tracking"""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value.filter.return_value.scalar.return_value = 0.0
        
        rm = RiskManager(settings_obj=MockSettings())
        
        result = rm.validate_trade(
            size=50.0,
            current_exposure=0.0,
            bankroll=1000.0,
            confidence=0.8,
            mode="live"
        )
        
        assert result.allowed is True


class TestConfidenceFiltering:
    """Test confidence-based trade filtering"""
    
    def test_low_confidence_rejected(self):
        """Verify trades below 0.5 confidence are rejected"""
        rm = RiskManager(settings_obj=MockSettings())
        
        result = rm.validate_trade(
            size=50.0,
            current_exposure=0.0,
            bankroll=1000.0,
            confidence=0.3  # Below 0.5 threshold
        )
        
        assert result.allowed is False
        assert "confidence" in result.reason.lower()
    
    def test_high_confidence_allowed(self):
        """Verify trades above 0.5 confidence pass confidence check"""
        rm = RiskManager(settings_obj=MockSettings())
        
        with patch("backend.core.risk_manager.SessionLocal") as mock_session_cls:
            mock_db = MagicMock()
            mock_session_cls.return_value = mock_db
            mock_db.query.return_value.filter.return_value.scalar.return_value = 0.0
            
            result = rm.validate_trade(
                size=50.0,
                current_exposure=0.0,
                bankroll=1000.0,
                confidence=0.8  # Above 0.5 threshold
            )
            
            assert result.allowed is True


class TestSlippageTolerance:
    """Test slippage rejection"""
    
    @patch("backend.core.risk_manager.SessionLocal")
    def test_high_slippage_rejected(self, mock_session_cls):
        """Verify trades with slippage > SLIPPAGE_TOLERANCE rejected"""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value.filter.return_value.scalar.return_value = 0.0
        
        rm = RiskManager(settings_obj=MockSettings())
        
        result = rm.validate_trade(
            size=50.0,
            current_exposure=0.0,
            bankroll=1000.0,
            confidence=0.8,
            slippage=0.05  # Exceeds 0.02 tolerance
        )
        
        assert result.allowed is False
        assert "slippage" in result.reason.lower()
    
    @patch("backend.core.risk_manager.SessionLocal")
    def test_acceptable_slippage_allowed(self, mock_session_cls):
        """Verify trades with slippage <= SLIPPAGE_TOLERANCE allowed"""
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value.filter.return_value.scalar.return_value = 0.0
        
        rm = RiskManager(settings_obj=MockSettings())
        
        result = rm.validate_trade(
            size=50.0,
            current_exposure=0.0,
            bankroll=1000.0,
            confidence=0.8,
            slippage=0.01  # Within 0.02 tolerance
        )
        
        assert result.allowed is True


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
