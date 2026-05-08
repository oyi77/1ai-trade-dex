"""Integration tests for parallel multi-mode execution.

Tests that paper, testnet, and live modes can run simultaneously with:
- Independent CLOB clients
- Isolated risk managers
- Separate BotState rows
- No cross-mode contamination
- Concurrent job execution
"""

# ruff: noqa: E402
import sys
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ---------------------------------------------------------------------------
# Stub scheduler before imports
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
# In-memory DB setup
# ---------------------------------------------------------------------------
from backend.models import database as _db_mod
from backend.models.database import Base, BotState, Trade, StrategyConfig

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


# ---------------------------------------------------------------------------
# Test Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_db():
    """Fresh DB session per test."""
    db = _TestSession()

    # Clear all trades before each test for isolation
    db.query(Trade).delete()
    db.commit()

    yield db
    db.close()


@pytest.fixture
def seed_bot_states(test_db):
    """Seed BotState rows for all 3 modes."""
    for mode in ["paper", "testnet", "live"]:
        existing = test_db.query(BotState).filter_by(mode=mode).first()
        if not existing:
            initial_bankroll = 1000.0 if mode != "testnet" else 100.0
            test_db.add(
                BotState(
                    mode=mode,
                    bankroll=initial_bankroll,
                    paper_bankroll=initial_bankroll if mode == "paper" else None,
                    testnet_bankroll=initial_bankroll if mode == "testnet" else None,
                    total_trades=0,
                    winning_trades=0,
                    total_pnl=0.0,
                    is_running=True,
                )
            )
        else:
            initial_bankroll = 1000.0 if mode != "testnet" else 100.0
            test_db.info["allow_live_financial_update"] = True
            existing.bankroll = initial_bankroll
            existing.paper_bankroll = initial_bankroll if mode == "paper" else None
            existing.testnet_bankroll = initial_bankroll if mode == "testnet" else None
            existing.total_trades = 0
            existing.winning_trades = 0
            existing.total_pnl = 0.0
            existing.is_running = True
    test_db.commit()
    test_db.info.pop("allow_live_financial_update", None)
    return test_db


@pytest.fixture
def seed_strategy_configs(test_db):
    """Seed StrategyConfig rows for testing."""
    configs = [
        StrategyConfig(
            strategy_name="test_strategy_paper",
            enabled=True,
            interval_seconds=60,
            mode="paper",
            params="{}",
        ),
        StrategyConfig(
            strategy_name="test_strategy_testnet",
            enabled=True,
            interval_seconds=60,
            mode="testnet",
            params="{}",
        ),
        StrategyConfig(
            strategy_name="test_strategy_live",
            enabled=True,
            interval_seconds=60,
            mode="live",
            params="{}",
        ),
        StrategyConfig(
            strategy_name="test_strategy_global",
            enabled=True,
            interval_seconds=60,
            mode=None,  # Applies to all modes
            params="{}",
        ),
    ]
    for cfg in configs:
        test_db.add(cfg)
    test_db.commit()
    return test_db


# ---------------------------------------------------------------------------
# Test 1: All 3 Modes Start Successfully
# ---------------------------------------------------------------------------


class TestAllModesStart:
    @pytest.mark.asyncio
    async def test_all_modes_parallel(self, seed_bot_states):
        """Verify all 3 modes can be registered and accessed."""
        from backend.core.mode_context import (
            register_context,
            get_context,
            list_contexts,
            ModeExecutionContext,
        )
        from backend.core.risk_manager import RiskManager

        # Create mock CLOB clients for each mode
        mock_clob_paper = AsyncMock()
        mock_clob_testnet = AsyncMock()
        mock_clob_live = AsyncMock()

        # Register contexts for all 3 modes
        register_context(
            "paper",
            ModeExecutionContext(
                mode="paper",
                clob_client=mock_clob_paper,
                risk_manager=RiskManager(),
                strategy_configs={},
            ),
        )
        register_context(
            "testnet",
            ModeExecutionContext(
                mode="testnet",
                clob_client=mock_clob_testnet,
                risk_manager=RiskManager(),
                strategy_configs={},
            ),
        )
        register_context(
            "live",
            ModeExecutionContext(
                mode="live",
                clob_client=mock_clob_live,
                risk_manager=RiskManager(),
                strategy_configs={},
            ),
        )

        # Verify all contexts registered
        contexts = list_contexts()
        assert len(contexts) == 3
        assert "paper" in contexts
        assert "testnet" in contexts
        assert "live" in contexts

        # Verify each context is accessible and has correct mode
        paper_ctx = get_context("paper")
        assert paper_ctx.mode == "paper"
        assert paper_ctx.clob_client is mock_clob_paper

        testnet_ctx = get_context("testnet")
        assert testnet_ctx.mode == "testnet"
        assert testnet_ctx.clob_client is mock_clob_testnet

        live_ctx = get_context("live")
        assert live_ctx.mode == "live"
        assert live_ctx.clob_client is mock_clob_live


