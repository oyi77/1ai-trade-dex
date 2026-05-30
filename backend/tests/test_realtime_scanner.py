"""Tests for RealtimeScannerStrategy — real-time price velocity scanner."""

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from backend.strategies.realtime_scanner import (
    RealtimeScannerStrategy,
    PriceHistory,
)
from backend.strategies.base import StrategyContext, MarketInfo, CycleResult, MarketEvent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def strategy():
    s = RealtimeScannerStrategy()
    return s


def _make_ctx(params=None, mode="paper"):
    return StrategyContext(
        db=MagicMock(),
        clob=None,
        settings=MagicMock(),
        logger=MagicMock(),
        params=params or {},
        mode=mode,
    )


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


class TestRealtimeScannerMeta:
    def test_name(self, strategy):
        assert strategy.name == "realtime_scanner"

    def test_category(self, strategy):
        assert strategy.category == "edge_discovery"

    def test_default_params(self, strategy):
        params = strategy.default_params
        assert params["velocity_threshold_up"] == 0.15
        assert params["velocity_threshold_down"] == -0.15
        assert params["velocity_window_fast"] == 5
        assert params["velocity_window_med"] == 15
        assert params["velocity_window_slow"] == 30
        assert params["min_signal_interval"] == 60
        assert params["min_history_points"] == 10
        assert params["max_position_usd"] == 50.0


# ---------------------------------------------------------------------------
# PriceHistory
# ---------------------------------------------------------------------------


class TestPriceHistory:
    @pytest.mark.asyncio
    async def test_add_price(self):
        ph = PriceHistory(token_id="tok1", ticker="test")
        await ph.add_price(0.50, 1000.0)
        assert len(ph.prices) == 1

    @pytest.mark.asyncio
    async def test_velocity_insufficient_data(self):
        ph = PriceHistory(token_id="tok1", ticker="test")
        await ph.add_price(0.50, 1000.0)
        vel = await ph.get_velocity(10.0)
        assert vel is None

    @pytest.mark.asyncio
    async def test_velocity_positive(self):
        ph = PriceHistory(token_id="tok1", ticker="test")
        now = time.time()
        await ph.add_price(0.50, now - 5)
        await ph.add_price(0.55, now)
        vel = await ph.get_velocity(10.0)
        assert vel is not None
        assert vel > 0

    @pytest.mark.asyncio
    async def test_velocity_negative(self):
        ph = PriceHistory(token_id="tok1", ticker="test")
        now = time.time()
        await ph.add_price(0.55, now - 5)
        await ph.add_price(0.50, now)
        vel = await ph.get_velocity(10.0)
        assert vel is not None
        assert vel < 0

    @pytest.mark.asyncio
    async def test_maxlen_respected(self):
        ph = PriceHistory(token_id="tok1", ticker="test")
        for i in range(150):
            await ph.add_price(0.50 + i * 0.001, float(i))
        assert len(ph.prices) == 100

    @pytest.mark.asyncio
    async def test_velocity_outside_window(self):
        """If all prices are outside the window, velocity is None."""
        ph = PriceHistory(token_id="tok1", ticker="test")
        # Use very old timestamps so the newest is still outside the short window
        old = 1000.0
        await ph.add_price(0.50, old)
        await ph.add_price(0.51, old + 0.1)
        vel = await ph.get_velocity(0.01)  # 10ms window, data at t=1000
        assert vel is None


# ---------------------------------------------------------------------------
# Market filter
# ---------------------------------------------------------------------------


class TestMarketFilter:
    @pytest.mark.asyncio
    async def test_filters_by_liquidity_and_volume(self, strategy):
        markets = [
            MarketInfo(ticker="hi", slug="hi", category="crypto", end_date=None, volume=10000, liquidity=5000),
            MarketInfo(ticker="lo", slug="lo", category="crypto", end_date=None, volume=100, liquidity=50),
        ]
        filtered = await strategy.market_filter(markets)
        assert len(filtered) == 1
        assert filtered[0].ticker == "hi"

    @pytest.mark.asyncio
    async def test_empty_markets(self, strategy):
        filtered = await strategy.market_filter([])
        assert filtered == []


