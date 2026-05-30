import pytest
import asyncio
import time
from unittest.mock import MagicMock, AsyncMock, patch
from contextlib import contextmanager

from backend.core.event_bus import MarketEvent
from backend.strategies.hft_scalper import HFTScalperStrategy, ScalpPosition
from backend.strategies.market_maker import MarketMakerStrategy, ActiveQuote
from backend.core.simulation.tick_simulator import TickSimulator
from backend.models.database import StrategyConfig, DecisionLog


@pytest.fixture
def mock_db_session(db_session):
    """Reuse test database session."""
    return db_session


@contextmanager
def patch_db_session(db_session):
    """Helper to patch get_db_session to point to mock DB transaction."""
    @contextmanager
    def _mock_get_db_session():
        yield db_session

    with patch("backend.db.utils.get_db_session", _mock_get_db_session):
        yield


@pytest.mark.asyncio
async def test_hft_scalper_queue_processing(mock_db_session):
    """Verify that trade ticks ingested into HFTScalper queue are processed sequentially by consumer."""
    strategy = HFTScalperStrategy()
    strategy.subscribed_tokens = {"token_scalp"}
    strategy._tokens_populated = True
    strategy.start_consumer()

    # Configure fast thresholds
    strategy.default_params = {
        **strategy.default_params,
        "min_history_points": 3,
        "velocity_threshold_up": 0.01,
        "entry_threshold": 0.01,
        "cooldown_seconds": 0,
        "momentum_confirmation": 2,
    }

    with patch_db_session(mock_db_session):
        # Push 3 ticks sequentially to trigger momentum entry
        t0 = time.time()
        
        # Ingest tick 1
        await strategy.on_market_event(MarketEvent("token_scalp", "last_trade_price", {"price": "0.50", "timestamp": t0 - 4}))
        await asyncio.sleep(0.01)
        assert len(strategy._price_history["token_scalp"]) == 1

        # Ingest tick 2
        await strategy.on_market_event(MarketEvent("token_scalp", "last_trade_price", {"price": "0.52", "timestamp": t0 - 2}))
        await asyncio.sleep(0.01)
        assert len(strategy._price_history["token_scalp"]) == 2

        # Ingest tick 3 (breaches threshold)
        await strategy.on_market_event(MarketEvent("token_scalp", "last_trade_price", {"price": "0.60", "timestamp": t0}))
        await asyncio.sleep(0.05)
        
        # Verify position opened locally!
        assert "token_scalp" in strategy._open_positions
        pos = strategy._open_positions["token_scalp"]
        assert pos.entry_price == 0.60
        assert pos.direction == "BUY_YES"

        # Ingest tick 4 (hits TAKE_PROFIT: profit_target=0.008, 0.60 * 1.01 = 0.606)
        await strategy.on_market_event(MarketEvent("token_scalp", "last_trade_price", {"price": "0.62", "timestamp": t0 + 2}))
        await asyncio.sleep(0.05)

        # Verify position successfully closed on take profit!
        assert "token_scalp" not in strategy._open_positions
        assert len(strategy._closed_positions) == 1
        assert strategy._closed_positions[0].exit_reason == "TAKE_PROFIT"

    # Stop background tasks
    if strategy._consumer_task:
        strategy._consumer_task.cancel()


@pytest.mark.asyncio
async def test_market_maker_queue_processing(mock_db_session):
    """Verify L2 order book updates ingested into MarketMaker are parsed and trigger quoting."""
    strategy = MarketMakerStrategy()
    strategy.subscribed_tokens = {"token_mm"}
    strategy._tokens_populated = True
    strategy.start_consumer()

    # Configure quoting size
    strategy.default_params = {
        **strategy.default_params,
        "quote_size": 10.0,
        "min_spread": 0.02,
    }

    with patch_db_session(mock_db_session):
        # Construct and push L2 book tick
        event_data = {
            "bids": [{"price": 0.50, "size": 100}],
            "asks": [{"price": 0.52, "size": 100}],
            "timestamp": time.time(),
        }
        event = MarketEvent("token_mm", "book", event_data, time.time())
        
        await strategy.on_market_event(event)
        await asyncio.sleep(0.2)

        # Verify two-sided quotes placed locally!
        active_quotes = strategy._get_active_quotes("token_mm")
        assert len(active_quotes) == 2
        
        sides = {q.side for q in active_quotes}
        assert "BUY" in sides
        assert "SELL" in sides

        buy_quote = [q for q in active_quotes if q.side == "BUY"][0]
        assert buy_quote.price < 0.51  # bid price is below mid (0.51)

    # Stop background tasks
    if strategy._consumer_task:
        strategy._consumer_task.cancel()


@pytest.mark.asyncio
async def test_hft_pipelines_safety_halt(mock_db_session):
    """Verify that WS disconnection triggers immediate halts and cancels all orders/quotes."""
    strategy = MarketMakerStrategy()
    strategy.subscribed_tokens = {"token_mm"}
    strategy._tokens_populated = True
    strategy.start_consumer()

    # Initialize a mock active quote
    strategy._add_active_quote(ActiveQuote(
        quote_id="quote-123",
        market_id="token_mm",
        side="BUY",
        price=0.49,
        size=10.0,
        placed_at=time.monotonic(),
        order_id="ord-abc",
    ))

    assert len(strategy._get_active_quotes("token_mm")) == 1

    # Simulate WS disconnection trigger
    await strategy.on_ws_disconnected()

    # Verify quoting halted and all active quotes canceled!
    assert strategy._halted is True
    assert len(strategy._get_active_quotes("token_mm")) == 0

    # Ensure further events are skipped
    event = MarketEvent("token_mm", "book", {"bids": [[0.50, 100]], "asks": [[0.52, 100]], "timestamp": time.time()})
    res = await strategy.on_market_event(event)
    assert res is None

    # Stop background tasks
    if strategy._consumer_task:
        strategy._consumer_task.cancel()


@pytest.mark.asyncio
async def test_high_fidelity_tick_replay_simulator(mock_db_session):
    """Verify TickSimulator replays mock trades, simulates execution, slippage, and generates P&L reports."""
    ticks = [
        {"token_id": "token_sim", "price": 0.50, "timestamp": time.time() - 10},
        {"token_id": "token_sim", "price": 0.52, "timestamp": time.time() - 8},
        {"token_id": "token_sim", "price": 0.60, "timestamp": time.time() - 6},  # Breach triggers simulated BUY
        {"token_id": "token_sim", "price": 0.65, "timestamp": time.time() - 4},  # TAKE_PROFIT exit
    ]

    simulator = TickSimulator(
        strategy_class=HFTScalperStrategy,
        initial_balance=1000.0,
        latency_ms=10.0,
        slippage_pct=0.001,
    )

    # Replay simulator in mock DB context
    with patch_db_session(mock_db_session):
        report = await simulator.run_simulation(ticks)

        assert report is not None
        assert report["total_trades"] >= 1
        assert report["final_balance"] != 1000.0
        assert report["total_pnl_usd"] != 0.0
        assert report["win_rate"] >= 0.0