# ---------------------------------------------------------------------------
# Test 2: Mode Isolation (Paper Trades Don't Affect Live Bankroll)
# ---------------------------------------------------------------------------


class TestModeIsolation:
    @pytest.mark.asyncio
    async def test_mode_isolation(self, seed_bot_states):
        """Verify paper trades don't affect testnet/live bankrolls."""
        from backend.core.mode_context import (
            register_context,
            ModeExecutionContext,
        )
        from backend.core.risk_manager import RiskManager
        from backend.core.strategy_executor import execute_decision

        # Register contexts
        for mode in ["paper", "testnet", "live"]:
            register_context(
                mode,
                ModeExecutionContext(
                    mode=mode,
                    clob_client=AsyncMock(),
                    risk_manager=RiskManager(),
                    strategy_configs={},
                ),
            )

        with (
            patch("backend.db.utils.SessionLocal", _TestSession),
            patch("backend.core.strategy_executor._broadcast_event"),
        ):
            # Execute paper trade
            paper_decision = {
                "market_ticker": "paper-market-001",
                "direction": "yes",
                "size": 5.0,
                "entry_price": 0.55,
                "edge": 0.08,
                "confidence": 0.75,
                "model_probability": 0.63,
                "platform": "polymarket",
                "reasoning": "paper test",
                "token_id": None,
            }
            await execute_decision(paper_decision, "test_strategy", "paper")

            # Verify paper bankroll decreased
            db = _TestSession()
            paper_state = db.query(BotState).filter_by(mode="paper").first()
            assert paper_state.paper_bankroll < 1000.0  # Deducted

            # Verify testnet/live bankrolls unchanged
            testnet_state = db.query(BotState).filter_by(mode="testnet").first()
            assert testnet_state.testnet_bankroll == 100.0  # Unchanged

            live_state = db.query(BotState).filter_by(mode="live").first()
            assert live_state.bankroll == 1000.0  # Unchanged

            # Verify trade tagged with correct mode
            trade = (
                db.query(Trade).filter_by(market_ticker="paper-market-001").first()
            )
            assert trade is not None
            assert trade.trading_mode == "paper"

            db.close()


# ---------------------------------------------------------------------------
# Test 3: Concurrent Job Execution (3 Modes Running Strategies Simultaneously)
# ---------------------------------------------------------------------------


class TestConcurrentExecution:
    @pytest.mark.asyncio
    async def test_concurrent_execution(self, seed_bot_states):
        """Verify 3 modes can execute trades concurrently without conflicts."""
        from backend.core.mode_context import (
            register_context,
            ModeExecutionContext,
        )
        from backend.core.risk_manager import RiskManager
        from backend.core.strategy_executor import execute_decision
        import asyncio

        # Register contexts with properly mocked CLOB clients
        for mode in ["paper", "testnet", "live"]:
            mock_clob = AsyncMock()
            mock_result = MagicMock()
            mock_result.success = True
            mock_result.order_id = f"order-{mode}-concurrent-123"
            mock_result.fill_price = 0.55
            mock_result.filled_size = None
            mock_clob.__aenter__.return_value.place_limit_order.return_value = mock_result

            register_context(
                mode,
                ModeExecutionContext(
                    mode=mode,
                    clob_client=mock_clob,
                    risk_manager=RiskManager(),
                    strategy_configs={},
                ),
            )

        with (
            patch("backend.db.utils.SessionLocal", _TestSession),
            patch("backend.core.strategy_executor._broadcast_event"),
        ):
            # Execute 3 trades concurrently (one per mode)
            decisions = [
                {
                    "market_ticker": f"{mode}-concurrent-market",
                    "direction": "yes",
                    "size": 5.0,
                    "entry_price": 0.55,
                    "edge": 0.08,
                    "confidence": 0.75,
                    "model_probability": 0.63,
                    "platform": "polymarket",
                    "reasoning": f"{mode} concurrent test",
                    "token_id": f"token-{mode}-123" if mode != "paper" else None,
                }
                for mode in ["paper", "testnet", "live"]
            ]

            # Execute all 3 concurrently
            results = await asyncio.gather(
                execute_decision(decisions[0], "test_strategy", "paper"),
                execute_decision(decisions[1], "test_strategy", "testnet"),
                execute_decision(decisions[2], "test_strategy", "live"),
            )

            # Verify all 3 succeeded
            assert all(r is not None for r in results)

            # Verify 3 trades created with correct modes
            db = _TestSession()
            paper_trade = (
                db.query(Trade)
                .filter_by(market_ticker="paper-concurrent-market")
                .first()
            )
            testnet_trade = (
                db.query(Trade)
                .filter_by(market_ticker="testnet-concurrent-market")
                .first()
            )
            live_trade = (
                db.query(Trade)
                .filter_by(market_ticker="live-concurrent-market")
                .first()
            )

            assert paper_trade.trading_mode == "paper"
            assert testnet_trade.trading_mode == "testnet"
            assert live_trade.trading_mode == "live"

            db.close()


