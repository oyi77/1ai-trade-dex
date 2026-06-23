"""Performance and accuracy tests for PolyEdge trading bot."""

import pytest
import time
import asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models.database import Base, Trade
from backend.core.backtester import BacktestConfig, BacktestEngine
from backend.core.risk.risk_manager import RiskManager
from backend.strategies.loader import load_all_strategies
from backend.strategies.registry import STRATEGY_REGISTRY

TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=TEST_ENGINE)
Base.metadata.create_all(bind=TEST_ENGINE)


@pytest.fixture()
def db():
    # Re-run create_all: other test modules may have registered new tables
    # on Base.metadata after this module's import-time create_all, and the
    # teardown below deletes from every table in sorted_tables.
    Base.metadata.create_all(bind=TEST_ENGINE)
    session = TestSession()
    yield session
    session.rollback()
    for table in reversed(Base.metadata.sorted_tables):
        session.execute(table.delete())
    session.commit()
    session.close()


def _add_settled_trade(
    db,
    *,
    ticker: str = "TEST",
    direction: str = "up",
    entry_price: float = 0.50,
    size: float = 5.0,
    settlement_value: float = 1.0,
    pnl: float = 2.5,
    strategy: str = "test_strategy",
    ts: datetime = None,
):
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


def test_database_performance(db):
    start_time = time.time()

    trades = []
    for i in range(1000):
        trade = Trade(
            market_ticker=f"TEST-{i}",
            platform="polymarket",
            direction="up",
            entry_price=0.50,
            size=10.0,
            model_probability=0.60,
            market_price_at_entry=0.50,
            edge_at_entry=0.10,
            trading_mode="paper",
            strategy="test_strategy",
            confidence=0.80,
        )
        trades.append(trade)

    db.bulk_save_objects(trades)
    db.commit()

    end_time = time.time()
    duration = end_time - start_time

    assert duration < 2.0

    start_time = time.time()
    count = db.query(Trade).count()
    end_time = time.time()
    query_duration = end_time - start_time

    assert count == 1000
    assert query_duration < 0.1


def test_strategy_registration_performance():
    start_time = time.time()
    load_all_strategies()
    end_time = time.time()
    duration = end_time - start_time

    assert duration < 1.0
    assert len(STRATEGY_REGISTRY) > 0


def test_risk_manager_performance(db):
    risk_manager = RiskManager()

    start_time = time.time()
    for i in range(100):
        decision = risk_manager.validate_trade(
            size=10.0,
            current_exposure=50.0,
            bankroll=1000.0,
            confidence=0.75,
            market_ticker=f"TEST-MARKET-{i}",
        )
        assert decision is not None
    end_time = time.time()
    duration = end_time - start_time

    # Allow slightly more time since this is a complex validation
    assert duration < 2.0


@pytest.mark.asyncio
async def test_backtest_accuracy_winning(db):
    for i in range(50):
        _add_settled_trade(
            db,
            ticker=f"WINNER-{i}",
            direction="up",
            entry_price=0.60,
            size=10.0,
            settlement_value=1.0,
            pnl=4.0,
            ts=datetime(2024, 1, 10 + (i % 10)),
        )

    config = BacktestConfig(
        strategy_name="test_strategy",
        start_date=datetime(2024, 1, 1),
        end_date=datetime(2024, 1, 31),
        initial_bankroll=1000.0,
    )

    engine = BacktestEngine(config)
    result = await engine.run_from_trades(db)

    assert result.total_trades == 50
    assert result.winning_trades == 50
    assert result.win_rate == 1.0
    assert result.total_pnl > 0
    assert result.final_bankroll > config.initial_bankroll


@pytest.mark.asyncio
async def test_backtest_accuracy_mixed(db):
    for i in range(30):
        _add_settled_trade(
            db,
            ticker=f"WINNER-{i}",
            direction="up",
            entry_price=0.60,
            size=10.0,
            settlement_value=1.0,
            pnl=4.0,
            ts=datetime(2024, 1, 10 + (i % 10)),
        )

    for i in range(20):
        _add_settled_trade(
            db,
            ticker=f"LOSER-{i}",
            direction="up",
            entry_price=0.60,
            size=10.0,
            settlement_value=0.0,
            pnl=-6.0,
            ts=datetime(2024, 1, 10 + (i % 10)),
        )

    config = BacktestConfig(
        strategy_name="test_strategy",
        start_date=datetime(2024, 1, 1),
        end_date=datetime(2024, 1, 31),
        initial_bankroll=1000.0,
    )

    engine = BacktestEngine(config)
    result = await engine.run_from_trades(db)

    assert result.total_trades == 50
    assert result.winning_trades == 30
    assert abs(result.win_rate - 0.6) < 0.01
    assert hasattr(result, "total_pnl")
    assert hasattr(result, "final_bankroll")


def test_full_system_performance(db):
    start_time = time.time()

    load_all_strategies()

    for i in range(50):
        _add_settled_trade(
            db,
            ticker=f"WINNER-{i}",
            direction="up",
            entry_price=0.50,
            size=10.0,
            settlement_value=1.0,
            pnl=5.0,
            strategy="general_scanner",
            ts=datetime(2024, 1, 10 + (i % 10)),
        )

    for i in range(50):
        _add_settled_trade(
            db,
            ticker=f"LOSER-{i}",
            direction="up",
            entry_price=0.50,
            size=10.0,
            settlement_value=0.0,
            pnl=-5.0,
            strategy="general_scanner",
            ts=datetime(2024, 1, 10 + (i % 10)),
        )

    config = BacktestConfig(
        strategy_name="general_scanner",
        start_date=datetime(2024, 1, 1),
        end_date=datetime(2024, 1, 31),
        initial_bankroll=1000.0,
    )

    engine = BacktestEngine(config)

    result = asyncio.run(engine.run_from_trades(db))

    end_time = time.time()
    duration = end_time - start_time

    assert duration < 5.0

    assert result.total_trades == 100
    assert 40 <= result.winning_trades <= 60
    assert abs(result.win_rate - 0.5) < 0.1


