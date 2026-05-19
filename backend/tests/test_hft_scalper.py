"""Tests for HFT Momentum Scalper Strategy."""
import time
from collections import deque
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.strategies.hft_scalper import (
    HFTScalperStrategy,
    ScalpPosition,
)
from backend.strategies.base import MarketInfo, StrategyContext


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def strategy():
    return HFTScalperStrategy()


@pytest.fixture
def mock_ctx():
    ctx = MagicMock(spec=StrategyContext)
    ctx.db = MagicMock()
    ctx.clob = AsyncMock()
    ctx.settings = MagicMock()
    ctx.logger = MagicMock()
    ctx.params = {}
    ctx.mode = "paper"
    ctx.clob.get_markets = AsyncMock(return_value=[])
    ctx.clob.get_usdc_balance = AsyncMock(return_value=1000.0)
    ctx.clob.place_limit_order = AsyncMock(return_value=MagicMock(success=True, order_id="order_1"))
    return ctx


def _make_market(ticker="tok_1", volume=5000, liquidity=2000, best_bid=0.48, best_ask=0.52):
    return MarketInfo(
        ticker=ticker,
        slug=f"slug-{ticker}",
        category="crypto",
        end_date=None,
        volume=volume,
        liquidity=liquidity,
        metadata={"bestBid": best_bid, "bestAsk": best_ask, "midpoint": (best_bid + best_ask) / 2},
    )


def _seed_price_history(strategy, ticker, prices, start=None):
    """Insert price ticks into the strategy's rolling history."""
    base = start or time.time() - len(prices)
    history = strategy._price_history[ticker]
    for i, p in enumerate(prices):
        history.append((base + i, p))


# ---------------------------------------------------------------------------
# Momentum detection
# ---------------------------------------------------------------------------

class TestDetectMomentum:
    def test_positive_momentum_detected(self, strategy):
        """Consecutive upward ticks exceeding threshold produce BUY_YES."""
        now = time.time()
        prices = deque([(now - 2, 0.50), (now - 1, 0.505), (now, 0.512)])
        direction, move = strategy.detect_momentum(prices, strategy.default_params)
        assert direction == "BUY_YES"
        assert move >= strategy.default_params["entry_threshold"]

    def test_negative_momentum_detected(self, strategy):
        """Consecutive downward ticks exceeding threshold produce BUY_NO."""
        now = time.time()
        prices = deque([(now - 2, 0.512), (now - 1, 0.505), (now, 0.50)])
        direction, move = strategy.detect_momentum(prices, strategy.default_params)
        assert direction == "BUY_NO"
        assert move >= strategy.default_params["entry_threshold"]

    def test_no_signal_mixed_direction(self, strategy):
        """Mixed up/down ticks produce no signal."""
        prices = deque([(0, 0.50), (1, 0.51), (2, 0.505)])
        direction, move = strategy.detect_momentum(prices, strategy.default_params)
        assert direction is None

    def test_no_signal_below_threshold(self, strategy):
        """Small moves below threshold produce no signal."""
        prices = deque([(0, 0.50), (1, 0.501), (2, 0.502)])
        direction, move = strategy.detect_momentum(prices, strategy.default_params)
        assert direction is None

    def test_insufficient_history(self, strategy):
        """Too few ticks returns no signal."""
        prices = deque([(0, 0.50)])
        direction, move = strategy.detect_momentum(prices, strategy.default_params)
        assert direction is None

    def test_stale_ticks_filtered(self, strategy):
        """Ticks outside lookback window are ignored."""
        old_time = time.time() - 60  # 60s ago, beyond 30s lookback
        prices = deque([
            (old_time, 0.50),
            (old_time + 1, 0.505),
            (old_time + 2, 0.512),
        ])
        direction, move = strategy.detect_momentum(prices, strategy.default_params)
        assert direction is None


# ---------------------------------------------------------------------------
# Exit conditions
# ---------------------------------------------------------------------------

