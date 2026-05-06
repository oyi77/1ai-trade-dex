import pytest
from unittest.mock import MagicMock, AsyncMock
from backend.core.auto_trader import AutoTrader
from backend.core.risk_manager import RiskDecision


@pytest.fixture
def rm_allow():
    rm = MagicMock()
    rm.validate_trade.return_value = RiskDecision(True, "ok", 100.0)
    return rm


@pytest.fixture
def rm_reject():
    rm = MagicMock()
    rm.validate_trade.return_value = RiskDecision(False, "rejected", 0.0)
    return rm


@pytest.mark.asyncio
async def test_auto_execute_high_confidence(rm_allow, monkeypatch):
    from backend.config import settings
    monkeypatch.setattr(settings, "ACTIVE_MODES", "paper")
    monkeypatch.setattr(settings, "AUTO_APPROVE_MIN_CONFIDENCE", 0.85)
    trader = AutoTrader(rm_allow)
    result = await trader.execute_signal(
        {"confidence": 0.9, "size": 100, "market_id": "m1", "side": "BUY"},
        bankroll=10000, current_exposure=0, mode="paper"
    )
    assert result.executed
    assert not result.pending_approval


@pytest.mark.asyncio
async def test_low_confidence_skips_in_auto_mode(rm_allow, monkeypatch):
    """Low confidence in non-manual mode must skip (not queue) to prevent auto-approve bypassing."""
    from backend.config import settings
    monkeypatch.setattr(settings, "AUTO_APPROVE_MIN_CONFIDENCE", 0.85)
    monkeypatch.setattr(settings, "SIGNAL_APPROVAL_MODE", "auto_approve")
    trader = AutoTrader(rm_allow)
    result = await trader.execute_signal(
        {"confidence": 0.6, "size": 100, "market_id": "m1", "side": "BUY"},
        bankroll=10000, current_exposure=0,
    )
    assert not result.executed
    assert not result.pending_approval  # must skip, not queue


@pytest.mark.asyncio
async def test_low_confidence_queues_in_manual_mode(rm_allow, monkeypatch):
    """Low confidence in manual mode must queue for human review."""
    from backend.config import settings
    monkeypatch.setattr(settings, "AUTO_APPROVE_MIN_CONFIDENCE", 0.85)
    monkeypatch.setattr(settings, "SIGNAL_APPROVAL_MODE", "manual")
    trader = AutoTrader(rm_allow)
    result = await trader.execute_signal(
        {"confidence": 0.6, "size": 100, "market_id": "m1", "side": "BUY"},
        bankroll=10000, current_exposure=0,
    )
    assert not result.executed
    assert result.pending_approval


@pytest.mark.asyncio
async def test_risk_rejection(rm_reject):
    trader = AutoTrader(rm_reject)
    result = await trader.execute_signal(
        {"confidence": 0.6, "size": 100, "market_id": "m1", "side": "BUY"},
        bankroll=10000, current_exposure=0, mode="paper"
    )
    assert not result.executed
    assert not result.pending_approval
    assert "rejected" in result.reason