def test_large_dataset_bulk_insert_performance(db):
    start_time = time.time()

    trades = []
    for i in range(5000):
        trades.append(
            Trade(
                market_ticker=f"LARGE-{i % 100}",
                platform="polymarket",
                direction="up" if i % 3 == 0 else "down",
                entry_price=0.40 + (i % 50) * 0.01,
                size=5.0 + (i % 20) * 0.5,
                model_probability=0.50 + (i % 30) * 0.01,
                market_price_at_entry=0.40 + (i % 50) * 0.01,
                edge_at_entry=0.05 + (i % 15) * 0.005,
                trading_mode="paper",
                strategy=["btc_5min", "weather_emos", "general_scanner"][i % 3],
                confidence=0.60 + (i % 20) * 0.01,
                result="win" if i % 3 == 0 else "loss",
                settled=True,
                settlement_value=1.0 if i % 3 == 0 else 0.0,
                pnl=(
                    (0.40 + (i % 50) * 0.01) * (5.0 + (i % 20) * 0.5)
                    if i % 3 == 0
                    else -(5.0 + (i % 20) * 0.5) * (1 - (0.40 + (i % 50) * 0.01))
                ),
                timestamp=datetime(2024, 1, 1) + timedelta(hours=i),
            )
        )
    db.bulk_save_objects(trades)
    db.commit()

    insert_duration = time.time() - start_time
    assert (
        insert_duration < 5.0
    ), f"Bulk insert of 5000 trades took {insert_duration:.2f}s"

    start_time = time.time()
    count = db.query(Trade).count()
    assert count == 5000

    start_time = time.time()
    _filtered = db.query(Trade).filter(Trade.strategy == "btc_5min").count()
    query_duration = time.time() - start_time
    assert query_duration < 0.2, f"Filtered query took {query_duration:.3f}s"

    start_time = time.time()
    from sqlalchemy import func

    _avg_pnl = (
        db.query(func.avg(Trade.pnl)).filter(Trade.strategy == "btc_5min").scalar()
    )
    agg_duration = time.time() - start_time
    assert agg_duration < 0.2, f"Aggregation query took {agg_duration:.3f}s"


def test_risk_manager_edge_cases():
    risk_manager = RiskManager()

    zero_decision = risk_manager.validate_trade(
        size=0.0,
        current_exposure=50.0,
        bankroll=1000.0,
        confidence=0.80,
        market_ticker="EDGE-CASE-ZERO",
    )
    assert zero_decision is not None

    max_decision = risk_manager.validate_trade(
        size=10000.0,
        current_exposure=99999.0,
        bankroll=100.0,
        confidence=0.99,
        market_ticker="EDGE-CASE-MAX",
    )
    assert max_decision is not None

    low_conf_decision = risk_manager.validate_trade(
        size=5.0,
        current_exposure=0.0,
        bankroll=1000.0,
        confidence=0.01,
        market_ticker="EDGE-CASE-LOW-CONF",
    )
    assert low_conf_decision is not None

    high_conf_decision = risk_manager.validate_trade(
        size=5.0,
        current_exposure=0.0,
        bankroll=1000.0,
        confidence=1.0,
        market_ticker="EDGE-CASE-HIGH-CONF",
    )
    assert high_conf_decision is not None


def test_signal_accuracy_edge_cases(db):
    now = datetime.now(timezone.utc)

    near_equal_trade = Trade(
        market_ticker="NEAR-EQUAL-EDGE",
        platform="polymarket",
        direction="up",
        entry_price=0.50,
        size=1.0,
        model_probability=0.51,
        market_price_at_entry=0.50,
        edge_at_entry=0.01,
        trading_mode="paper",
        strategy="test_strategy",
        confidence=0.52,
        timestamp=now,
    )
    db.add(near_equal_trade)
    db.commit()
    assert near_equal_trade.id is not None
    assert near_equal_trade.edge_at_entry < 0.05

    max_price_trade = Trade(
        market_ticker="MAX-PRICE",
        platform="polymarket",
        direction="up",
        entry_price=0.99,
        size=10.0,
        model_probability=0.99,
        market_price_at_entry=0.99,
        edge_at_entry=0.01,
        trading_mode="paper",
        strategy="test_strategy",
        confidence=0.99,
        timestamp=now,
    )
    db.add(max_price_trade)
    db.commit()
    assert max_price_trade.entry_price == 0.99

    min_price_trade = Trade(
        market_ticker="MIN-PRICE",
        platform="polymarket",
        direction="down",
        entry_price=0.01,
        size=10.0,
        model_probability=0.02,
        market_price_at_entry=0.01,
        edge_at_entry=0.01,
        trading_mode="paper",
        strategy="test_strategy",
        confidence=0.03,
        timestamp=now,
    )
    db.add(min_price_trade)
    db.commit()
    assert min_price_trade.entry_price == 0.01


def test_concurrent_risk_validation():
    risk_manager = RiskManager()
    results = []
    for i in range(500):
        decision = risk_manager.validate_trade(
            size=5.0 + i * 0.1,
            current_exposure=float(i * 10),
            bankroll=10000.0,
            confidence=0.60 + (i % 40) * 0.01,
            market_ticker=f"PERF-MARKET-{i % 50}",
        )
        results.append(decision)

    assert len(results) == 500
    allowed = sum(1 for d in results if d.allowed)
    assert allowed > 0, "At least some trades should be allowed"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
