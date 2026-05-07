"""Comprehensive integration tests for PolyEdge trading bot."""

import pytest
import time
import asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models.database import Base, Trade, Signal, SystemSettings
from backend.core.backtester import BacktestConfig, BacktestEngine
from backend.core.risk_manager import RiskManager
from backend.strategies.registry import load_all_strategies, STRATEGY_REGISTRY
from backend.config_extensions import settings as extended_settings
from backend.services.mirofish_service import get_mirofish_service


TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=TEST_ENGINE)
Base.metadata.create_all(bind=TEST_ENGINE)


@pytest.fixture()
def db():
    session = TestSession()
    yield session
    session.rollback()
    for table in reversed(Base.metadata.sorted_tables):
        session.execute(table.delete())
    session.commit()
    session.close()


def _add_settled_trade(db, *, ticker: str = "TEST", direction: str = "up",
                      entry_price: float = 0.50, size: float = 5.0,
                      settlement_value: float = 1.0, pnl: float = 2.5,
                      strategy: str = "test_strategy", ts: datetime = None):
    if ts is None:
        ts = datetime(2024, 1, 15)
    trade = Trade(
        market_ticker=ticker,
        platform="polymarket",
        direction=direction,
        entry_price=entry_price,
        size=size,
        model_probability=0.6,
        market_price_at_entry=entry_price,
        edge_at_entry=0.10,
        result="win" if pnl > 0 else "loss",
        settled=True,
        settlement_value=settlement_value,
        pnl=pnl,
        strategy=strategy,
        timestamp=ts,
        trading_mode="paper",
    )
    db.add(trade)
    db.commit()
    return trade


def test_configuration_system(db):
    """Test that the configuration system works correctly with both base and extended settings."""
    from backend.config import settings as base_settings
    
    assert hasattr(base_settings, 'DATABASE_URL')
    assert hasattr(base_settings, 'POLYMARKET_API_KEY')
    
    assert hasattr(extended_settings, 'AGGRESSIVE_MODE_ENABLED')
    assert hasattr(extended_settings, 'POLYGON_RPC_URL')
    assert hasattr(extended_settings, 'PORT')
    
    from backend.config_extensions import settings
    assert hasattr(settings, 'DATABASE_URL')
    assert hasattr(settings, 'AGGRESSIVE_MODE_ENABLED')
    
    system_setting = SystemSettings(
        key="test_config",
        value={"enabled": True, "value": 42},
        updated_at=datetime.now(timezone.utc)
    )
    db.add(system_setting)
    db.commit()
    
    stored = db.query(SystemSettings).filter_by(key="test_config").first()
    assert stored is not None
    assert stored.value["enabled"] is True
    assert stored.value["value"] == 42


def test_mirofish_service_lifecycle():
    """Test MiroFish service lifecycle management."""
    service = get_mirofish_service()
    
    assert service.state.value == "stopped"
    
    result = service.start()
    assert result["state"] == "running"
    assert "Started" in result["message"]
    
    result = service.pause()
    assert result["state"] == "paused"
    assert "Paused" in result["message"]
    
    result = service.start()
    assert result["state"] == "running"
    assert "Started" in result["message"]
    
    result = service.stop()
    assert result["state"] == "stopped"
    assert "Stopped" in result["message"]
    
    assert service.state.value == "stopped"


def test_edge_case_accuracy_low_probability(db):
    """Test accuracy with extremely low probability winning trades."""
    for i in range(10):
        _add_settled_trade(
            db,
            ticker=f"LOW_PROB_{i}",
            direction="up",
            entry_price=0.95,
            size=10.0,
            settlement_value=1.0,
            pnl=0.5,
            ts=datetime(2024, 1, 10 + (i % 10)),
        )
    
    config = BacktestConfig(
        strategy_name="test_strategy",
        start_date=datetime(2024, 1, 1),
        end_date=datetime(2024, 1, 31),
        initial_bankroll=1000.0
    )
    
    engine = BacktestEngine(config)
    result = asyncio.run(engine.run_from_trades(db))
    
    assert result.total_trades == 10
    assert result.winning_trades == 10
    assert result.win_rate == 1.0
    assert result.total_pnl > 0


def test_edge_case_accuracy_high_probability(db):
    """Test accuracy with extremely high probability losing trades."""
    for i in range(10):
        _add_settled_trade(
            db,
            ticker=f"HIGH_PROB_{i}",
            direction="up",
            entry_price=0.05,
            size=10.0,
            settlement_value=0.0,
            pnl=-9.5,
            ts=datetime(2024, 1, 10 + (i % 10)),
        )
    
    config = BacktestConfig(
        strategy_name="test_strategy",
        start_date=datetime(2024, 1, 1),
        end_date=datetime(2024, 1, 31),
        initial_bankroll=1000.0
    )
    
    engine = BacktestEngine(config)
    result = asyncio.run(engine.run_from_trades(db))
    
    assert result.total_trades == 10
    assert result.winning_trades == 0
    assert result.win_rate == 0.0
    assert result.total_pnl < 0


