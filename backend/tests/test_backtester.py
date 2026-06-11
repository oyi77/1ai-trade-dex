"""Tests for the BacktestEngine in backend/core/backtester.py.

Uses an in-memory SQLite database seeded with Trade/Signal records.
No external APIs are mocked — all data comes from the in-memory DB.
"""

import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models.database import Base, Trade
from backend.core.backtester import BacktestConfig, BacktestEngine, BacktestResult

# ---------------------------------------------------------------------------
# In-memory DB fixture shared across the module
# ---------------------------------------------------------------------------

TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=TEST_ENGINE)
Base.metadata.create_all(bind=TEST_ENGINE)


@pytest.fixture()
def db():
    """Fresh DB session; rolls back after each test to keep isolation."""
    # Re-run create_all: other test modules may have registered new tables
    # on Base.metadata after this module's import-time create_all, and the
    # teardown below deletes from every table in sorted_tables.
    Base.metadata.create_all(bind=TEST_ENGINE)
    session = TestSession()
    yield session
    session.rollback()
    # Delete all rows so tests don't bleed into each other
    for table in reversed(Base.metadata.sorted_tables):
        session.execute(table.delete())
    session.commit()
    session.close()


def _make_config(
    strategy_name: str = "test_strategy",
    days: int = 30,
    initial_bankroll: float = 100.0,
    **kwargs,
) -> BacktestConfig:
    end = datetime(2024, 1, 31)
    start = end - timedelta(days=days)
    return BacktestConfig(
        strategy_name=strategy_name,
        start_date=start,
        end_date=end,
        initial_bankroll=initial_bankroll,
        **kwargs,
    )


def _add_settled_trade(
    db,
    *,
    ticker: str = "BTC-TEST",
    direction: str = "up",
    entry_price: float = 0.50,
    size: float = 5.0,
    settlement_value: float = 1.0,  # 1.0 = UP won, 0.0 = DOWN won
    pnl: float = 2.5,
    strategy: str = "test_strategy",
    ts: datetime = None,
) -> Trade:
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


def _make_engine_with_db(config: BacktestConfig, db_session):
    """Return a BacktestEngine; db_session is passed explicitly at call time."""
    return BacktestEngine(config)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backtest_with_winning_trades(db):
    """Simulate three winning trades; total PnL must be positive."""
    for i in range(3):
        _add_settled_trade(
            db,
            ticker=f"BTC-WIN-{i}",
            direction="up",
            entry_price=0.50,
            size=5.0,
            settlement_value=1.0,
            pnl=2.5,
            ts=datetime(2024, 1, 10 + i),
        )

    config = _make_config()
    engine = _make_engine_with_db(config, db)
    result: BacktestResult = await engine.run_from_trades(db)

    assert result.total_trades == 3
    assert result.total_pnl > 0
    assert result.winning_trades == 3
    assert result.win_rate == pytest.approx(1.0)
    assert result.final_bankroll > config.initial_bankroll


@pytest.mark.asyncio
async def test_backtest_with_losing_trades(db):
    """Simulate three losing trades; total PnL must be negative."""
    for i in range(3):
        _add_settled_trade(
            db,
            ticker=f"BTC-LOSE-{i}",
            direction="up",
            entry_price=0.50,
            size=5.0,
            settlement_value=0.0,  # DOWN won — our UP bet loses
            pnl=-5.0,
            ts=datetime(2024, 1, 10 + i),
        )

    config = _make_config()
    engine = _make_engine_with_db(config, db)
    result: BacktestResult = await engine.run_from_trades(db)

    assert result.total_trades == 3
    assert result.total_pnl < 0
    assert result.winning_trades == 0
    assert result.win_rate == pytest.approx(0.0)
    assert result.final_bankroll < config.initial_bankroll


@pytest.mark.asyncio
async def test_risk_limits_respected(db):
    """max_trade_size and max_position_fraction cap individual trade sizes."""
    # Add a large trade — engine should cap the simulated size
    for i in range(5):
        _add_settled_trade(
            db,
            ticker=f"BTC-RISK-{i}",
            direction="up",
            entry_price=0.50,
            size=50.0,  # original was huge
            settlement_value=1.0,
            pnl=25.0,
            ts=datetime(2024, 1, 5 + i),
        )

    # Tight limits
    config = _make_config(
        initial_bankroll=100.0,
        max_trade_size=2.0,  # hard cap at $2
        max_position_fraction=0.05,  # at most 5% of bankroll
    )
    engine = _make_engine_with_db(config, db)
    result: BacktestResult = await engine.run_from_trades(db)

    # Every simulated trade size must not exceed the cap
    for bt in result.trades:
        assert (
            bt.size <= config.max_trade_size + 1e-9
        ), f"Trade size {bt.size} exceeds max_trade_size {config.max_trade_size}"