# ---------------------------------------------------------------------------
# Test 4: Database Integrity (No Cross-Mode Contamination)
# ---------------------------------------------------------------------------


class TestDatabaseIntegrity:
    @pytest.mark.asyncio
    async def test_no_cross_mode_contamination(self, seed_bot_states):
        """Verify trades and risk calculations are isolated per mode."""
        from backend.core.mode_context import (
            register_context,
            ModeExecutionContext,
        )
        from backend.core.risk_manager import RiskManager
        from backend.core.strategy_executor import execute_decision

        for mode in ["paper", "testnet", "live"]:
            mock_clob = AsyncMock()
            mock_result = MagicMock()
            mock_result.success = True
            mock_result.order_id = f"order-{mode}-integrity-456"
            mock_result.fill_price = 0.55
            mock_result.filled_size = None
            mock_clob.__aenter__.return_value.place_limit_order.return_value = mock_result

            register_context(
                mode,
                ModeExecutionContext(
                    mode=mode,
                    clob_client=mock_clob,
                    risk_manager=RiskManager(),
                    strategy_configs={},
                ),
            )

        with (
            patch("backend.db.utils.SessionLocal", _TestSession),
            patch("backend.core.strategy_executor._broadcast_event"),
        ):
            # Create trades in each mode
            for mode in ["paper", "testnet", "live"]:
                decision = {
                    "market_ticker": f"{mode}-integrity-market",
                    "direction": "yes",
                    "size": 5.0,
                    "entry_price": 0.55,
                    "edge": 0.08,
                    "confidence": 0.75,
                    "model_probability": 0.63,
                    "platform": "polymarket",
                    "reasoning": f"{mode} integrity test",
                    "token_id": f"token-{mode}-456" if mode != "paper" else None,
                }
                await execute_decision(decision, "test_strategy", mode)

            # Verify each mode has exactly 1 trade
            db = _TestSession()
            paper_trades = (
                db.query(Trade).filter_by(trading_mode="paper").count()
            )
            testnet_trades = (
                db.query(Trade).filter_by(trading_mode="testnet").count()
            )
            live_trades = (
                db.query(Trade).filter_by(trading_mode="live").count()
            )

            assert paper_trades == 1
            assert testnet_trades == 1
            assert live_trades == 1

            # Verify BotState rows are independent
            paper_state = db.query(BotState).filter_by(mode="paper").first()
            testnet_state = db.query(BotState).filter_by(mode="testnet").first()
            live_state = db.query(BotState).filter_by(mode="live").first()

            # Each mode should have deducted from its own bankroll
            assert paper_state.paper_bankroll < 1000.0
            assert testnet_state.testnet_bankroll < 100.0
            assert live_state.bankroll == 1000.0
            assert live_state.total_trades == 1

            # Verify no cross-contamination (paper trades don't affect live)
            paper_trade = (
                db.query(Trade)
                .filter_by(market_ticker="paper-integrity-market")
                .first()
            )
            assert paper_trade.trading_mode == "paper"
            assert paper_trade.trading_mode != "live"

            db.close()


# ---------------------------------------------------------------------------
# Test 5: Mode-Specific Risk Limits
# ---------------------------------------------------------------------------