class TestCheckExit:
    def _make_position(self, direction="BUY_YES", entry_price=0.50, opened_at=None):
        return ScalpPosition(
            position_id="pos_1",
            market_id="tok_1",
            ticker="tok_1",
            direction=direction,
            entry_price=entry_price,
            size_usd=50.0,
            opened_at=opened_at or time.monotonic(),
        )

    def test_take_profit_yes(self, strategy):
        """BUY_YES position hitting profit target exits with TAKE_PROFIT."""
        pos = self._make_position("BUY_YES", 0.50)
        # 0.8% profit: 0.50 * 1.008 = 0.504
        reason, pnl = strategy.check_exit(pos, 0.504, strategy.default_params)
        assert reason == "TAKE_PROFIT"
        assert pnl > 0

    def test_take_profit_no(self, strategy):
        """BUY_NO position hitting profit target exits with TAKE_PROFIT."""
        pos = self._make_position("BUY_NO", 0.50)
        # Price drops 0.8%: 0.50 * 0.992 = 0.496
        reason, pnl = strategy.check_exit(pos, 0.496, strategy.default_params)
        assert reason == "TAKE_PROFIT"
        assert pnl > 0

    def test_stop_loss_yes(self, strategy):
        """BUY_YES position hitting stop loss exits with STOP_LOSS."""
        pos = self._make_position("BUY_YES", 0.50)
        # 0.8% loss: 0.50 * 0.992 = 0.496
        reason, pnl = strategy.check_exit(pos, 0.496, strategy.default_params)
        assert reason == "STOP_LOSS"
        assert pnl < 0

    def test_stop_loss_no(self, strategy):
        """BUY_NO position hitting stop loss exits with STOP_LOSS."""
        pos = self._make_position("BUY_NO", 0.50)
        # Price rises 0.8%: 0.50 * 1.008 = 0.504
        reason, pnl = strategy.check_exit(pos, 0.504, strategy.default_params)
        assert reason == "STOP_LOSS"
        assert pnl < 0

    def test_time_exit(self, strategy):
        """Position exceeding max hold time exits with TIME_EXIT."""
        pos = self._make_position("BUY_YES", 0.50, opened_at=time.monotonic() - 20)
        # Price unchanged
        reason, pnl = strategy.check_exit(pos, 0.50, strategy.default_params)
        assert reason == "TIME_EXIT"

    def test_no_exit_within_bounds(self, strategy):
        """Position within thresholds and time holds."""
        pos = self._make_position("BUY_YES", 0.50)
        reason, pnl = strategy.check_exit(pos, 0.501, strategy.default_params)
        assert reason is None


# ---------------------------------------------------------------------------
# Position management
# ---------------------------------------------------------------------------

class TestPositionManagement:
    def test_close_position_updates_state(self, strategy):
        """Closing a position removes from open, adds to closed, sets cooldown."""
        pos = ScalpPosition(
            position_id="pos_1",
            market_id="tok_1",
            ticker="tok_1",
            direction="BUY_YES",
            entry_price=0.50,
            size_usd=50.0,
            opened_at=time.monotonic() - 5,
        )
        strategy._open_positions["tok_1"] = pos

        closed = strategy._close_position(pos, 0.505, "TAKE_PROFIT")

        assert "tok_1" not in strategy._open_positions
        assert len(strategy._closed_positions) == 1
        assert closed.pnl_pct > 0
        assert closed.exit_reason == "TAKE_PROFIT"
        assert "tok_1" in strategy._cooldowns

    def test_daily_pnl_tracking(self, strategy):
        """Wins and losses accumulate in daily PnL."""
        strategy._daily_pnl_day = time.strftime("%Y-%m-%d", time.gmtime())
        pos = ScalpPosition(
            position_id="pos_1",
            market_id="tok_1",
            ticker="tok_1",
            direction="BUY_YES",
            entry_price=0.50,
            size_usd=50.0,
            opened_at=time.monotonic() - 5,
        )
        strategy._open_positions["tok_1"] = pos
        strategy._close_position(pos, 0.51, "TAKE_PROFIT")
        assert strategy._daily_pnl > 0


