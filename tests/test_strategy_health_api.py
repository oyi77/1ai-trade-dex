import sys
from unittest.mock import MagicMock
sys.modules.setdefault("apscheduler.events", MagicMock())
sys.modules.setdefault("apscheduler.triggers", MagicMock())
sys.modules.setdefault("apscheduler.triggers.interval", MagicMock())

import pytest
import json
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone

from backend.models.database import BotState, StrategyConfig, Signal, TradeAttempt, Trade
from backend.models.outcome_tables import StrategyHealthRecord
from backend.core.heartbeat import update_scan_stats, _flush_heartbeats
from backend.core.scheduling.scheduling_strategies import strategy_cycle_job


@pytest.fixture(autouse=True)
def setup_bot_states(db_session):
    """Ensure BotState records exist in the DB for the test."""
    from backend.config import settings
    for mode in ["paper", "testnet", "live"]:
        state = db_session.query(BotState).filter_by(mode=mode).first()
        if not state:
            initial_bankroll = settings.INITIAL_BANKROLL if mode != "testnet" else 100.0
            db_session.add(
                BotState(
                    mode=mode,
                    bankroll=initial_bankroll,
                    total_trades=0,
                    winning_trades=0,
                    total_pnl=0.0,
                    is_running=True,
                )
            )
    db_session.commit()


def test_update_and_flush_scan_stats(db_session):
    # Ensure BotState for paper exists (should be seeded)
    state = db_session.query(BotState).filter_by(mode="paper").first()
    assert state is not None

    # Update scan stats in memory
    update_scan_stats(
        strategy_name="btc_oracle",
        mode="paper",
        markets_scanned=15,
        signals_had_edge=4,
        signals_rejected=1,
        trades_executed=3,
    )

    # Flush heartbeats
    success = _flush_heartbeats()
    assert success is True

    # Reload BotState and check misc_data
    db_session.refresh(state)
    assert state.misc_data is not None
    misc = json.loads(state.misc_data)
    
    assert "scan_stats:btc_oracle" in misc
    stats = misc["scan_stats:btc_oracle"]
    assert stats["markets_scanned"] == 15
    assert stats["signals_had_edge"] == 4
    assert stats["signals_rejected"] == 1
    assert stats["trades_executed"] == 3
    assert "last_scan_time" in stats


def test_strategies_health_api_endpoint(test_app, db_session):
    # Override admin requirement
    from backend.api.auth import require_admin
    from backend.api.main import app
    app.dependency_overrides[require_admin] = lambda: None

    # Setup database configs and data
    cfg = StrategyConfig(strategy_name="btc_oracle", enabled=True, trading_mode="paper")
    db_session.add(cfg)
    
    # Add a mock Signal
    sig = Signal(
        market_ticker="BTC-20260526-UP",
        platform="polymarket",
        market_type="btc",
        direction="up",
        model_probability=0.65,
        market_price=0.55,
        edge=0.10,
        confidence=0.8,
        track_name="btc_oracle",
        execution_mode="paper",
        reasoning="Test signal",
    )
    db_session.add(sig)

    # Add a mock TradeAttempt (rejection)
    attempt = TradeAttempt(
        attempt_id="test-attempt-id",
        correlation_id="test-correlation-id",
        strategy="btc_oracle",
        mode="paper",
        market_ticker="BTC-20260526-UP",
        status="REJECTED",
        phase="risk",
        reason_code="REJECTED_MAX_EXPOSURE",
        reason="Max exposure limit exceeded",
    )
    db_session.add(attempt)

    # Add some scan stats to BotState
    state = db_session.query(BotState).filter_by(mode="paper").first()
    state.misc_data = json.dumps({
        "heartbeat:btc_oracle": datetime.now(timezone.utc).isoformat(),
        "scan_stats:btc_oracle": {
            "last_scan_time": datetime.now(timezone.utc).isoformat(),
            "markets_scanned": 12,
            "signals_had_edge": 2,
            "signals_rejected": 1,
            "trades_executed": 1
        }
    })
    db_session.commit()

    # Call endpoint
    response = test_app.get("/api/v1/strategies/health")
    assert response.status_code == 200
    data = response.json()
    
    # Find btc_oracle in results
    health = next((h for h in data if h["strategy"] == "btc_oracle"), None)
    assert health is not None
    assert health["enabled"] is True
    assert health["trading_mode"] == "paper"
    assert health["markets_scanned"] == 12
    assert health["signals_had_edge"] == 2
    assert health["signals_rejected"] == 1
    assert health["trades_executed"] == 1
    assert health["last_signal"] is not None
    assert health["last_signal"]["market_ticker"] == "BTC-20260526-UP"
    assert len(health["rejections"]) > 0
    assert health["rejections"][0]["status"] == "REJECTED"
    assert health["rejections"][0]["reason_code"] == "REJECTED_MAX_EXPOSURE"


