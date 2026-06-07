"""Shared pytest fixtures for PolyEdge backend integration tests."""

import sys
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure conftest_agi fixtures are always loaded
pytest_plugins = ["backend.tests.conftest_agi"]

# ---------------------------------------------------------------------------
# Stub apscheduler and backend.core.scheduler BEFORE any other imports
# so the startup event doesn't crash on the missing package.
# ---------------------------------------------------------------------------
_sched_stub = MagicMock()
_sched_stub.start_scheduler = MagicMock()
_sched_stub.stop_scheduler = MagicMock()
_sched_stub.log_event = MagicMock()
_sched_stub.is_scheduler_running = MagicMock(return_value=False)
_sched_stub.get_recent_events = MagicMock(return_value=[])
_sched_stub.run_manual_scan = MagicMock(return_value=None)
sys.modules.setdefault("apscheduler", MagicMock())
sys.modules.setdefault("apscheduler.schedulers", MagicMock())
sys.modules.setdefault("apscheduler.schedulers.asyncio", MagicMock())
sys.modules.setdefault("apscheduler.triggers", MagicMock())
sys.modules.setdefault("apscheduler.triggers.interval", MagicMock())
sys.modules.setdefault("apscheduler.triggers.cron", MagicMock())
sys.modules.setdefault("apscheduler.events", MagicMock())
sys.modules["backend.core.scheduler"] = _sched_stub
sys.modules["backend.core.scheduling.scheduler"] = _sched_stub

# ---------------------------------------------------------------------------
# Loguru → caplog bridge: routes loguru output into pytest caplog
# so tests that use caplog (stdlib LogCaptureFixture) still work.
# ---------------------------------------------------------------------------
import logging as _stdlib_logging


@pytest.fixture(autouse=True)
def _loguru_to_caplog(caplog):
    from loguru import logger as _loguru_logger

    class _LoguruHandler(_stdlib_logging.Handler):
        def emit(self, record):
            caplog.handler.emit(record)

    _LoguruHandler()
    handler_id = _loguru_logger.add(
        lambda msg: _stdlib_logging.log(msg.record["level"].no, msg.record["message"]),
        level="DEBUG",
    )
    yield
    _loguru_logger.remove(handler_id)


# ---------------------------------------------------------------------------
# Build in-memory SQLite engine and redirect the database module to use it
# so every SessionLocal() call (including from startup event / heartbeat)
# hits the same in-memory DB.
# ---------------------------------------------------------------------------
TEST_DB_URL = "sqlite:///:memory:"

test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

# Patch the database module's engine/SessionLocal before app import
from backend.models import database as _db_mod
from backend.models.database import Base

# Import all models so Base.metadata.create_all() creates every table.
# Without these imports, tables like strategy_proposal are missing in test DB.
from backend.models.database import (
    Signal,
    Trade,
    BotState,
    StrategyConfig,
    DecisionLog,
    TradeAttempt,
    MarketWatch,
    WalletConfig,
    TradeContext,
    JobQueue,
    PendingApproval,
    AILog,
    ActivityLog,
    MiroFishSignal,
    StrategyProposal,
    PerformanceMetric,
    AuditLog,
    WhaleTransaction,
    BtcPriceSnapshot,
    ScanLog,
    CopyTraderEntry,
    SettlementEvent,
    EquitySnapshot,
    CalibrationRecord,
    ResearchItemDB,
    Alert,
    AlertConfig,
    Setting,
    SystemSettings,
    ErrorLog,
    Experiment,
    ShadowTrade,
)
from backend.models.backtest import BacktestRun, BacktestTrade
from backend.models.kg_models import LLMCostRecord
import backend.models.genome_registry
from backend.core.strategy_performance_registry import StrategyPerformanceSnapshot
from backend.models.database import TransactionEvent
from backend.models.outcome_tables import (
    StrategyOutcome,
    StrategyHealthRecord,
    ParamChange,
    TradingCalibrationRecord,
)
from backend.models.signal_log import SignalLog
from backend.models.signal_log import SignalLog
from backend.models.signal_log import SignalLog
from backend.models.kg_models import ExperimentRecord, DecisionAuditLog
from backend.models.historical_data import (
    HistoricalCandle,
    MarketOutcome,
    WeatherSnapshot,
)
from backend.core.risk_profiles import RiskProfileRow

_db_mod.engine = test_engine
_db_mod.SessionLocal = TestSessionLocal

# Create all tables (Base.metadata covers most; ensure_schema covers extras)
Base.metadata.create_all(bind=test_engine)
try:
    _db_mod.ensure_schema()
except Exception:
    pass

# Patch heartbeat module's SessionLocal reference
try:
    from backend.core import heartbeat as _hb

    _hb.SessionLocal = TestSessionLocal
except Exception:
    pass

# ---------------------------------------------------------------------------
# Now import the app (startup event will use the patched SessionLocal)
# ---------------------------------------------------------------------------
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.models.database import get_db


def _override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture(scope="function")
def client(db):
    def _override_test_db():
        yield db

    app.dependency_overrides[get_db] = _override_test_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides[get_db] = _override_get_db