# ---------------------------------------------------------------------------
# Risk controls
# ---------------------------------------------------------------------------

class TestRiskGates:
    def test_max_concurrent_positions(self, strategy):
        """Blocks entry when at max concurrent positions."""
        params = strategy.default_params
        now = time.time()
        for i in range(params["max_concurrent_positions"]):
            strategy._open_positions[f"tok_{i}"] = MagicMock()

        market = _make_market("tok_new")
        reason = strategy._passes_risk_gates(market, 0.50, 1000.0, params, now)
        assert reason == "max_concurrent_positions"

    def test_daily_loss_limit(self, strategy):
        """Blocks entry when daily loss exceeds limit."""
        params = strategy.default_params
        now = time.time()
        strategy._daily_pnl_day = time.strftime("%Y-%m-%d", time.gmtime(now))
        strategy._daily_pnl = -40.0  # 4% of 1000 bankroll > 3% limit

        market = _make_market("tok_1")
        reason = strategy._passes_risk_gates(market, 0.50, 1000.0, params, now)
        assert reason == "daily_loss_limit"

    def test_low_volume_rejected(self, strategy):
        """Rejects markets below min volume."""
        params = strategy.default_params
        now = time.time()
        market = _make_market(volume=100)

        reason = strategy._passes_risk_gates(market, 0.50, 1000.0, params, now)
        assert reason == "low_volume"

    def test_wide_spread_rejected(self, strategy):
        """Rejects markets with spread exceeding max."""
        params = strategy.default_params
        now = time.time()
        market = _make_market(best_bid=0.40, best_ask=0.60)  # 20% spread > 5% max

        reason = strategy._passes_risk_gates(market, 0.50, 1000.0, params, now)
        assert reason == "wide_spread"

    def test_cooldown_blocks_reentry(self, strategy):
        """Blocks re-entry during cooldown period."""
        params = strategy.default_params
        now = time.time()
        strategy._cooldowns["tok_1"] = now - 2  # 2s ago < 5s cooldown

        market = _make_market("tok_1")
        reason = strategy._passes_risk_gates(market, 0.50, 1000.0, params, now)
        assert reason == "cooldown"

    def test_already_in_position(self, strategy):
        """Blocks entry if already holding position on market."""
        params = strategy.default_params
        now = time.time()
        strategy._open_positions["tok_1"] = MagicMock()

        market = _make_market("tok_1")
        reason = strategy._passes_risk_gates(market, 0.50, 1000.0, params, now)
        assert reason == "already_in_position"

    def test_passes_all_gates(self, strategy):
        """Returns None when all risk gates pass."""
        params = strategy.default_params
        now = time.time()
        market = _make_market("tok_new")

        reason = strategy._passes_risk_gates(market, 0.50, 1000.0, params, now)
        assert reason is None


# ---------------------------------------------------------------------------
# Kelly sizing
# ---------------------------------------------------------------------------

