import pytest
import asyncio
import json
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from contextlib import contextmanager

from backend.config import settings
from backend.core.event_bus import event_bus, MarketEvent
from backend.core.ws_dispatcher import WSDispatcher, ws_dispatcher
from backend.strategies.realtime_scanner import RealtimeScannerStrategy
from backend.models.database import StrategyConfig, Trade, DecisionLog
from backend.core.market_scanner import MarketInfo
from backend.strategies.registry import STRATEGY_REGISTRY


@pytest.fixture
def mock_db_session(db_session):
    """Reuse test database session."""
    return db_session


@pytest.fixture
def cleanup_event_bus():
    """Ensure event bus is cleared of any registered strategy handlers after each test."""
    yield
    for name in list(event_bus._strategy_subs.keys()):
        event_bus.unsubscribe_strategy(name)


@contextmanager
def patch_db_and_scanner(db_session, mock_tokens=None):
    """Context manager to consistently patch get_db_session and market_scanner calls."""
    if mock_tokens is None:
        mock_tokens = ["token_123"]

    @contextmanager
    def _mock_get_db_session():
        yield db_session

    mock_markets = [
        MarketInfo(
            ticker="MKT1",
            slug="mkt-1",
            category="crypto",
            end_date=None,
            volume=1000,
            liquidity=5000,
            metadata={"clobTokenIds": mock_tokens},
        )
    ]

    with patch("backend.db.utils.get_db_session", _mock_get_db_session), \
         patch("backend.core.market_scanner.fetch_all_active_markets", AsyncMock(return_value=mock_markets)), \
         patch("backend.core.market_scanner.fetch_short_duration_token_ids", AsyncMock(return_value=mock_tokens)):
        yield


def setup_strategy_config(db_session):
    """Safely upsert StrategyConfig for realtime_scanner to avoid UNIQUE constraint violations."""
    cfg = db_session.query(StrategyConfig).filter(StrategyConfig.strategy_name == "realtime_scanner").first()
    if not cfg:
        cfg = StrategyConfig(
            strategy_name="realtime_scanner",
            enabled=True,
            trading_mode="paper",
        )
        db_session.add(cfg)
    else:
        cfg.enabled = True
        cfg.trading_mode = "paper"
    db_session.commit()


@pytest.mark.asyncio
async def test_ws_dispatcher_initialization(mock_db_session, cleanup_event_bus):
    """Verify WSDispatcher correctly discovers and initializes active event-driven strategies."""
    setup_strategy_config(mock_db_session)

    dispatcher = WSDispatcher()

    with patch_db_and_scanner(mock_db_session, ["token_123"]), \
         patch("backend.core.ws_dispatcher.PolymarketWebSocket") as mock_ws_cls:
        
        mock_ws = MagicMock()
        mock_ws.connect = AsyncMock()
        mock_ws_cls.return_value = mock_ws

        # Mock event_bus get_all_subscribed_tokens
        with patch.object(
            event_bus, "get_all_subscribed_tokens", return_value={"token_123"}
        ):
            await dispatcher.start()
            await asyncio.sleep(0.1)

            assert "realtime_scanner" in dispatcher._strategies
            assert dispatcher._running is True
            mock_ws_cls.assert_called_once()
            mock_ws.connect.assert_called_once()

            await dispatcher.stop()
            assert dispatcher._running is False


@pytest.mark.asyncio
async def test_ws_dispatcher_dispatches_events(mock_db_session, cleanup_event_bus):
    """Mock raw WebSocket events and verify they are dispatched through EventBus into strategies."""
    setup_strategy_config(mock_db_session)

    dispatcher = WSDispatcher()

    # Let the strategy define token subscriptions
    strategy = RealtimeScannerStrategy()
    strategy.subscribed_tokens = {"token_abc"}
    strategy._tokens_populated = True

    with patch_db_and_scanner(mock_db_session, ["token_abc"]), \
         patch("backend.core.ws_dispatcher.PolymarketWebSocket") as mock_ws_cls:
        
        mock_ws = MagicMock()
        mock_ws.connect = AsyncMock()
        mock_ws_cls.return_value = mock_ws

        with patch.dict(STRATEGY_REGISTRY, {"realtime_scanner": lambda: strategy}, clear=True):
            await dispatcher.start()
            await asyncio.sleep(0.1)

            # Verify strategy is registered on the EventBus
            assert "realtime_scanner" in event_bus._strategy_subs
            assert "token_abc" in event_bus._token_index

            # Publish mock price event through the EventBus
            mock_event_data = {
                "asset_id": "token_abc",
                "price": "0.55",
                "timestamp": int(time.time()),
            }

            # Inject directly into event bus publish to mock WS push
            event_bus.publish("last_trade_price", mock_event_data)

            # Allow event loop dispatch to run
            await asyncio.sleep(0.1)

            # Check that strategy's history successfully recorded the tick
            assert "token_abc" in strategy._price_history
            prices = list(strategy._price_history["token_abc"].prices)
            assert len(prices) == 1
            assert prices[0][1] == 0.55

            await dispatcher.stop()


