"""Shared pytest fixtures for PolyEdge backend integration tests."""
# ruff: noqa: E402,F401,F811

import sys
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

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
sys.modules["backend.core.scheduler"] = _sched_stub

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
    Signal, Trade, BotState, StrategyConfig, DecisionLog, TradeAttempt,
    MarketWatch, WalletConfig, TradeContext, JobQueue, PendingApproval,
    AILog, ActivityLog, MiroFishSignal, StrategyProposal,
    PerformanceMetric, AuditLog, WhaleTransaction, BtcPriceSnapshot,
    ScanLog, CopyTraderEntry, SettlementEvent, EquitySnapshot,
    CalibrationRecord, ResearchItemDB, Alert, AlertConfig,
    Setting, SystemSettings, ErrorLog, Experiment, ShadowTrade,
)  # noqa: F401
from backend.models.backtest import BacktestRun, BacktestTrade  # noqa: F401
from backend.models.kg_models import LLMCostRecord  # noqa: F401
from backend.core.strategy_performance_registry import StrategyPerformanceSnapshot
from backend.models.database import TransactionEvent
from backend.models.outcome_tables import StrategyOutcome, StrategyHealthRecord, ParamChange, TradingCalibrationRecord  # noqa: F401
from backend.models.kg_models import ExperimentRecord, DecisionAuditLog  # noqa: F401
from backend.models.historical_data import HistoricalCandle, MarketOutcome, WeatherSnapshot  # noqa: F401
from backend.core.risk_profiles import RiskProfileRow  # noqa: F401

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
]


@pytest.fixture(scope="function")
def db():
    connection = test_engine.connect()
    connection.begin()
    nested = connection.begin_nested()

    _conn_session_factory = sessionmaker(autocommit=False, autoflush=False, bind=connection)

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
        BotState, Trade, Signal, StrategyProposal, StrategyConfig, ActivityLog, DecisionLog, TradeAttempt, MiroFishSignal, ShadowTrade
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
            db.add(BotState(
                mode=mode,
                bankroll=10000.0 if mode != "testnet" else 100.0,
                total_trades=0,
                winning_trades=0,
                total_pnl=0.0,
                is_running=True,
            ))
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
