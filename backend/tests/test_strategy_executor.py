"""Tests for backend.core.strategy_executor — strategy decision → trade pipeline."""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ---------------------------------------------------------------------------
# Stub heavy scheduler deps before any app imports
# ---------------------------------------------------------------------------
_sched_stub = MagicMock()
_sched_stub.start_scheduler = MagicMock()
_sched_stub.stop_scheduler = MagicMock()
_sched_stub.log_event = MagicMock()
_sched_stub.is_scheduler_running = MagicMock(return_value=False)
sys.modules.setdefault("apscheduler", MagicMock())
sys.modules.setdefault("apscheduler.schedulers", MagicMock())
sys.modules.setdefault("apscheduler.schedulers.asyncio", MagicMock())
sys.modules["backend.core.scheduler"] = _sched_stub

# ---------------------------------------------------------------------------
# In-memory DB wiring (mirrors conftest pattern)
# ---------------------------------------------------------------------------
from backend.models import database as _db_mod  # noqa: E402
from backend.models.database import Base, BotState  # noqa: E402

_test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSession = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)

_db_mod.engine = _test_engine
_db_mod.SessionLocal = _TestSession

Base.metadata.create_all(bind=_test_engine)
try:
    _db_mod.ensure_schema()
except Exception:
    pass

try:
    from backend.core import heartbeat as _hb

    _hb.SessionLocal = _TestSession
except Exception:
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_state(db, bankroll=1000.0, paper_bankroll=1000.0, is_running=True, mode="paper"):
    """Insert or reset BotState for a test."""
    state = db.query(BotState).filter_by(mode=mode).first()
    if state:
        state.bankroll = bankroll
        state.paper_bankroll = paper_bankroll
        state.is_running = is_running
        state.total_trades = 0
    else:
        state = BotState(
            id=1,
            mode=mode,
            bankroll=bankroll,
            paper_bankroll=paper_bankroll,
            is_running=is_running,
            total_trades=0,
            winning_trades=0,
            total_pnl=0.0,
        )
        db.add(state)
    db.commit()
    return state


