"""AGI test fixtures — shared fixtures for AGI module tests."""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.agi_types import (  # noqa: F401
    AGIGoal,
    DecisionAuditEntry,
    ExperimentStatus,
    KGEntity,
    KGRelation,
    MarketRegime,
    RegimeTransition,
    StrategyBlock,
)
from backend.models.database import Base


@pytest.fixture
def agi_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    from backend.models.kg_models import KGEntity as KGEntityModel, KGRelation as KGRelationModel, MarketRegimeSnapshot, ExperimentRecord, DecisionAuditLog, LLMCostRecord
    KGEntityModel.__table__.create(engine, checkfirst=True)
    KGRelationModel.__table__.create(engine, checkfirst=True)
    MarketRegimeSnapshot.__table__.create(engine, checkfirst=True)
    ExperimentRecord.__table__.create(engine, checkfirst=True)
    DecisionAuditLog.__table__.create(engine, checkfirst=True)
    LLMCostRecord.__table__.create(engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def regime_data_bull():
    return {
        "prices": [100 + i * 0.5 for i in range(250)],
        "volumes": [1000 + i * 10 for i in range(250)],
        "sma_50": 115.0,
        "sma_200": 110.0,
        "atr": 2.0,
        "atr_percentile": 0.3,
        "drawdown": 0.02,
        "volume_trend": 0.5,
    }


@pytest.fixture
def regime_data_bear():
    return {
        "prices": [200 - i * 0.5 for i in range(250)],
        "volumes": [1000 - i * 5 for i in range(250)],
        "sma_50": 95.0,
        "sma_200": 100.0,
        "atr": 5.0,
        "atr_percentile": 0.7,
        "drawdown": 0.08,
        "volume_trend": -0.5,
    }


@pytest.fixture
def regime_data_sideways():
    return {
        "prices": [150 + (i % 10 - 5) * 0.1 for i in range(250)],
        "volumes": [500 for _ in range(250)],
        "sma_50": 150.1,
        "sma_200": 150.0,
        "atr": 1.0,
        "atr_percentile": 0.2,
        "drawdown": 0.01,
        "volume_trend": 0.0,
    }


@pytest.fixture
def regime_data_crisis():
    return {
        "prices": [200 - i * 2 for i in range(250)],
        "volumes": [2000 for _ in range(250)],
        "sma_50": 160.0,
        "sma_200": 180.0,
        "atr": 15.0,
        "atr_percentile": 0.95,
        "drawdown": 0.25,
        "volume_trend": -0.8,
    }


@pytest.fixture
def sample_kg_entity():
    return KGEntity(
        entity_type="strategy",
        entity_id="btc_momentum",
        properties={"win_rate": 0.65, "sharpe": 1.2},
    )


@pytest.fixture
def sample_kg_relation():
    return KGRelation(
        from_entity="btc_momentum",
        to_entity="bull_regime",
        relation_type="performs_well_in",
        weight=0.85,
        confidence=0.72,
        timestamp=datetime(2026, 4, 30, tzinfo=timezone.utc),
    )


@pytest.fixture
def sample_strategy_block():
    return StrategyBlock(
        signal_source="whale_tracker",
        filter="min_volume_1000",
        position_sizer="kelly_half",
        risk_rule="max_1pct",
        exit_rule="take_profit_10pct",
    )


@pytest.fixture
def mock_llm_response():
    return {
        "strategy_code": "def generated_strategy(market_data):\n    return {'signal': 'buy', 'confidence': 0.8}",
        "reasoning": "Momentum signal detected with high confidence",
        "cost_usd": 0.05,
        "token_count": 500,
    }


@pytest.fixture
def mock_market_data():
    return {
        "prices": [100 + i * 0.3 for i in range(250)],
        "volumes": [1000 for _ in range(250)],
        "sma_50": 112.0,
        "sma_200": 110.0,
        "atr": 3.0,
        "atr_percentile": 0.4,
        "drawdown": 0.03,
        "volume_trend": 0.2,
    }


@pytest.fixture
def shadow_mode_settings():
    with patch("backend.config.settings.ACTIVE_MODES", "paper"):
        yield


@pytest.fixture
def risk_bounding_settings():
    with patch("backend.config.settings.MAX_TRADE_SIZE", 50.0):
        with patch("backend.config.settings.DAILY_LOSS_LIMIT", 100.0):
            with patch("backend.config.settings.KELLY_FRACTION", 0.5):
                yield