def test_performance_large_dataset(db):
    """Test performance with larger dataset (5000 trades)."""
    start_time = time.time()
    
    trades = []
    for i in range(5000):
        trade = Trade(
            market_ticker=f"LARGE_TEST_{i}",
            platform="polymarket",
            direction="up" if i % 2 == 0 else "down",
            entry_price=0.50,
            size=10.0,
            model_probability=0.60,
            market_price_at_entry=0.50,
            edge_at_entry=0.10,
            trading_mode="paper",
            strategy="test_strategy",
        )
        trades.append(trade)
    
    db.bulk_save_objects(trades)
    db.commit()
    
    end_time = time.time()
    insertion_duration = end_time - start_time
    
    assert insertion_duration < 5.0
    
    start_time = time.time()
    count = db.query(Trade).count()
    end_time = time.time()
    query_duration = end_time - start_time
    
    assert count == 5000
    assert query_duration < 0.5


def test_risk_manager_extreme_values(db):
    """Test risk manager with extreme values."""
    risk_manager = RiskManager()
    
    decision = risk_manager.validate_trade(
        size=1000.0,
        current_exposure=5000.0,
        bankroll=1000.0,
        confidence=0.95,
        market_ticker="EXTREME_TEST"
    )
    
    assert decision is not None
    
    decision = risk_manager.validate_trade(
        size=0.0,
        current_exposure=0.0,
        bankroll=0.0,
        confidence=0.0,
        market_ticker="ZERO_TEST"
    )
    
    assert decision is not None


def test_strategy_registry_comprehensive():
    """Test that all strategies load correctly and have proper configuration."""
    load_all_strategies()
    
    assert len(STRATEGY_REGISTRY) > 0
    
    for name, strategy_class in STRATEGY_REGISTRY.items():
        assert hasattr(strategy_class, 'run') or hasattr(strategy_class, '__call__')
        assert isinstance(name, str)
        assert len(name) > 0


def test_backtest_performance_regression(db):
    """Regression test for backtest performance with complex scenarios."""
    scenarios = [
        {"ticker": "HIGH_WIN", "entry": 0.3, "settlement": 1.0, "pnl": 7.0, "count": 20},
        {"ticker": "LOW_WIN", "entry": 0.8, "settlement": 1.0, "pnl": 2.0, "count": 10},
        {"ticker": "HIGH_LOSE", "entry": 0.2, "settlement": 0.0, "pnl": -2.0, "count": 15},
        {"ticker": "LOW_LOSE", "entry": 0.9, "settlement": 0.0, "pnl": -1.0, "count": 5},
    ]
    
    trade_count = 0
    for scenario in scenarios:
        for i in range(scenario["count"]):
            _add_settled_trade(
                db,
                ticker=f"{scenario['ticker']}_{i}",
                direction="up",
                entry_price=scenario["entry"],
                size=10.0,
                settlement_value=scenario["settlement"],
                pnl=scenario["pnl"],
                ts=datetime(2024, 1, 10 + (i % 20)),
            )
            trade_count += 1
    
    config = BacktestConfig(
        strategy_name="test_strategy",
        start_date=datetime(2024, 1, 1),
        end_date=datetime(2024, 1, 31),
        initial_bankroll=1000.0
    )
    
    start_time = time.time()
    engine = BacktestEngine(config)
    result = asyncio.run(engine.run_from_trades(db))
    end_time = time.time()
    
    execution_time = end_time - start_time
    
    assert execution_time < 2.0
    
    assert result.total_trades == trade_count
    assert hasattr(result, 'win_rate')
    assert hasattr(result, 'total_pnl')


@pytest.mark.asyncio
async def test_concurrent_operations(db):
    """Test concurrent database operations for performance."""
    async def add_trades_task(count, task_id):
        trades = []
        for i in range(count):
            trade = Trade(
                market_ticker=f"CONCURRENT_{task_id}_{i}",
                platform="polymarket",
                direction="up",
                entry_price=0.50,
                size=5.0,
                model_probability=0.6,
                market_price_at_entry=0.50,
                edge_at_entry=0.10,
                trading_mode="paper",
                strategy="test_strategy",
            )
            trades.append(trade)
        db.bulk_save_objects(trades)
        db.commit()
        return len(trades)
    
    tasks = [
        add_trades_task(100, 1),
        add_trades_task(100, 2), 
        add_trades_task(100, 3),
    ]
    
    start_time = time.time()
    results = await asyncio.gather(*tasks)
    end_time = time.time()
    
    execution_time = end_time - start_time
    
    assert len(results) == 3
    assert all(r == 100 for r in results)
    
    assert execution_time < 1.0
    
    total_trades = db.query(Trade).count()
    assert total_trades == 300


if __name__ == "__main__":
    pytest.main([__file__, "-v"])