@pytest.mark.asyncio
async def test_equity_curve_tracked(db):
    """Equity curve must contain one entry per processed trade."""
    n = 4
    for i in range(n):
        _add_settled_trade(
            db,
            ticker=f"BTC-EC-{i}",
            pnl=1.0,
            ts=datetime(2024, 1, 10 + i),
        )

    config = _make_config()
    engine = _make_engine_with_db(config, db)
    result: BacktestResult = await engine.run_from_trades(db)

    assert len(result.equity_curve) == result.total_trades
    # Each entry has required keys
    for point in result.equity_curve:
        assert "timestamp" in point
        assert "bankroll" in point


@pytest.mark.asyncio
async def test_metrics_calculation(db):
    """win_rate, max_drawdown, and return_pct are computed correctly."""
    # 2 wins, 1 loss
    _add_settled_trade(
        db, ticker="BTC-M1", pnl=5.0, settlement_value=1.0, ts=datetime(2024, 1, 10)
    )
    _add_settled_trade(
        db, ticker="BTC-M2", pnl=5.0, settlement_value=1.0, ts=datetime(2024, 1, 11)
    )
    _add_settled_trade(
        db,
        ticker="BTC-M3",
        direction="up",
        entry_price=0.5,
        size=5.0,
        pnl=-5.0,
        settlement_value=0.0,
        ts=datetime(2024, 1, 12),
    )

    config = _make_config(initial_bankroll=100.0)
    engine = _make_engine_with_db(config, db)
    result: BacktestResult = await engine.run_from_trades(db)

    assert result.total_trades == 3
    assert result.winning_trades == 2
    assert result.win_rate == pytest.approx(2 / 3, rel=1e-3)
    assert isinstance(result.max_drawdown, float)
    assert result.max_drawdown >= 0.0
    # return_pct reflects direction of PnL
    expected_return = result.total_pnl / 100.0 * 100
    assert result.return_pct == pytest.approx(expected_return, rel=1e-3)


@pytest.mark.asyncio
async def test_daily_loss_stops_trading(db):
    """Daily loss limit halts further trades that calendar day.

    The engine recalculates position size using Kelly, so we set a very tight
    daily_loss_limit (0.05) and high edge_at_entry (1.0) so the simulated
    size is large enough that two losses exceed the limit, blocking a third.
    """
    # With edge=1.0, kelly_size = bankroll * 0.0625 * 1.0 = 6.25
    # Capped by max_trade_size=10 and max_position_fraction=0.10 → size = 6.25
    # settlement_value=0.0 + direction=up → pnl = -size = -6.25 each loss
    # daily_loss_limit = 5.0 → after first loss (-6.25) day_loss <= -5 → second trade blocked

    def _add_high_edge(ticker, ts, settlement_value, direction="up"):
        trade = Trade(
            market_ticker=ticker,
            platform="polymarket",
            direction=direction,
            entry_price=0.50,
            size=10.0,
            model_probability=0.9,
            market_price_at_entry=0.50,
            edge_at_entry=1.0,  # high edge → large simulated size
            result="loss" if settlement_value == 0.0 else "win",
            settled=True,
            settlement_value=settlement_value,
            pnl=-10.0 if settlement_value == 0.0 else 5.0,
            strategy="test_strategy",
            timestamp=ts,
            trading_mode="paper",
        )
        db.add(trade)
        db.commit()

    # Jan 15: two losses — cumulative simulated loss should exceed limit=5.0
    _add_high_edge("BTC-DL1", datetime(2024, 1, 15, 9, 0), settlement_value=0.0)
    _add_high_edge("BTC-DL2", datetime(2024, 1, 15, 10, 0), settlement_value=0.0)
    # Jan 15: third trade — should be blocked
    _add_high_edge("BTC-DL3", datetime(2024, 1, 15, 11, 0), settlement_value=0.0)
    # Jan 16: should proceed normally
    _add_high_edge("BTC-DL4", datetime(2024, 1, 16, 9, 0), settlement_value=1.0)

    # daily_loss_limit=5.0 means after ~6.25 simulated loss on first trade, next same-day trade blocked
    config = _make_config(daily_loss_limit=5.0)
    engine = _make_engine_with_db(config, db)
    result: BacktestResult = await engine.run_from_trades(db)

    tickers = [t.market_ticker for t in result.trades]
    assert (
        "BTC-DL3" not in tickers
    ), f"Third same-day trade should be blocked by daily loss limit; got tickers={tickers}"
    assert "BTC-DL4" in tickers, "Next-day trade should proceed"