_MODULES_WITH_SESSIONLOCAL = [
    "backend.db.utils",
    "backend.core.nightly_review",
    "backend.core.decisions",
    "backend.core.signals",
    "backend.core.whale_discovery",
    "backend.core.autonomous_promoter",
    "backend.core.heartbeat",
    "backend.core.risk_manager",
    "backend.core.auto_trader",
    "backend.core.strategy_executor",
    "backend.core.bankroll_allocator",
    "backend.core.agi_health_check",
    "backend.core.trade_forensics",
    "backend.core.strategy_rehabilitator",
    "backend.core.monitoring_job",
    "backend.core.settlement_ws",
    "backend.core.forensics_integration",
    "backend.core.activity_logger",
    "backend.core.retrain_trigger",
    "backend.core.auto_improve",
    "backend.core.weather_signals",
    "backend.core.backtester",
    "backend.core.historical_data_collector",
    "backend.core.strategy_performance_registry",
    "backend.core.llm_cost_tracker",
    "backend.core.risk_profiles",
    "backend.core.settlement_helpers",
    "backend.core.shadow_validation",
    "backend.core.orchestrator",
    "backend.core.scheduler",
    "backend.core.scheduling_strategies",
    "backend.core.settlement",
    "backend.core.strategy_ranker",
    "backend.core.agi_orchestrator",
    "backend.core.agi_jobs",
    "backend.core.fronttest_validator",
    "backend.core.cache_cleanup",
    "backend.core.auto_redeem",
    # New subpackage paths (after core/ refactor)
    "backend.core.settlement.settlement",
    "backend.core.settlement.settlement_helpers",
    "backend.core.settlement.settlement_ws",
    "backend.core.settlement.auto_redeem",
    "backend.core.risk.risk_manager",
    "backend.core.risk.risk_profiles",
    "backend.core.scheduling.scheduler",
    "backend.core.scheduling.scheduling_strategies",
    "backend.core.learning.auto_improve",
    "backend.core.learning.retrain_trigger",
    "backend.core.wallet.bankroll_allocator",
    "backend.core.wallet.bankroll_reconciliation",
    "backend.core.wallet.wallet_reconciliation",
    "backend.strategies.wallet_sync",
    "backend.strategies.base",
    "backend.modules.execution.copy_trader",
    "backend.modules.data_feeds.whale_pnl_tracker",
    "backend.application.strategy.shadow_runner",
    "backend.application.agi.evolution_jobs",
    "backend.application.agi.knowledge_graph",
    "backend.api.lifespan",
    "backend.api.activities",
    "backend.api.analytics",
    "backend.api.auto_trader",
    "backend.api.backtest",
    "backend.api.copy_trading",
    "backend.api.system",
    "backend.api.wallets",
    "backend.api.sync",
    "backend.ai.prediction_engine",
    "backend.ai.feedback_tracker",
    "backend.ai.impact_measurer",
    "backend.ai.meta_learner",
    "backend.ai.proposal_generator",
    "backend.ai.rejection_learner",
    "backend.ai.self_review",
    "backend.ai.strategy_composer",
    "backend.ai.counterfactual_scorer",
    "backend.core.proposal_applier",
    "backend.core.proposal_executor",
]


@pytest.fixture(scope="function")
def db():
    connection = test_engine.connect()
    connection.begin()
    nested = connection.begin_nested()

    _conn_session_factory = sessionmaker(
        autocommit=False, autoflush=False, bind=connection
    )

    _original_sl = _db_mod.SessionLocal
    _db_mod.SessionLocal = _conn_session_factory

    # Patch SessionLocal in every module that imported it at module level
    # so production code reaches the test connection, not a stale engine.
    _saved_refs: dict[str, object] = {}
    for mod_name in _MODULES_WITH_SESSIONLOCAL:
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, "SessionLocal"):
            _saved_refs[mod_name] = mod.SessionLocal
            mod.SessionLocal = _conn_session_factory

    session = _conn_session_factory()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(sess, txn):
        if nested.is_active:
            return
        try:
            connection.begin_nested()
        except Exception:
            pass

    yield session

    _db_mod.SessionLocal = _original_sl
    for mod_name, orig in _saved_refs.items():
        mod = sys.modules.get(mod_name)
        if mod is not None:
            mod.SessionLocal = orig

    try:
        session.close()
    except Exception:
        pass
    try:
        connection.close()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def cleanup_proposals_between_tests(db):
    from backend.models.database import (
        BotState,
        Trade,
        Signal,
        StrategyProposal,
        StrategyConfig,
        ActivityLog,
        DecisionLog,
        TradeAttempt,
        MiroFishSignal,
        ShadowTrade,
    )
    from backend.models.kg_models import ExperimentRecord

    db.query(Trade).delete()
    db.query(Signal).delete()
    db.query(StrategyProposal).delete()
    db.query(ActivityLog).delete()
    db.query(DecisionLog).delete()
    db.query(TradeAttempt).delete()
    db.query(MiroFishSignal).delete()
    db.query(StrategyConfig).delete()
    db.query(ExperimentRecord).delete()
    db.query(ShadowTrade).delete()

    db.info["allow_live_financial_update"] = True
    for mode in ["paper", "testnet", "live"]:
        state = db.query(BotState).filter_by(mode=mode).first()
        if not state:
            db.add(
                BotState(
                    mode=mode,
                    bankroll=10000.0 if mode != "testnet" else 100.0,
                    paper_bankroll=10000.0,
                    total_trades=0,
                    winning_trades=0,
                    total_pnl=0.0,
                    is_running=True,
                )
            )
        else:
            state.bankroll = 10000.0 if mode != "testnet" else 100.0
            state.total_trades = 0
            state.winning_trades = 0
            state.total_pnl = 0.0
            state.is_running = True
            state.paper_bankroll = 10000.0
            state.paper_pnl = 0.0
            state.paper_trades = 0
            state.paper_wins = 0
            state.testnet_bankroll = 100.0
            state.testnet_pnl = 0.0
            state.testnet_trades = 0
            state.testnet_wins = 0

    db.commit()
    db.info.pop("allow_live_financial_update", None)
    yield


@pytest.fixture(autouse=True)
def reset_provider_registry():
    from backend.data.source_registry import DataSourceRegistry
    from backend.markets.provider_registry import MarketProviderRegistry

    DataSourceRegistry.reset()
