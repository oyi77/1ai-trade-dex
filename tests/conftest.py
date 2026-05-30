"""Shared pytest fixtures for PolyEdge root-level integration tests."""

import sys
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Stub apscheduler before any imports
_sched_stub = MagicMock()
sys.modules.setdefault("apscheduler", MagicMock())
sys.modules.setdefault("apscheduler.schedulers", MagicMock())
sys.modules.setdefault("apscheduler.schedulers.asyncio", MagicMock())
sys.modules.setdefault("apscheduler.events", MagicMock())
sys.modules.setdefault("apscheduler.triggers", MagicMock())
sys.modules.setdefault("apscheduler.triggers.interval", MagicMock())
sys.modules.setdefault("apscheduler.triggers.cron", MagicMock())
sys.modules.setdefault("apscheduler.triggers.date", MagicMock())
sys.modules.setdefault("apscheduler.jobstores", MagicMock())
sys.modules.setdefault("apscheduler.jobstores.base", MagicMock())
sys.modules["backend.core.scheduler"] = _sched_stub

# Create in-memory test database
TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

# Patch database module before app import
from backend.models import database as _db_mod  # noqa: E402
from backend.models.database import Base  # noqa: E402

# Ensure all ORM models are registered with Base.metadata before create_all()
try:
    from backend.core.strategy_performance_registry import (
        StrategyPerformanceSnapshot,
    )  # noqa: F401
except Exception:
    pass
try:
    from backend.models.database import Trade, ShadowTrade  # noqa: F401
except Exception:
    pass

_db_mod.engine = test_engine
_db_mod.SessionLocal = TestSessionLocal

# Proactively patch backend.db.utils.SessionLocal so all modules share the same TestSessionLocal
try:
    from backend.db import utils as _db_utils_mod
    _db_utils_mod.SessionLocal = TestSessionLocal
except Exception:
    pass

# Create all tables (drop first to ensure schema is fresh)
Base.metadata.drop_all(bind=test_engine)
Base.metadata.create_all(bind=test_engine)
try:
    _db_mod.ensure_schema()
except Exception:
    pass

# Seed BotState
from backend.models.database import BotState
from backend.config import settings as _settings

_seed_db = TestSessionLocal()
try:
    for mode in ["paper", "testnet", "live"]:
        if not _seed_db.query(BotState).filter_by(mode=mode).first():
            initial_bankroll = (
                _settings.INITIAL_BANKROLL if mode != "testnet" else 100.0
            )
            _seed_db.add(
                BotState(
                    mode=mode,
                    bankroll=initial_bankroll,
                    total_trades=0,
                    winning_trades=0,
                    total_pnl=0.0,
                    is_running=True,
                )
            )
    _seed_db.commit()
finally:
    _seed_db.close()


@pytest.fixture(scope="function")
def db_session():
    """Fresh database session for each test."""
    session = TestSessionLocal()
    yield session
    session.rollback()
    session.close()


@pytest.fixture(scope="function")
def test_app():
    """FastAPI test client."""
    from fastapi.testclient import TestClient
    from backend.api.main import app
    from backend.models.database import get_db

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(scope="function")
def mock_mirofish():
    """Mock MiroFish API responses."""
    from unittest.mock import AsyncMock

    mock = AsyncMock()
    mock.get_signals = AsyncMock(return_value=[])
    mock.get_market_data = AsyncMock(return_value={})
    return mock


@pytest.fixture(scope="function")
def test_settings(monkeypatch):
    """Override settings for testing."""
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("SHADOW_MODE", "true")
    monkeypatch.setenv("INITIAL_BANKROLL", "10000.0")
    from backend.config import settings

    return settings


@pytest.fixture
def sample_ensemble_members():
    """31-member GEFS ensemble data for NYC on a warm day (~78F mean)."""
    import random

    random.seed(42)
    return [random.gauss(78.0, 3.0) for _ in range(31)]


@pytest.fixture
def sample_cold_ensemble():
    """31-member ensemble for a cold day (~45F mean)."""
    import random

    random.seed(7)
    return [random.gauss(45.0, 4.0) for _ in range(31)]