def test_strategies_compare_api_endpoint(test_app, db_session):
    # Override admin requirement
    from backend.api.auth import require_admin
    from backend.api.main import app
    app.dependency_overrides[require_admin] = lambda: None

    # Insert a StrategyHealthRecord
    health_rec = StrategyHealthRecord(
        strategy="btc_oracle",
        total_trades=10,
        wins=6,
        losses=4,
        win_rate=0.6,
        sharpe=1.5,
        max_drawdown=-0.1,
        brier_score=0.2,
        psi_score=0.05,
        status="active",
    )
    db_session.add(health_rec)

    # Insert some mock Trades
    t1 = Trade(
        market_ticker="BTC-UP",
        direction="buy",
        entry_price=0.5,
        size=10.0,
        market_type="btc",
        trading_mode="paper",
        strategy="btc_oracle",
        status="closed",
        pnl=5.0,
        settled=True,
        edge_at_entry=0.08,
        source="bot",
    )
    t2 = Trade(
        market_ticker="BTC-DOWN",
        direction="buy",
        entry_price=0.5,
        size=10.0,
        market_type="btc",
        trading_mode="paper",
        strategy="btc_oracle",
        status="closed",
        pnl=-5.0,
        settled=True,
        edge_at_entry=0.04,
        source="bot",
    )
    db_session.add(t1)
    db_session.add(t2)
    db_session.commit()

    # Call endpoint
    response = test_app.get("/api/v1/strategies/compare")
    assert response.status_code == 200
    data = response.json()
    
    assert "btc_oracle" in data
    comparison = data["btc_oracle"]
    assert comparison["total_trades"] == 2
    assert comparison["wins"] == 1
    assert comparison["losses"] == 1
    assert comparison["win_rate"] == 0.5
    assert comparison["total_pnl"] == 0.0
    assert comparison["avg_edge"] == 0.06
    assert comparison["avg_size"] == 10.0
    assert comparison["sharpe"] == 1.5
    assert comparison["max_drawdown"] == -0.1
    assert comparison["status"] == "active"


@pytest.mark.asyncio
@patch("backend.strategies.registry.STRATEGY_REGISTRY")
@patch("backend.core.strategy_executor.execute_decisions")
async def test_strategy_cycle_job_outcomes(mock_exec, mock_registry, db_session):
    # Set up mock strategy
    mock_strategy_cls = MagicMock()
    mock_strategy = AsyncMock()
    mock_strategy_cls.return_value = mock_strategy
    
    from backend.strategies.base import CycleResult
    
    mock_strategy.run = AsyncMock(return_value=CycleResult(
        decisions_recorded=2,
        trades_attempted=2,
        trades_placed=0,
        decisions=[
            {"decision": "BUY", "market_ticker": "BTC-UP", "token_id": "0x123", "edge": 0.05, "confidence": 0.8},
            {"decision": "BUY", "market_ticker": "BTC-DOWN", "token_id": "0x456", "edge": 0.06, "confidence": 0.8},
        ],
        markets_scanned=20,
    ))
    
    mock_registry.get.return_value = mock_strategy_cls
    
    # Mock executor decisions to execute 1 trade and reject 1
    mock_exec.return_value = [{"trade_id": 101}]
    
    # Configure strategy config in DB
    cfg = StrategyConfig(strategy_name="mock_strat", enabled=True, trading_mode="paper")
    db_session.add(cfg)
    db_session.commit()
    
    # Run strategy cycle
    await strategy_cycle_job("mock_strat", "paper")
    
    # Verify update_scan_stats was updated
    # We flush heartbeats first
    _flush_heartbeats()
    
    # Load BotState and check
    state = db_session.query(BotState).filter_by(mode="paper").first()
    misc = json.loads(state.misc_data)
    assert "scan_stats:mock_strat" in misc
    stats = misc["scan_stats:mock_strat"]
    assert stats["markets_scanned"] == 20
    assert stats["signals_had_edge"] == 2
    assert stats["signals_rejected"] == 1
    assert stats["trades_executed"] == 1
