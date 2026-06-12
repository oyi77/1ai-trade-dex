"""Tests for APEX strategy integration."""

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.edge.edge_types import EdgeType
from backend.core.edge.edge_model import Signal as APEXSignal


class TestAPEXStrategy:
    @pytest.fixture
    def strategy(self):
        from backend.strategies.apex_strategy import APEXStrategy
        return APEXStrategy()

    def test_name_and_category(self, strategy):
        assert strategy.name == "apex"
        assert strategy.category == "value"

    def test_default_params(self, strategy):
        assert "min_edge_pp" in strategy.default_params
        assert "min_confidence" in strategy.default_params
        assert "max_concurrent" in strategy.default_params

    def test_signal_to_decision_high_edge(self, strategy):
        """High edge signal produces a valid decision."""
        sig = APEXSignal(
            market_id="TEST",
            token_id="0x1",
            edge_type=EdgeType.RESOLUTION_TIMING,
            direction="yes",
            entry_price=0.55,
            fair_price=0.65,
            edge_pp=10.0,
            confidence=0.75,
            edge_score=7.5,
            size_usd=8.0,
            expected_value=0.80,
            time_horizon_min=60,
            profit_target_pct=0.025,
            stop_loss_pct=0.04,
            max_hold_seconds=3600,
        )
        ctx = MagicMock()
        ctx.params = {}
        ctx.bankroll = 100.0

        decision = strategy._signal_to_decision(sig, ctx)
        assert decision is not None
        assert decision["strategy_name"] == "apex"
        assert decision["decision"] == "BUY"

    def test_signal_to_decision_low_confidence_filtered(self, strategy):
        sig = APEXSignal(
            market_id="TEST", token_id="0x1",
            edge_type=EdgeType.RESOLUTION_TIMING,
            direction="yes", entry_price=0.55, fair_price=0.60,
            edge_pp=5.0, confidence=0.3, edge_score=1.5,
            size_usd=5.0, expected_value=0.25,
            time_horizon_min=60,
            profit_target_pct=0.025, stop_loss_pct=0.04,
            max_hold_seconds=3600,
        )
        ctx = MagicMock()
        ctx.params = {}
        ctx.bankroll = 100.0
        decision = strategy._signal_to_decision(sig, ctx)
        assert decision is None

    def test_signal_to_decision_low_edge_filtered(self, strategy):
        sig = APEXSignal(
            market_id="TEST", token_id="0x1",
            edge_type=EdgeType.RESOLUTION_TIMING,
            direction="yes", entry_price=0.55, fair_price=0.57,
            edge_pp=1.5, confidence=0.8, edge_score=1.2,
            size_usd=5.0, expected_value=0.075,
            time_horizon_min=60,
            profit_target_pct=0.025, stop_loss_pct=0.04,
            max_hold_seconds=3600,
        )
        ctx = MagicMock()
        ctx.params = {}
        ctx.bankroll = 100.0
        decision = strategy._signal_to_decision(sig, ctx)
        assert decision is None

    def test_signal_to_decision_position_sizing(self, strategy):
        sig = APEXSignal(
            market_id="TEST", token_id="0x1",
            edge_type=EdgeType.RESOLUTION_TIMING,
            direction="yes", entry_price=0.55, fair_price=0.65,
            edge_pp=10.0, confidence=0.75, edge_score=7.5,
            size_usd=80.0, expected_value=8.0,
            time_horizon_min=60,
            profit_target_pct=0.025, stop_loss_pct=0.04,
            max_hold_seconds=3600,
        )
        ctx = MagicMock()
        ctx.params = {}
        ctx.bankroll = 1000.0
        decision = strategy._signal_to_decision(sig, ctx)
        assert decision is not None
        # size_usd should be capped at bankroll_pct * bankroll = 0.08 * 1000 = 80
        assert decision["size"] == 80.0

    def test_get_existing_positions_includes_unresolved_settled(self, strategy, db):
        """settled=True with pnl=NULL is a stale-marked but financially open
        position (see ADR-016) and must still count as "held"."""
        from backend.models.database import Trade

        db.add_all([
            # Open position, never settled.
            Trade(market_ticker="MKT-OPEN", strategy="apex", trading_mode="paper",
                  settled=False, pnl=None, direction="yes", entry_price=0.5, size=10.0),
            # Stale-marked by cleanup job, pending Gamma resolution (ADR-016 limbo).
            Trade(market_ticker="MKT-LIMBO", strategy="apex", trading_mode="paper",
                  settled=True, pnl=None, direction="yes", entry_price=0.5, size=10.0),
            # Fully resolved - no longer an open position.
            Trade(market_ticker="MKT-RESOLVED", strategy="apex", trading_mode="paper",
                  settled=True, pnl=5.0, result="win", direction="yes", entry_price=0.5, size=10.0),
            # Different strategy on the same market - irrelevant to apex.
            Trade(market_ticker="MKT-OTHER", strategy="longshot_bias", trading_mode="paper",
                  settled=False, pnl=None, direction="yes", entry_price=0.5, size=10.0),
        ])
        db.commit()

        ctx = MagicMock()
        ctx.db = db
        ctx.mode = "paper"

        positions = set(strategy._get_existing_positions(ctx))
        assert positions == {"MKT-OPEN", "MKT-LIMBO"}

    @pytest.mark.asyncio
    async def test_run_cycle_skips_existing_positions(self, strategy, db):
        """Phase 4 must not generate a BUY decision for a market apex already
        holds (including ADR-016 settled=True/pnl=NULL limbo positions)."""
        from backend.models.database import Trade
        from backend.strategies.base import StrategyContext

        db.add(Trade(market_ticker="MKT-HELD", strategy="apex", trading_mode="paper",
                      settled=True, pnl=None, direction="yes", entry_price=0.5, size=10.0))
        db.commit()

        strategy._ensure_initialized()

        def _signal(market_id, token_id):
            return APEXSignal(
                market_id=market_id, token_id=token_id,
                edge_type=EdgeType.RESOLUTION_TIMING,
                direction="yes", entry_price=0.55, fair_price=0.65,
                edge_pp=10.0, confidence=0.75, edge_score=7.5,
                size_usd=8.0, expected_value=0.80,
                time_horizon_min=60,
                profit_target_pct=0.025, stop_loss_pct=0.04,
                max_hold_seconds=3600,
            )

        strategy._calibration.refresh_from_db = AsyncMock(return_value=None)
        strategy._check_exits = AsyncMock(return_value=[])
        strategy._registry.run_all = AsyncMock(return_value=["edge_placeholder"])
        strategy._pipeline.evaluate = AsyncMock(return_value=[
            _signal("MKT-HELD", "0xHELD"),
            _signal("MKT-NEW", "0xNEW"),
        ])

        ctx = StrategyContext(
            db=db, clob=None, settings=None, logger=None,
            params={}, mode="paper", bankroll=100.0,
        )

        result = await strategy.run_cycle(ctx)

        tickers = [d["market_ticker"] for d in result.decisions if d.get("decision") == "BUY"]
        assert "MKT-HELD" not in tickers
        assert "MKT-NEW" in tickers