# ---------------------------------------------------------------------------
# on_market_event
# ---------------------------------------------------------------------------


class TestOnMarketEvent:
    @pytest.mark.asyncio
    async def test_unknown_token_returns_none(self, strategy):
        """Events from unsubscribed tokens return None."""
        event = MarketEvent(
            token_id="unknown_tok",
            event_type="last_trade_price",
            data={"price": "0.55"},
            timestamp=time.time(),
        )
        result = await strategy.on_market_event(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_price_data_returns_none(self, strategy):
        """Events without price data return None."""
        strategy.subscribed_tokens = {"tok1"}
        event = MarketEvent(
            token_id="tok1",
            event_type="last_trade_price",
            data={},
            timestamp=time.time(),
        )
        result = await strategy.on_market_event(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_insufficient_history_returns_none(self, strategy):
        """With fewer than min_history_points, no signal is generated."""
        strategy.subscribed_tokens = {"tok1"}
        strategy.default_params["min_history_points"] = 5

        event = MarketEvent(
            token_id="tok1",
            event_type="last_trade_price",
            data={"price": "0.55"},
            timestamp=time.time(),
        )
        result = await strategy.on_market_event(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_signal_generated_on_velocity_breach(self, strategy):
        """When slow velocity exceeds threshold, a BUY signal is generated."""
        strategy.subscribed_tokens = {"tok1"}
        strategy._tokens_populated = True
        strategy.default_params["min_history_points"] = 3
        strategy.default_params["velocity_threshold_up"] = 0.01
        strategy.default_params["velocity_window_slow"] = 30
        strategy.default_params["min_signal_interval"] = 0  # no cooldown

        now = time.time()
        ph = PriceHistory(token_id="tok1", ticker="test_tok")
        # Seed history with rapid price increase
        ph.prices.append((now - 5, 0.50))
        ph.prices.append((now - 3, 0.52))
        ph.prices.append((now - 1, 0.55))
        strategy._price_history["tok1"] = ph

        event = MarketEvent(
            token_id="tok1",
            event_type="last_trade_price",
            data={"price": "0.58"},
            timestamp=now,
        )

        with patch("backend.strategies.realtime_scanner.record_decision"):
            with patch("backend.db.utils.get_db_session") as mock_db:
                mock_ctx = MagicMock()
                mock_ctx.__enter__ = MagicMock(return_value=MagicMock())
                mock_ctx.__exit__ = MagicMock(return_value=False)
                mock_db.return_value = mock_ctx
                result = await strategy.on_market_event(event)

        assert result is not None
        assert result["decision"] == "BUY"
        assert result["market_ticker"] == "test_tok"


# ---------------------------------------------------------------------------
# run_cycle
# ---------------------------------------------------------------------------


class TestRunCycle:
    @pytest.mark.asyncio
    async def test_run_cycle_returns_empty_result(self, strategy):
        """run_cycle is a fallback; returns empty CycleResult."""
        ctx = _make_ctx()

        with patch.object(strategy, "_populate_subscribed_tokens", AsyncMock()):
            result = await strategy.run_cycle(ctx)

        assert isinstance(result, CycleResult)
        assert result.decisions_recorded == 0
        assert result.trades_attempted == 0
        assert result.trades_placed == 0

    @pytest.mark.asyncio
    async def test_run_wrapper(self, strategy):
        """Base run() wrapper returns valid CycleResult."""
        ctx = _make_ctx()
        with patch.object(strategy, "_populate_subscribed_tokens", AsyncMock()):
            result = await strategy.run(ctx)

        assert isinstance(result, CycleResult)
        assert result.cycle_duration_ms >= 0


# ---------------------------------------------------------------------------
# Event-driven subscription
# ---------------------------------------------------------------------------


class TestSubscriptionConfig:
    def test_subscribed_events(self, strategy):
        assert "last_trade_price" in strategy.subscribed_events
        assert "price_change" in strategy.subscribed_events
