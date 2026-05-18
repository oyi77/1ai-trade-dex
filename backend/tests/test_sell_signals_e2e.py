"""End-to-end tests for sell signal generation and routing.

Tests the sell signal pipeline built in backend/core/position_monitor.py:
- Profit-take trigger (probability > 80%)
- Stop-loss trigger (probability drops > 15pp)
- Time-decay trigger (settlement < 1 hour, marginal edge)
- Sell signal routing through auto_trader
- SHADOW_MODE compliance
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from backend.core.position_monitor import (
    OpenPositionSnapshot,
    SellSignal,
    _evaluate_sell_triggers,
    execute_sell_signals,
    PROFIT_TAKE_PROBABILITY,
    STOP_LOSS_DROP_PP,
    TIME_DECAY_MINUTES,
    SELL_SIGNAL_MIN_EDGE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trade(**overrides):
    """Create a mock Trade object with sensible defaults."""
    defaults = {
        "id": 1,
        "market_ticker": "test-market",
        "strategy": "crypto_oracle",
        "trading_mode": "paper",
        "direction": "up",
        "entry_price": 0.50,
        "size": 10.0,
        "market_price_at_entry": 0.50,
        "market_end_date": datetime.now(timezone.utc) + timedelta(hours=2),
        "timestamp": datetime.now(timezone.utc) - timedelta(minutes=30),
        "last_sync_at": datetime.now(timezone.utc) - timedelta(minutes=5),
        "settled": False,
    }
    defaults.update(overrides)
    return MagicMock(**{"get": lambda self, key, default=None: defaults.get(key, default), **defaults})


# ---------------------------------------------------------------------------
# Profit-Take Tests
# ---------------------------------------------------------------------------

class TestProfitTakeTrigger:
    def test_profit_take_fires_when_prob_above_threshold(self):
        snapshot = OpenPositionSnapshot(
            trade_id=1,
            market_ticker="btc-up",
            strategy="crypto_oracle",
            trading_mode="paper",
            direction="up",
            entry_price=0.50,
            size=10.0,
            market_price_at_entry=0.50,
            market_end_date=datetime.now(timezone.utc) + timedelta(hours=2),
            opened_at=datetime.now(timezone.utc) - timedelta(minutes=30),
            current_price=0.85,
            unrealized_pnl=7.0,
            unrealized_pnl_pct=70.0,
        )
        signal = _evaluate_sell_triggers(snapshot)
        assert signal is not None
        assert signal.trigger == "profit_take"
        assert signal.confidence > 0.7

    def test_profit_take_does_not_fire_below_threshold(self):
        snapshot = OpenPositionSnapshot(
            trade_id=1,
            market_ticker="btc-up",
            strategy="crypto_oracle",
            trading_mode="paper",
            direction="up",
            entry_price=0.50,
            size=10.0,
            market_price_at_entry=0.50,
            market_end_date=datetime.now(timezone.utc) + timedelta(hours=2),
            opened_at=datetime.now(timezone.utc) - timedelta(minutes=30),
            current_price=0.75,
            unrealized_pnl=5.0,
            unrealized_pnl_pct=50.0,
        )
        signal = _evaluate_sell_triggers(snapshot)
        # Should not fire profit_take (0.75 < 0.80), but may fire stop_loss if entry was higher
        if signal is not None:
            assert signal.trigger != "profit_take"

    def test_profit_take_requires_entry_below_threshold(self):
        """If entry was already above 80%, profit-take should not fire."""
        snapshot = OpenPositionSnapshot(
            trade_id=1,
            market_ticker="btc-up",
            strategy="crypto_oracle",
            trading_mode="paper",
            direction="up",
            entry_price=0.82,
            size=10.0,
            market_price_at_entry=0.82,
            market_end_date=datetime.now(timezone.utc) + timedelta(hours=2),
            opened_at=datetime.now(timezone.utc) - timedelta(minutes=30),
            current_price=0.85,
            unrealized_pnl=0.37,
            unrealized_pnl_pct=3.7,
        )
        signal = _evaluate_sell_triggers(snapshot)
        if signal is not None:
            assert signal.trigger != "profit_take"


# ---------------------------------------------------------------------------
# Stop-Loss Tests
# ---------------------------------------------------------------------------

class TestStopLossTrigger:
    def test_stop_loss_fires_on_large_drop(self):
        snapshot = OpenPositionSnapshot(
            trade_id=2,
            market_ticker="eth-up",
            strategy="crypto_oracle",
            trading_mode="paper",
            direction="up",
            entry_price=0.60,
            size=10.0,
            market_price_at_entry=0.60,
            market_end_date=datetime.now(timezone.utc) + timedelta(hours=2),
            opened_at=datetime.now(timezone.utc) - timedelta(minutes=30),
            current_price=0.40,
            unrealized_pnl=-3.33,
            unrealized_pnl_pct=-33.3,
        )
        signal = _evaluate_sell_triggers(snapshot)
        assert signal is not None
        assert signal.trigger == "stop_loss"
        assert signal.confidence > 0.6

    def test_stop_loss_does_not_fire_on_small_drop(self):
        snapshot = OpenPositionSnapshot(
            trade_id=2,
            market_ticker="eth-up",
            strategy="crypto_oracle",
            trading_mode="paper",
            direction="up",
            entry_price=0.60,
            size=10.0,
            market_price_at_entry=0.60,
            market_end_date=datetime.now(timezone.utc) + timedelta(hours=2),
            opened_at=datetime.now(timezone.utc) - timedelta(minutes=30),
            current_price=0.55,
            unrealized_pnl=-0.83,
            unrealized_pnl_pct=-8.3,
        )
        signal = _evaluate_sell_triggers(snapshot)
        # Drop of 0.05 < 0.15 threshold — stop_loss should not fire
        if signal is not None:
            assert signal.trigger != "stop_loss"


# ---------------------------------------------------------------------------
# Time-Decay Tests
# ---------------------------------------------------------------------------

class TestTimeDecayTrigger:
    def test_time_decay_fires_near_settlement_with_marginal_edge(self):
        now = datetime.now(timezone.utc)
        snapshot = OpenPositionSnapshot(
            trade_id=3,
            market_ticker="btc-5m",
            strategy="btc_oracle",
            trading_mode="paper",
            direction="up",
            entry_price=0.52,
            size=10.0,
            market_price_at_entry=0.52,
            market_end_date=now + timedelta(minutes=30),
            opened_at=now - timedelta(minutes=10),
            current_price=0.53,
            unrealized_pnl=0.19,
            unrealized_pnl_pct=1.9,
        )
        signal = _evaluate_sell_triggers(snapshot)
        assert signal is not None
        assert signal.trigger == "time_decay"
        assert "Time decay" in signal.reason

    def test_time_decay_does_not_fire_with_large_edge(self):
        now = datetime.now(timezone.utc)
        snapshot = OpenPositionSnapshot(
            trade_id=3,
            market_ticker="btc-5m",
            strategy="btc_oracle",
            trading_mode="paper",
            direction="up",
            entry_price=0.50,
            size=10.0,
            market_price_at_entry=0.50,
            market_end_date=now + timedelta(minutes=30),
            opened_at=now - timedelta(minutes=10),
            current_price=0.65,
            unrealized_pnl=3.0,
            unrealized_pnl_pct=30.0,
        )
        signal = _evaluate_sell_triggers(snapshot)
        # Edge of 0.15 > 0.02 threshold — time_decay should not fire
        # (profit_take may fire instead since 0.65 < 0.80, and stop_loss won't fire)
        if signal is not None:
            assert signal.trigger != "time_decay"

    def test_time_decay_does_not_fire_far_from_settlement(self):
        now = datetime.now(timezone.utc)
        snapshot = OpenPositionSnapshot(
            trade_id=3,
            market_ticker="btc-5m",
            strategy="btc_oracle",
            trading_mode="paper",
            direction="up",
            entry_price=0.52,
            size=10.0,
            market_price_at_entry=0.52,
            market_end_date=now + timedelta(hours=3),
            opened_at=now - timedelta(minutes=10),
            current_price=0.53,
            unrealized_pnl=0.19,
            unrealized_pnl_pct=1.9,
        )
        signal = _evaluate_sell_triggers(snapshot)
        # 3 hours > 60 min threshold — time_decay should not fire
        if signal is not None:
            assert signal.trigger != "time_decay"


# ---------------------------------------------------------------------------
# Routing Tests
# ---------------------------------------------------------------------------

class TestSellSignalRouting:
    @pytest.mark.asyncio
    async def test_sell_signals_route_through_execute_sell_signals(self):
        """Verify sell signals can be routed through the execution pipeline."""
        signals = [
            SellSignal(
                trade_id=1,
                market_ticker="btc-up",
                strategy="crypto_oracle",
                trading_mode="paper",
                direction="up",
                size=10.0,
                trigger="profit_take",
                reason="Test profit take",
                entry_price=0.50,
                current_price=0.85,
                unrealized_pnl=7.0,
                confidence=0.85,
            ),
        ]

        with patch("backend.core.strategy_executor.execute_decision", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = {"order_id": "test-123"}
            results = await execute_sell_signals(signals)

        assert len(results) == 1
        assert results[0]["trade_id"] == 1
        assert results[0]["trigger"] == "profit_take"
        assert results[0]["action"] == "executed"

    @pytest.mark.asyncio
    async def test_sell_signals_dry_run(self):
        """Dry-run mode should not call execute_decision."""
        signals = [
            SellSignal(
                trade_id=1,
                market_ticker="btc-up",
                strategy="crypto_oracle",
                trading_mode="paper",
                direction="up",
                size=10.0,
                trigger="stop_loss",
                reason="Test stop loss",
                entry_price=0.60,
                current_price=0.40,
                unrealized_pnl=-3.33,
                confidence=0.75,
            ),
        ]

        with patch("backend.core.strategy_executor.execute_decision", new_callable=AsyncMock) as mock_exec:
            results = await execute_sell_signals(signals, dry_run=True)

        mock_exec.assert_not_called()
        assert len(results) == 1
        assert results[0]["action"] == "dry_run"


# ---------------------------------------------------------------------------
# SHADOW_MODE Compliance Tests
# ---------------------------------------------------------------------------

class TestShadowModeCompliance:
    def test_sell_signal_has_trading_mode(self):
        """All sell signals carry trading_mode for SHADOW_MODE routing."""
        snapshot = OpenPositionSnapshot(
            trade_id=1,
            market_ticker="btc-up",
            strategy="crypto_oracle",
            trading_mode="paper",
            direction="up",
            entry_price=0.50,
            size=10.0,
            market_price_at_entry=0.50,
            market_end_date=datetime.now(timezone.utc) + timedelta(hours=2),
            opened_at=datetime.now(timezone.utc) - timedelta(minutes=30),
            current_price=0.85,
            unrealized_pnl=7.0,
            unrealized_pnl_pct=70.0,
        )
        signal = _evaluate_sell_triggers(snapshot)
        assert signal is not None
        assert signal.trading_mode == "paper"

    @pytest.mark.asyncio
    async def test_shadow_mode_preserved_in_execution(self):
        """Execution pipeline preserves shadow mode in results."""
        signals = [
            SellSignal(
                trade_id=1,
                market_ticker="btc-up",
                strategy="crypto_oracle",
                trading_mode="paper",
                direction="up",
                size=10.0,
                trigger="profit_take",
                reason="Test",
                entry_price=0.50,
                current_price=0.85,
                unrealized_pnl=7.0,
                confidence=0.85,
            ),
        ]

        with patch("backend.core.strategy_executor.execute_decision", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = {"order_id": "test-123"}
            with patch("backend.core.position_monitor.settings") as mock_settings:
                mock_settings.SHADOW_MODE = True
                results = await execute_sell_signals(signals)

        assert len(results) == 1
        assert results[0]["shadow_mode"] is True


# ---------------------------------------------------------------------------
# Config Tests
# ---------------------------------------------------------------------------

class TestConfigSettings:
    def test_profit_take_threshold_default(self):
        assert PROFIT_TAKE_PROBABILITY == 0.80

    def test_stop_loss_drop_default(self):
        assert STOP_LOSS_DROP_PP == 0.15

    def test_time_decay_minutes_default(self):
        assert TIME_DECAY_MINUTES == 60

    def test_sell_signal_min_edge_default(self):
        assert SELL_SIGNAL_MIN_EDGE == 0.02