def _make_decision(**overrides) -> dict:
    base = {
        "market_ticker": "test-market-001",
        "direction": "yes",
        "size": 5.0,
        "entry_price": 0.55,
        "edge": 0.08,
        "confidence": 0.75,
        "model_probability": 0.63,
        "platform": "polymarket",
        "reasoning": "test signal",
        "token_id": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPaperTradeCreatesRecord:
    @pytest.mark.asyncio
    async def test_paper_trade_creates_record(self):
        """In paper mode, execute_decision creates a Trade row in the DB."""
        from backend.models.database import Trade, Signal, TradeAttempt
        from backend.core.mode_context import register_context, ModeExecutionContext
        from backend.core.risk_manager import RiskManager

        db = _TestSession()
        _seed_state(db)
        db.close()

        mock_clob = AsyncMock()
        mock_rm = RiskManager()
        register_context("paper", ModeExecutionContext(
            mode="paper",
            clob_client=mock_clob,
            risk_manager=mock_rm,
            strategy_configs={}
        ))

        with (
            patch("backend.core.strategy_executor.settings") as mock_settings,
            patch("backend.db.utils.SessionLocal", _TestSession),
            patch("backend.core.strategy_executor._broadcast_event"),
        ):
            mock_settings.TRADING_MODE = "paper"

            from backend.core.strategy_executor import execute_decision

            result = await execute_decision(_make_decision(), "test_strategy", "paper")

        assert result is not None
        assert result["market_ticker"] == "test-market-001"
        assert result["fill_price"] == pytest.approx(0.55, abs=0.01)

        check_db = _TestSession()
        try:
            trade = (
                check_db.query(Trade)
                .filter(Trade.market_ticker == "test-market-001")
                .first()
            )
            assert trade is not None
            assert trade.strategy == "test_strategy"
            assert trade.direction == "yes"
            assert trade.trading_mode == "paper"

            sig = (
                check_db.query(Signal)
                .filter(Signal.market_ticker == "test-market-001")
                .first()
            )
            assert sig is not None
            assert sig.executed is True

            attempt = (
                check_db.query(TradeAttempt)
                .filter(TradeAttempt.market_ticker == "test-market-001")
                .first()
            )
            assert attempt is not None
            assert attempt.status == "EXECUTED"
            assert attempt.reason_code == "EXECUTED_TRADE_OPENED"
            assert attempt.trade_id == trade.id
        finally:
            check_db.close()


class TestRiskRejection:
    @pytest.mark.asyncio
    async def test_risk_rejection_returns_none(self):
        """RiskManager rejection causes execute_decision to return None."""
        from backend.core.risk_manager import RiskDecision, RiskManager
        from backend.core.mode_context import register_context, ModeExecutionContext

        test_engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        TestSession = sessionmaker(bind=test_engine)
        Base.metadata.create_all(bind=test_engine)

        db = TestSession()
        _seed_state(db)
        db.close()

        mock_rm = MagicMock(spec=RiskManager)
        mock_rm.validate_trade.return_value = RiskDecision(
            allowed=False, reason="daily loss limit hit", adjusted_size=0.0
        )

        mock_clob = AsyncMock()
        register_context("paper", ModeExecutionContext(
            mode="paper",
            clob_client=mock_clob,
            risk_manager=mock_rm,
            strategy_configs={}
        ))

        with (
            patch("backend.core.strategy_executor.settings") as mock_settings,
            patch("backend.db.utils.SessionLocal", TestSession),
            patch("backend.core.strategy_executor._broadcast_event"),
        ):
            mock_settings.TRADING_MODE = "paper"

            from backend.core.strategy_executor import execute_decision

            result = await execute_decision(
                _make_decision(market_ticker="reject-market"), "test_strategy", "paper"
            )
            assert result is None
            mock_rm.validate_trade.assert_called_once()

        check_db = TestSession()
        try:
            from backend.models.database import TradeAttempt

            attempt = (
                check_db.query(TradeAttempt)
                .filter(TradeAttempt.market_ticker == "reject-market")
                .first()
            )
            assert attempt is not None
            assert attempt.status == "REJECTED"
            assert attempt.phase == "risk_gate"
            assert attempt.reason_code == "REJECTED_DRAWDOWN_BREAKER"
            assert attempt.risk_allowed is False
            assert attempt.risk_reason == "daily loss limit hit"
        finally:
            check_db.close()


class TestBotStateLockHandling:
    @pytest.mark.asyncio
    async def test_preflight_bot_state_read_does_not_lock_before_risk_rejection(self):
        """Risk-rejected trades should not acquire BotState FOR UPDATE during preflight."""
        from backend.core.risk_manager import RiskDecision, RiskManager
        from backend.core.mode_context import register_context, ModeExecutionContext

        test_engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        TestSession = sessionmaker(bind=test_engine)
        Base.metadata.create_all(bind=test_engine)

        db = TestSession()
        _seed_state(db)
        db.close()

        mock_rm = MagicMock(spec=RiskManager)
        mock_rm.validate_trade.return_value = RiskDecision(
            allowed=False, reason="risk rejected", adjusted_size=0.0
        )
        register_context("paper", ModeExecutionContext(
            mode="paper",
            clob_client=AsyncMock(),
            risk_manager=mock_rm,
            strategy_configs={},
        ))

        def fail_if_called(*_args, **_kwargs):
            raise AssertionError("BotState preflight should not use FOR UPDATE")

        with (
            patch("backend.core.strategy_executor.settings") as mock_settings,
            patch("backend.db.utils.SessionLocal", TestSession),
            patch("backend.models.database.for_update", side_effect=fail_if_called),
            patch("backend.core.strategy_executor._broadcast_event"),
        ):
            mock_settings.TRADING_MODE = "paper"

            from backend.core.strategy_executor import execute_decision

            result = await execute_decision(
                _make_decision(market_ticker="no-lock-risk-reject"),
                "test_strategy",
                "paper",
            )

        assert result is None
        mock_rm.validate_trade.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_decision_retries_bot_state_lock_contention(self):
        """Transient BotState lock contention retries the whole execution."""
        from backend.core import strategy_executor as se

        expected = {"id": 123, "market_ticker": "retry-market"}
        with (
            patch.object(
                se,
                "_execute_decision_paper_or_kalshi",
                side_effect=[se._BotStateLockRetry("locked"), expected],
            ) as execute_mock,
            patch.object(se.asyncio, "sleep", new=AsyncMock()) as sleep_mock,
        ):
            result = await se.execute_decision(
                _make_decision(market_ticker="retry-market"),
                "retry_strategy",
                "paper",
            )

        assert result == expected
        assert execute_mock.call_count == 2
        sleep_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_trade_persists_when_post_trade_botstate_update_fails(self):
        """BotState follow-up failure must not roll back an already-created trade."""
        from backend.core.mode_context import register_context, ModeExecutionContext
        from backend.core.risk_manager import RiskManager
        from backend.core import strategy_executor as se
        from backend.models.database import Trade, TradeAttempt

        test_engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        TestSession = sessionmaker(bind=test_engine)
        Base.metadata.create_all(bind=test_engine)

        db = TestSession()
        _seed_state(db, paper_bankroll=500.0)
        db.close()

        register_context("paper", ModeExecutionContext(
            mode="paper",
            clob_client=AsyncMock(),
            risk_manager=RiskManager(),
            strategy_configs={},
        ))

        with (
            patch("backend.core.strategy_executor.settings") as mock_settings,
            patch("backend.db.utils.SessionLocal", TestSession),
            patch("backend.core.strategy_executor._broadcast_event"),
            patch.object(se, "_apply_post_trade_botstate_update", return_value=False),
        ):
            mock_settings.TRADING_MODE = "paper"

            from backend.core.strategy_executor import execute_decision

            result = await execute_decision(
                _make_decision(market_ticker="persist-market", size=5.0),
                "persist_strategy",
                "paper",
            )

        assert result is not None

        check_db = TestSession()
        try:
            trade = (
                check_db.query(Trade)
                .filter(Trade.market_ticker == "persist-market")
                .first()
            )
            assert trade is not None

            attempt = (
                check_db.query(TradeAttempt)
                .filter(TradeAttempt.market_ticker == "persist-market")
                .first()
            )
            assert attempt is not None
            assert attempt.status == "EXECUTED"
            assert attempt.trade_id == trade.id

            state = check_db.query(BotState).filter_by(mode="paper").first()
            assert state.paper_bankroll == pytest.approx(500.0)
        finally:
            check_db.close()

    def test_post_trade_botstate_update_sets_short_transaction_timeouts(self):
        """Best-effort BotState sync must fast-fail instead of waiting on stale locks."""
        from backend.core import strategy_executor as se

        calls: list[str] = []

        class Bind:
            class Dialect:
                name = "postgresql"

            dialect = Dialect()

        class FakeSession:
            def get_bind(self):
                return Bind()

            def execute(self, statement, *_args, **_kwargs):
                calls.append(str(statement))

        db = FakeSession()

        with patch.object(se, "_update_botstate_after_trade") as update_mock:
            se._prepare_short_botstate_transaction(db)
            se._update_botstate_after_trade(db, "paper", 50.0)

        assert "SET LOCAL lock_timeout = '2s'" in calls
        assert "SET LOCAL statement_timeout = '5s'" in calls
        update_mock.assert_called_once_with(db, "paper", 50.0)


class TestAttemptSizingRejection:
    @pytest.mark.asyncio
    async def test_order_below_minimum_records_attempt_reason(self):
        """Orders too small for the active mode are visible in TradeAttempt."""
        from backend.core.risk_manager import RiskDecision, RiskManager
        from backend.core.mode_context import register_context, ModeExecutionContext
        from backend.models.database import TradeAttempt

        test_engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        TestSession = sessionmaker(bind=test_engine)
        Base.metadata.create_all(bind=test_engine)

        db = TestSession()
        _seed_state(db, paper_bankroll=500.0)
        db.close()

        mock_rm = MagicMock(spec=RiskManager)
        mock_rm.validate_trade.return_value = RiskDecision(
            allowed=True, reason="ok", adjusted_size=0.93
        )

        register_context("paper", ModeExecutionContext(
            mode="paper",
            clob_client=AsyncMock(),
            risk_manager=mock_rm,
            strategy_configs={}
        ))

        with (
            patch("backend.core.strategy_executor.settings") as mock_settings,
            patch("backend.db.utils.SessionLocal", TestSession),
            patch("backend.core.strategy_executor._broadcast_event"),
        ):
            mock_settings.TRADING_MODE = "paper"

            from backend.core.strategy_executor import execute_decision

            result = await execute_decision(
                _make_decision(market_ticker="tiny-market", size=0.93),
                "tiny_strategy",
                "paper",
            )

        assert result is None

        check_db = TestSession()
        try:
            attempt = (
                check_db.query(TradeAttempt)
                .filter(TradeAttempt.market_ticker == "tiny-market")
                .first()
            )
            assert attempt is not None
            assert attempt.status == "REJECTED"
            assert attempt.phase == "sizing"
            assert attempt.reason_code == "REJECTED_ORDER_TOO_SMALL"
            assert attempt.adjusted_size == pytest.approx(0.93)
        finally:
            check_db.close()


class TestAttemptUnexpectedFailure:
    @pytest.mark.asyncio
    async def test_unexpected_executor_error_records_failed_attempt(self):
        """Unexpected execution exceptions remain visible in TradeAttempt."""
        from backend.core.risk_manager import RiskDecision, RiskManager
        from backend.core.mode_context import register_context, ModeExecutionContext
        from backend.models.database import TradeAttempt

        test_engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        TestSession = sessionmaker(bind=test_engine)
        Base.metadata.create_all(bind=test_engine)

        db = TestSession()
        _seed_state(db, paper_bankroll=500.0)
        db.close()

        mock_rm = MagicMock(spec=RiskManager)
        mock_rm.validate_trade.return_value = RiskDecision(
            allowed=True, reason="ok", adjusted_size=10.0
        )

        register_context("paper", ModeExecutionContext(
            mode="paper",
            clob_client=AsyncMock(),
            risk_manager=mock_rm,
            strategy_configs={}
        ))

        with (
            patch("backend.core.strategy_executor.settings") as mock_settings,
            patch("backend.db.utils.SessionLocal", TestSession),
            patch("backend.core.strategy_executor._broadcast_event"),
            patch("backend.core.strategy_executor.TradeValidator.validate_trade_data") as validate_trade,
        ):
            mock_settings.TRADING_MODE = "paper"
            validate_trade.side_effect = RuntimeError("validator exploded")

            from backend.core.strategy_executor import execute_decision

            result = await execute_decision(
                _make_decision(market_ticker="boom-market", size=10.0),
                "boom_strategy",
                "paper",
            )

        assert result is None

        check_db = TestSession()
        try:
            attempts = (
                check_db.query(TradeAttempt)
                .filter(TradeAttempt.market_ticker == "boom-market")
                .all()
            )
            assert len(attempts) == 1
            assert attempts[0].status == "FAILED"
            assert attempts[0].phase == "error"
            assert attempts[0].reason_code == "FAILED_UNEXPECTED_EXECUTION_ERROR_RUNTIMEERROR_VALIDATOR_EXPLODED"
        finally:
            check_db.close()


class TestUpdatesBankroll:
    @pytest.mark.asyncio
    async def test_updates_paper_bankroll(self):
        """Paper trade DEDUCTS bankroll at entry — settlement returns stake + PNL."""
        from backend.core.mode_context import register_context, ModeExecutionContext
        from backend.core.risk_manager import RiskManager

        test_engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        TestSession = sessionmaker(bind=test_engine)
        Base.metadata.create_all(bind=test_engine)

        db = TestSession()
        _seed_state(db, paper_bankroll=500.0)
        db.close()

        mock_clob = AsyncMock()
        mock_rm = RiskManager()
        register_context("paper", ModeExecutionContext(
            mode="paper",
            clob_client=mock_clob,
            risk_manager=mock_rm,
            strategy_configs={}
        ))

        with (
            patch("backend.core.strategy_executor.settings") as mock_settings,
            patch("backend.db.utils.SessionLocal", TestSession),
            patch("backend.core.strategy_executor._broadcast_event"),
        ):
            mock_settings.TRADING_MODE = "paper"

            from backend.core.strategy_executor import execute_decision

            result = await execute_decision(
                _make_decision(market_ticker="bankroll-market", size=5.0),
                "test_strategy",
                "paper",
            )

        assert result is not None

        check_db = TestSession()
        try:
            state = check_db.query(BotState).filter_by(mode="paper").first()
            assert state.paper_bankroll == pytest.approx(500.0 - 5.0)
        finally:
            check_db.close()

    @pytest.mark.asyncio
    async def test_trade_creation_uses_atomic_botstate_update_without_for_update(self):
        """Successful paper trades update BotState without SELECT ... FOR UPDATE."""
        from backend.core.mode_context import register_context, ModeExecutionContext
        from backend.core.risk_manager import RiskManager

        test_engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        TestSession = sessionmaker(bind=test_engine)
        Base.metadata.create_all(bind=test_engine)

        db = TestSession()
        _seed_state(db, paper_bankroll=500.0)
        db.close()

        register_context("paper", ModeExecutionContext(
            mode="paper",
            clob_client=AsyncMock(),
            risk_manager=RiskManager(),
            strategy_configs={},
        ))

        def fail_if_called(*_args, **_kwargs):
            raise AssertionError("Trade creation should use atomic UPDATE, not FOR UPDATE")

        with (
            patch("backend.core.strategy_executor.settings") as mock_settings,
            patch("backend.db.utils.SessionLocal", TestSession),
            patch("backend.models.database.for_update", side_effect=fail_if_called),
            patch("backend.core.strategy_executor._broadcast_event"),
        ):
            mock_settings.TRADING_MODE = "paper"

            from backend.core.strategy_executor import execute_decision

            result = await execute_decision(
                _make_decision(market_ticker="atomic-bankroll-market", size=5.0),
                "test_strategy",
                "paper",
            )

        assert result is not None

        check_db = TestSession()
        try:
            state = check_db.query(BotState).filter_by(mode="paper").first()
            assert state.paper_bankroll == pytest.approx(495.0)
            assert state.paper_trades == 1
        finally:
            check_db.close()

    @pytest.mark.asyncio
    async def test_trade_persists_when_post_commit_botstate_sync_fails(self):
        """Trade/attempt persistence must survive follow-up BotState sync failure."""
        from backend.models.database import Trade, TradeAttempt
        from backend.core.mode_context import register_context, ModeExecutionContext
        from backend.core.risk_manager import RiskManager

        test_engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        TestSession = sessionmaker(bind=test_engine)
        Base.metadata.create_all(bind=test_engine)

        db = TestSession()
        _seed_state(db, paper_bankroll=500.0)
        db.close()

        register_context("paper", ModeExecutionContext(
            mode="paper",
            clob_client=AsyncMock(),
            risk_manager=RiskManager(),
            strategy_configs={},
        ))

        with (
            patch("backend.core.strategy_executor.settings") as mock_settings,
            patch("backend.db.utils.SessionLocal", TestSession),
            patch("backend.core.strategy_executor._broadcast_event"),
            patch("backend.core.strategy_executor._apply_post_trade_botstate_update", return_value=False),
        ):
            mock_settings.TRADING_MODE = "paper"

            from backend.core.strategy_executor import execute_decision

            result = await execute_decision(
                _make_decision(market_ticker="paper-botstate-sync-fail", size=5.0),
                "test_strategy",
                "paper",
            )

        assert result is not None

        check_db = TestSession()
        try:
            trade = (
                check_db.query(Trade)
                .filter(Trade.market_ticker == "paper-botstate-sync-fail")
                .first()
            )
            assert trade is not None

            attempt = (
                check_db.query(TradeAttempt)
                .filter(TradeAttempt.market_ticker == "paper-botstate-sync-fail")
                .first()
            )
            assert attempt is not None
            assert attempt.status == "EXECUTED"
            assert attempt.reason_code == "EXECUTED_TRADE_OPENED"
            assert attempt.trade_id == trade.id

            state = check_db.query(BotState).filter_by(mode="paper").first()
            assert state.paper_bankroll == pytest.approx(500.0)
            assert state.paper_trades == 0
        finally:
            check_db.close()


class TestHeartbeatFlush:
    def test_failed_flush_preserves_pending_heartbeats(self):
        """Failed heartbeat DB flush must retain pending in-memory entries."""
        from backend.core import heartbeat as hb

        class FailingSession:
            def execute(self, *_args, **_kwargs):
                raise RuntimeError("db locked")

            def rollback(self):
                pass

            def close(self):
                pass

        def failing_session():
            return FailingSession()

        hb._pending_heartbeats.clear()
        hb._pending_heartbeats["strategy-a"] = "2026-05-14T01:00:00+00:00"

        with patch("backend.core.heartbeat.SessionLocal", failing_session), patch(
            "backend.core.heartbeat.logger.warning"
        ) as warning_mock:
            flushed = hb._flush_heartbeats()

        assert flushed is False
        assert hb._pending_heartbeats == {
            "strategy-a": "2026-05-14T01:00:00+00:00"
        }
        warning_mock.assert_called_once_with("heartbeat flush failed: db locked")

        hb._pending_heartbeats.clear()

    def test_lock_timeout_flush_logs_concise_warning(self):
        """Expected BotState lock contention should not emit raw SQL stack text."""
        from sqlalchemy.exc import OperationalError
        from backend.core import heartbeat as hb

        class Orig:
            pgcode = "55P03"

            def __str__(self):
                return "canceling statement due to lock timeout"

        class FailingSession:
            def execute(self, *_args, **_kwargs):
                raise OperationalError("UPDATE bot_state SET misc_data", {}, Orig())

            def rollback(self):
                pass

            def close(self):
                pass

        hb._pending_heartbeats.clear()
        hb._pending_heartbeats["strategy-a"] = "2026-05-14T01:00:00+00:00"

        with patch("backend.core.heartbeat.SessionLocal", lambda: FailingSession()), patch(
            "backend.core.heartbeat.logger.warning"
        ) as warning_mock:
            flushed = hb._flush_heartbeats()

        assert flushed is False
        warning_mock.assert_called_once_with("heartbeat flush deferred due to BotState contention")

        hb._pending_heartbeats.clear()

    @pytest.mark.asyncio
    async def test_watchdog_skips_stale_checks_when_flush_fails(self):
        """Watchdog should not emit stale errors from old DB data when flush fails."""
        from backend.core import heartbeat as hb

        def fail_flush():
            return False

        def should_not_open_session():
            raise RuntimeError("db locked")

        with patch("backend.core.heartbeat._flush_heartbeats", fail_flush), patch(
            "backend.db.utils.get_db_session", should_not_open_session
        ), patch("backend.core.heartbeat.logger.warning") as warning_mock:
            await hb.watchdog_job()

        warning_mock.assert_called_once_with(
            "[WATCHDOG] Skipping stale heartbeat checks until heartbeat flush succeeds"
        )


class TestCreatesSignalRecord:
    @pytest.mark.asyncio
    async def test_creates_signal_record(self):
        """execute_decision creates a Signal row for calibration tracking."""
        from backend.models.database import Signal
        from backend.core.mode_context import register_context, ModeExecutionContext
        from backend.core.risk_manager import RiskManager

        test_engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        TestSession = sessionmaker(bind=test_engine)
        Base.metadata.create_all(bind=test_engine)

        db = TestSession()
        _seed_state(db)
        db.close()

        ticker = "signal-track-market"

        mock_clob = AsyncMock()
        mock_rm = RiskManager()
        register_context("paper", ModeExecutionContext(
            mode="paper",
            clob_client=mock_clob,
            risk_manager=mock_rm,
            strategy_configs={}
        ))

        with (
            patch("backend.core.strategy_executor.settings") as mock_settings,
            patch("backend.db.utils.SessionLocal", TestSession),
            patch("backend.core.strategy_executor._broadcast_event"),
        ):
            mock_settings.TRADING_MODE = "paper"

            from backend.core.strategy_executor import execute_decision

            result = await execute_decision(
                _make_decision(market_ticker=ticker, reasoning="signal reason"),
                "calibration_strategy",
                "paper",
            )

        assert result is not None

        check_db = TestSession()
        try:
            sig = (
                check_db.query(Signal)
                .filter(Signal.market_ticker == ticker)
                .order_by(Signal.id.desc())
                .first()
            )
            assert sig is not None
            assert sig.track_name == "calibration_strategy"
            assert sig.executed is True
            assert sig.execution_mode == "paper"
        finally:
            check_db.close()


class TestMaxTradesPerCycle:
    @pytest.mark.asyncio
    async def test_max_trades_per_cycle(self):
        """execute_decisions caps at MAX_TRADES_PER_CYCLE (6)."""
        from backend.core.mode_context import register_context, ModeExecutionContext
        from backend.core.risk_manager import RiskManager

        test_engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        TestSession = sessionmaker(bind=test_engine)
        Base.metadata.create_all(bind=test_engine)

        db = TestSession()
        _seed_state(db, paper_bankroll=10000.0)
        db.close()

        decisions = [
            _make_decision(market_ticker=f"cap-market-{i}", size=10.0) for i in range(5)
        ]

        mock_clob = AsyncMock()
        mock_rm = RiskManager()
        register_context("paper", ModeExecutionContext(
            mode="paper",
            clob_client=mock_clob,
            risk_manager=mock_rm,
            strategy_configs={}
        ))

        with (
            patch("backend.core.strategy_executor.settings") as mock_settings,
            patch("backend.db.utils.SessionLocal", TestSession),
            patch("backend.core.strategy_executor._broadcast_event"),
        ):
            mock_settings.TRADING_MODE = "paper"

            from backend.core.strategy_executor import execute_decisions

            results = await execute_decisions(decisions, "cap_strategy", "paper")

        assert len(results) <= 6


class TestLiveModeCallsCLOB:
    @pytest.mark.asyncio
    async def test_live_mode_calls_clob(self):
        """In live mode, place_limit_order is called and its result drives trade creation."""
        from backend.data.polymarket_clob import OrderResult
        from backend.core.mode_context import register_context, ModeExecutionContext
        from backend.core.risk_manager import RiskManager

        test_engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        TestSession = sessionmaker(bind=test_engine)
        Base.metadata.create_all(bind=test_engine)

        db = TestSession()
        _seed_state(db, bankroll=2000.0, paper_bankroll=2000.0, mode="live")
        db.close()

        mock_order_result = OrderResult(
            success=True,
            order_id="live-order-xyz",
            fill_price=0.56,
            fill_size=5.0,
        )

        mock_clob = AsyncMock()
        mock_clob.place_limit_order = AsyncMock(return_value=mock_order_result)
        mock_clob.create_or_derive_api_key = AsyncMock()
        mock_clob.__aenter__ = AsyncMock(return_value=mock_clob)
        mock_clob.__aexit__ = AsyncMock(return_value=False)

        mock_rm = RiskManager()
        register_context("live", ModeExecutionContext(
            mode="live",
            clob_client=mock_clob,
            risk_manager=mock_rm,
            strategy_configs={}
        ))

        with (
            patch("backend.core.strategy_executor.settings") as mock_settings,
            patch("backend.db.utils.SessionLocal", TestSession),
            patch("backend.core.strategy_executor._broadcast_event"),
        ):
            mock_settings.TRADING_MODE = "live"

            from backend.core.strategy_executor import execute_decision

            result = await execute_decision(
                _make_decision(
                    market_ticker="live-market-001",
                    token_id="token-abc-123",
                    size=5.0,
                ),
                "live_strategy",
                "live",
            )

        assert result is not None
        mock_clob.place_limit_order.assert_awaited_once()
        assert result["clob_order_id"] == "live-order-xyz"

    @pytest.mark.asyncio
    async def test_live_clob_success_without_order_id_records_failed_attempt(self):
        """Live CLOB handoff must not leave attempts stuck at RISK_APPROVED."""
        from backend.data.polymarket_clob import OrderResult
        from backend.core.mode_context import register_context, ModeExecutionContext
        from backend.core.risk_manager import RiskManager
        from backend.models.database import Trade, TradeAttempt

        test_engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        TestSession = sessionmaker(bind=test_engine)
        Base.metadata.create_all(bind=test_engine)

        db = TestSession()
        _seed_state(db, bankroll=2000.0, paper_bankroll=2000.0, mode="live")
        db.close()

        mock_order_result = OrderResult(
            success=True,
            order_id=None,
            fill_price=0.56,
            fill_size=5.0,
        )

        mock_clob = AsyncMock()
        mock_clob.place_limit_order = AsyncMock(return_value=mock_order_result)
        mock_clob.create_or_derive_api_key = AsyncMock()
        mock_clob.__aenter__ = AsyncMock(return_value=mock_clob)
        mock_clob.__aexit__ = AsyncMock(return_value=False)

        register_context("live", ModeExecutionContext(
            mode="live",
            clob_client=mock_clob,
            risk_manager=RiskManager(),
            strategy_configs={},
        ))

        with (
            patch("backend.core.strategy_executor.settings") as mock_settings,
            patch("backend.db.utils.SessionLocal", TestSession),
            patch("backend.core.strategy_executor._broadcast_event"),
        ):
            mock_settings.TRADING_MODE = "live"

            from backend.core.strategy_executor import execute_decision

            result = await execute_decision(
                _make_decision(
                    market_ticker="live-market-no-order-id",
                    token_id="token-abc-123",
                    size=5.0,
                ),
                "live_strategy",
                "live",
            )

        assert result is None
        mock_clob.place_limit_order.assert_awaited_once()

        check_db = TestSession()
        try:
            trade = (
                check_db.query(Trade)
                .filter(Trade.market_ticker == "live-market-no-order-id")
                .first()
            )
            assert trade is None

            attempt = (
                check_db.query(TradeAttempt)
                .filter(TradeAttempt.market_ticker == "live-market-no-order-id")
                .first()
            )
            assert attempt is not None
            assert attempt.status == "FAILED"
            assert attempt.phase == "execution"
            assert attempt.reason_code == "FAILED_BROKER_REJECTED"
            assert attempt.trade_id is None
            assert attempt.order_id is None
        finally:
            check_db.close()
    @pytest.mark.asyncio
    async def test_testnet_with_polymarket_token_uses_simulated_path(self):
        """Testnet Polymarket token decisions must not use live CLOB placement."""
        from backend.core.mode_context import register_context, ModeExecutionContext
        from backend.core.risk_manager import RiskManager
        from backend.models.database import Trade

        test_engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        TestSession = sessionmaker(bind=test_engine)
        Base.metadata.create_all(bind=test_engine)

        db = TestSession()
        _seed_state(db, bankroll=1000.0, paper_bankroll=1000.0, mode="testnet")
        db.close()

        mock_clob = AsyncMock()
        mock_clob.place_limit_order = AsyncMock()
        register_context("testnet", ModeExecutionContext(
            mode="testnet",
            clob_client=mock_clob,
            risk_manager=RiskManager(),
            strategy_configs={},
        ))

        with (
            patch("backend.core.strategy_executor.settings") as mock_settings,
            patch("backend.db.utils.SessionLocal", TestSession),
            patch("backend.core.strategy_executor._broadcast_event"),
        ):
            mock_settings.TRADING_MODE = "testnet"

            from backend.core.strategy_executor import execute_decision

            result = await execute_decision(
                _make_decision(
                    market_ticker="testnet-token-market",
                    token_id="123456789",
                    size=5.0,
                ),
                "testnet_strategy",
                "testnet",
            )

        assert result is not None
        mock_clob.place_limit_order.assert_not_called()

        check_db = TestSession()
        try:
            trade = (
                check_db.query(Trade)
                .filter(Trade.market_ticker == "testnet-token-market")
                .first()
            )
            assert trade is not None
            assert trade.trading_mode == "testnet"
        finally:
            check_db.close()