@pytest.mark.asyncio
async def test_realtime_scanner_velocity_signals(mock_db_session, cleanup_event_bus):
    """Verify that rapid ticks breach velocity thresholds and generate real-time BUY signals."""
    strategy = RealtimeScannerStrategy()
    strategy.subscribed_tokens = {"token_fast"}
    strategy._tokens_populated = True
    strategy._token_to_ticker["token_fast"] = "FAST_TICKER"

    # Set parameters to trigger quickly (e.g. 5 points, low thresholds)
    strategy.default_params = {
        **strategy.default_params,
        "min_history_points": 3,
        "velocity_threshold_up": 0.01,  # 1% price velocity
        "velocity_window_slow": 5,
        "min_signal_interval": 1,
    }

    with patch_db_and_scanner(mock_db_session, ["token_fast"]):
        # 1. First tick (baseline)
        t0 = time.time() - 4
        event1 = MarketEvent("token_fast", "last_trade_price", {"price": "0.50", "timestamp": t0})
        res1 = await strategy.on_market_event(event1)
        assert res1 is None

        # 2. Second tick
        t1 = time.time() - 2
        event2 = MarketEvent("token_fast", "last_trade_price", {"price": "0.52", "timestamp": t1})
        res2 = await strategy.on_market_event(event2)
        assert res2 is None

        # 3. Third tick with massive spike (velocity = (0.65 - 0.50) / 4s = 0.0375 > 0.01 threshold)
        t2 = time.time()
        event3 = MarketEvent("token_fast", "last_trade_price", {"price": "0.65", "timestamp": t2})
        res3 = await strategy.on_market_event(event3)

        # Confirm signal generated!
        assert res3 is not None
        assert res3["decision"] == "BUY"
        assert res3["market_ticker"] == "FAST_TICKER"
        assert res3["direction"] == "up"
        assert res3["token_id"] == "token_fast"

        # Verify decision was persisted to mock DB
        db_decisions = mock_db_session.query(DecisionLog).filter(DecisionLog.strategy == "realtime_scanner").all()
        assert len(db_decisions) >= 1
        assert "velocity=" in db_decisions[0].reason


@pytest.mark.asyncio
async def test_ws_dispatcher_dynamic_subscription_update(mock_db_session, cleanup_event_bus):
    """Verify that updating strategy subscriptions triggers safe WebSocket dynamic re-subscription."""
    setup_strategy_config(mock_db_session)

    dispatcher = WSDispatcher()

    with patch_db_and_scanner(mock_db_session, ["token_1"]), \
         patch("backend.core.ws_dispatcher.PolymarketWebSocket") as mock_ws_cls:
        
        mock_ws = MagicMock()
        mock_ws.connect = AsyncMock()
        mock_ws.ws = MagicMock()
        mock_ws.ws.close = AsyncMock()
        mock_ws.config = MagicMock()
        mock_ws.config.asset_ids = ["token_1"]
        mock_ws_cls.return_value = mock_ws

        strategy = RealtimeScannerStrategy()
        strategy.subscribed_tokens = {"token_1"}
        strategy._tokens_populated = True

        with patch.dict(STRATEGY_REGISTRY, {"realtime_scanner": lambda: strategy}, clear=True):
            await dispatcher.start()
            await asyncio.sleep(0.1)

            # Dynamically add subscription
            strategy.subscribed_tokens = {"token_1", "token_2"}
            
            # Patch populate_subscribed_tokens to do nothing (already populated)
            with patch.object(strategy, "_populate_subscribed_tokens", AsyncMock()):
                await dispatcher.update_subscriptions()

                # Verify dynamic updating and re-connection trigger
                mock_ws.update_asset_ids.assert_called_once()
                mock_ws.ws.close.assert_called_once()

            await dispatcher.stop()