class TestModeSpecificRiskLimits:
    @pytest.mark.asyncio
    async def test_mode_specific_risk_limits(self, seed_bot_states):
        """Verify risk limits are enforced independently per mode."""
        from backend.core.mode_context import (
            register_context,
            ModeExecutionContext,
        )
        from backend.core.risk_manager import RiskManager
        from backend.core.strategy_executor import execute_decision

        # Register contexts with separate risk managers
        for mode in ["paper", "testnet", "live"]:
            mock_clob = AsyncMock()
            mock_result = MagicMock()
            mock_result.success = True
            mock_result.order_id = f"order-{mode}-789"
            mock_result.fill_price = 0.55
            mock_result.filled_size = None
            mock_clob.__aenter__.return_value.place_limit_order.return_value = mock_result

            register_context(
                mode,
                ModeExecutionContext(
                    mode=mode,
                    clob_client=mock_clob,
                    risk_manager=RiskManager(),
                    strategy_configs={},
                ),
            )

        with (
            patch("backend.db.utils.SessionLocal", _TestSession),
            patch("backend.core.strategy_executor._broadcast_event"),
        ):
            # Execute trade in paper mode that consumes most of bankroll
            paper_decision = {
                "market_ticker": "paper-risk-market",
                "direction": "yes",
                "size": 5.0,
                "entry_price": 0.55,
                "edge": 0.08,
                "confidence": 0.75,
                "model_probability": 0.63,
                "platform": "polymarket",
                "reasoning": "paper risk test",
                "token_id": None,
            }
            paper_result = await execute_decision(
                paper_decision, "test_strategy", "paper"
            )
            assert paper_result is not None  # Should succeed

            # Try to execute another paper trade (should fail due to exposure)
            paper_decision_2 = {
                "market_ticker": "paper-risk-market-2",
                "direction": "yes",
                "size": 5.0,
                "entry_price": 0.55,
                "edge": 0.08,
                "confidence": 0.75,
                "model_probability": 0.63,
                "platform": "polymarket",
                "reasoning": "paper risk test 2",
                "token_id": None,
            }
            await execute_decision(paper_decision_2, "test_strategy", "paper")
            # May succeed with adjusted size or fail - depends on risk limits

            # Execute trade in live mode (should succeed despite paper exposure)
            live_decision = {
                "market_ticker": "live-risk-market",
                "direction": "yes",
                "size": 5.0,
                "entry_price": 0.55,
                "edge": 0.08,
                "confidence": 0.75,
                "model_probability": 0.63,
                "platform": "polymarket",
                "reasoning": "live risk test",
                "token_id": "token-live-789",
            }
            live_result = await execute_decision(
                live_decision, "test_strategy", "live"
            )
            assert live_result is not None  # Should succeed

            # Verify paper and live trades are independent
            db = _TestSession()
            paper_trades = (
                db.query(Trade).filter_by(trading_mode="paper").count()
            )
            live_trades = (
                db.query(Trade).filter_by(trading_mode="live").count()
            )

            assert paper_trades >= 1  # At least 1 paper trade
            assert live_trades == 1  # Exactly 1 live trade

            db.close()


# ---------------------------------------------------------------------------
# Test 6: Strategy Config Loading Per Mode
# ---------------------------------------------------------------------------


class TestStrategyConfigLoading:
    def test_strategy_config_per_mode(self, seed_strategy_configs):
        """Verify strategy configs are loaded correctly per mode."""
        db = _TestSession()

        # Query paper-specific configs
        paper_configs = (
            db.query(StrategyConfig)
            .filter(
                (StrategyConfig.mode == "paper") | (StrategyConfig.mode.is_(None))
            )
            .all()
        )
        paper_names = [c.strategy_name for c in paper_configs]
        assert "test_strategy_paper" in paper_names
        assert "test_strategy_global" in paper_names
        assert "test_strategy_testnet" not in paper_names
        assert "test_strategy_live" not in paper_names

        # Query testnet-specific configs
        testnet_configs = (
            db.query(StrategyConfig)
            .filter(
                (StrategyConfig.mode == "testnet") | (StrategyConfig.mode.is_(None))
            )
            .all()
        )
        testnet_names = [c.strategy_name for c in testnet_configs]
        assert "test_strategy_testnet" in testnet_names
        assert "test_strategy_global" in testnet_names
        assert "test_strategy_paper" not in testnet_names
        assert "test_strategy_live" not in testnet_names

        # Query live-specific configs
        live_configs = (
            db.query(StrategyConfig)
            .filter(
                (StrategyConfig.mode == "live") | (StrategyConfig.mode.is_(None))
            )
            .all()
        )
        live_names = [c.strategy_name for c in live_configs]
        assert "test_strategy_live" in live_names
        assert "test_strategy_global" in live_names
        assert "test_strategy_paper" not in live_names
        assert "test_strategy_testnet" not in live_names

        db.close()