class TestAPEXClosePosition:
    """ADR-017: APEX's own exit signals (profit target / stop loss / time
    decay) must actually settle the Trade with a partial early-exit P&L,
    not just emit a dead 'SELL' decision dict."""

    @pytest.fixture
    def strategy(self):
        from backend.strategies.apex_strategy import APEXStrategy
        s = APEXStrategy()
        s._ensure_initialized()
        return s

    def _open_trade(self, db, **kw):
        from backend.models.database import Trade
        defaults = dict(
            market_ticker="MKT-EXIT", strategy="apex", trading_mode="paper",
            direction="yes", entry_price=0.50, size=10.0, token_id="0xEXIT",
            settled=False, pnl=None, timestamp=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        defaults.update(kw)
        trade = Trade(**defaults)
        db.add(trade)
        db.commit()
        return trade

    @pytest.mark.asyncio
    async def test_close_position_profit_target_paper(self, strategy, db):
        from backend.core.edge.edge_model import ExitSignal
        from backend.core.edge.edge_model import ExitReason
        from backend.strategies.base import StrategyContext

        trade = self._open_trade(db)
        sig = ExitSignal(
            trade_id=trade.id, market_id=trade.market_ticker,
            reason=ExitReason.PROFIT_TARGET, exit_price=0.58, urgency=0.6,
            edge_at_entry=5.0, current_edge=0.0,
        )
        ctx = StrategyContext(db=db, clob=None, settings=None, logger=None, params={}, mode="paper", bankroll=100.0)

        closed = await strategy._close_position(sig, ctx)

        assert closed is not None
        assert closed["result"] == "win"
        assert closed["pnl"] == pytest.approx(0.79)
        db.refresh(trade)
        assert trade.settled is True
        assert trade.pnl == pytest.approx(0.79)
        assert trade.result == "win"
        assert trade.settlement_source == "early_exit_profit_target"
        assert trade.settlement_time is not None

    @pytest.mark.asyncio
    async def test_close_position_stop_loss_paper(self, strategy, db):
        from backend.core.edge.edge_model import ExitSignal
        from backend.core.edge.edge_model import ExitReason
        from backend.strategies.base import StrategyContext

        trade = self._open_trade(db)
        sig = ExitSignal(
            trade_id=trade.id, market_id=trade.market_ticker,
            reason=ExitReason.STOP_LOSS, exit_price=0.42, urgency=0.9,
            edge_at_entry=5.0, current_edge=0.0,
        )
        ctx = StrategyContext(db=db, clob=None, settings=None, logger=None, params={}, mode="paper", bankroll=100.0)

        closed = await strategy._close_position(sig, ctx)

        assert closed is not None
        assert closed["result"] == "loss"
        assert closed["pnl"] == pytest.approx(-0.81)
        db.refresh(trade)
        assert trade.settled is True
        assert trade.result == "loss"
        assert trade.settlement_source == "early_exit_stop_loss"

    @pytest.mark.asyncio
    async def test_close_position_already_settled_is_noop(self, strategy, db):
        """A trade that is fully settled (settled=True, pnl set) must not be
        re-closed — calculate_exit_pnl would double-charge fees and overwrite
        the original settlement pnl."""
        from backend.core.edge.edge_model import ExitSignal
        from backend.core.edge.edge_model import ExitReason
        from backend.strategies.base import StrategyContext

        trade = self._open_trade(db, settled=True, pnl=5.0, result="win",
                                  settlement_source="gamma_resolution")
        sig = ExitSignal(
            trade_id=trade.id, market_id=trade.market_ticker,
            reason=ExitReason.PROFIT_TARGET, exit_price=0.58, urgency=0.6,
            edge_at_entry=5.0, current_edge=0.0,
        )
        ctx = StrategyContext(db=db, clob=None, settings=None, logger=None, params={}, mode="paper", bankroll=100.0)

        closed = await strategy._close_position(sig, ctx)

        assert closed is None
        db.refresh(trade)
        assert trade.pnl == 5.0
        assert trade.settlement_source == "gamma_resolution"

    @pytest.mark.asyncio
    async def test_run_cycle_closes_profit_target_position(self, strategy, db):
        """End-to-end Phase 1: an open position whose mid-price has rallied
        past profit_target_pct gets closed via run_cycle, producing a SELL
        decision with realized pnl/result."""
        from backend.strategies.base import StrategyContext

        trade = self._open_trade(db)

        mock_clob = AsyncMock()
        mock_clob.get_mid_price = AsyncMock(return_value=0.58)

        strategy._calibration.refresh_from_db = AsyncMock(return_value=None)
        strategy._registry.run_all = AsyncMock(return_value=[])

        ctx = StrategyContext(db=db, clob=mock_clob, settings=None, logger=None, params={}, mode="paper", bankroll=100.0)

        result = await strategy.run_cycle(ctx)

        sell_decisions = [d for d in result.decisions if d.get("decision") == "SELL"]
        assert len(sell_decisions) == 1
        assert sell_decisions[0]["exit_reason"] == "profit_target"
        assert sell_decisions[0]["result"] == "win"
        assert sell_decisions[0]["pnl"] == pytest.approx(0.79)

        db.refresh(trade)
        assert trade.settled is True
        assert trade.result == "win"

    @pytest.mark.asyncio
    async def test_close_position_live_blocked_by_gate_stays_open(self, strategy, db):
        """A strategy not yet promoted to 'live' (the default — apex is
        paper-only) must not place real CLOB orders; the position is left
        open for retry next cycle (ADR-017)."""
        from backend.core.edge.edge_model import ExitSignal
        from backend.core.edge.edge_model import ExitReason
        from backend.strategies.base import StrategyContext

        trade = self._open_trade(db, trading_mode="live")
        sig = ExitSignal(
            trade_id=trade.id, market_id=trade.market_ticker,
            reason=ExitReason.PROFIT_TARGET, exit_price=0.58, urgency=0.6,
            edge_at_entry=5.0, current_edge=0.0,
        )
        mock_clob = AsyncMock()
        ctx = StrategyContext(db=db, clob=mock_clob, settings=None, logger=None, params={}, mode="live", bankroll=100.0)

        closed = await strategy._close_position(sig, ctx)

        assert closed is None
        mock_clob.place_limit_order.assert_not_called()
        db.refresh(trade)
        assert trade.settled is False
        assert trade.pnl is None