class TestKellySizing:
    def test_insufficient_data_uses_conservative_size(self, strategy):
        """With < 5 closed trades, returns conservative fixed size."""
        size = strategy._kelly_size(1000.0, strategy.default_params)
        assert size <= strategy.default_params["max_position_usd"]
        assert size > 0

    def test_scales_with_win_rate(self, strategy):
        """Higher win rate produces larger position size."""
        # Seed losing history
        for _ in range(10):
            p = ScalpPosition(
                position_id="", market_id="", ticker="",
                direction="BUY_YES", entry_price=0.50, size_usd=50,
                opened_at=0, pnl_pct=-0.01, pnl_usd=-0.50,
            )
            strategy._closed_positions.append(p)

        bad_size = strategy._kelly_size(1000.0, strategy.default_params)

        # Clear and seed winning history
        strategy._closed_positions.clear()
        for _ in range(10):
            p = ScalpPosition(
                position_id="", market_id="", ticker="",
                direction="BUY_YES", entry_price=0.50, size_usd=50,
                opened_at=0, pnl_pct=0.01, pnl_usd=0.50,
            )
            strategy._closed_positions.append(p)

        good_size = strategy._kelly_size(1000.0, strategy.default_params)
        assert good_size > bad_size

    def test_capped_at_max_position(self, strategy):
        """Size never exceeds max_position_usd."""
        strategy._closed_positions.clear()
        for _ in range(20):
            p = ScalpPosition(
                position_id="", market_id="", ticker="",
                direction="BUY_YES", entry_price=0.50, size_usd=50,
                opened_at=0, pnl_pct=0.05, pnl_usd=2.50,
            )
            strategy._closed_positions.append(p)

        size = strategy._kelly_size(100_000.0, strategy.default_params)
        assert size <= strategy.default_params["max_position_usd"]


# ---------------------------------------------------------------------------
# Strategy stats
# ---------------------------------------------------------------------------

class TestStats:
    def test_get_stats_empty(self, strategy):
        """Stats report correctly with no trades."""
        stats = strategy.get_stats()
        assert stats["total_trades"] == 0
        assert stats["win_rate"] == 0.5
        assert stats["open_positions"] == 0

    def test_get_stats_with_trades(self, strategy):
        """Stats reflect closed and open positions."""
        strategy._closed_positions.append(
            ScalpPosition(
                position_id="", market_id="", ticker="",
                direction="BUY_YES", entry_price=0.50, size_usd=50,
                opened_at=0, pnl_pct=0.01, pnl_usd=0.50,
            )
        )
        strategy._open_positions["tok_1"] = MagicMock()

        stats = strategy.get_stats()
        assert stats["total_trades"] == 1
        assert stats["wins"] == 1
        assert stats["open_positions"] == 1


# ---------------------------------------------------------------------------
# Full cycle integration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestRunCycle:
    async def test_empty_cycle_no_markets(self, strategy, mock_ctx):
        """Cycle with no markets returns zero results without error."""
        mock_ctx.clob.get_markets = AsyncMock(return_value=[])
        result = await strategy.run_cycle(mock_ctx)
        assert result.trades_attempted == 0
        assert result.trades_placed == 0
        assert result.errors == []

    async def test_cycle_records_decisions_on_signal(self, strategy, mock_ctx):
        """Cycle detects momentum and records a BUY decision."""
        # Seed price history that shows clear upward momentum (recent timestamps)
        now = time.time()
        _seed_price_history(strategy, "tok_1", [0.50, 0.505], start=now - 2)

        raw_market = {
            "conditionId": "tok_1",
            "slug": "test-market",
            "category": "crypto",
            "endDate": None,
            "volume24hr": 5000,
            "liquidity": 2000,
            "midpoint": 0.514,
            "bestBid": 0.512,
            "bestAsk": 0.516,
        }
        mock_ctx.clob.get_markets = AsyncMock(return_value=[raw_market])

        result = await strategy.run_cycle(mock_ctx)
        assert result.decisions_recorded >= 1

    async def test_cycle_closes_expired_positions(self, strategy, mock_ctx):
        """Cycle closes positions that exceeded max hold time."""
        pos = ScalpPosition(
            position_id="pos_old",
            market_id="tok_old",
            ticker="tok_old",
            direction="BUY_YES",
            entry_price=0.50,
            size_usd=50.0,
            opened_at=time.monotonic() - 100,  # well past 15s limit
        )
        strategy._open_positions["tok_old"] = pos
        _seed_price_history(strategy, "tok_old", [0.50, 0.501, 0.502])

        mock_ctx.clob.get_markets = AsyncMock(return_value=[])
        result = await strategy.run_cycle(mock_ctx)

        assert "tok_old" not in strategy._open_positions
        assert len(strategy._closed_positions) == 1
