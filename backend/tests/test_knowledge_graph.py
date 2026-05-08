"""Tests for KnowledgeGraph — entity/relation CRUD, queries, rollback, validation."""
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.agi_types import MarketRegime
from backend.core.knowledge_graph import KnowledgeGraph
from backend.models.database import Base


@pytest.fixture
def kg():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    graph = KnowledgeGraph(session=session)
    yield graph
    session.close()


class TestEntityCRUD:
    def test_add_entity(self, kg):
        entity = kg.add_entity("strategy", "btc_momentum", {"win_rate": 0.65, "sharpe": 1.2})
        assert entity.entity_type == "strategy"
        assert entity.entity_id == "btc_momentum"
        assert entity.properties["win_rate"] == 0.65

    def test_get_entity(self, kg):
        kg.add_entity("strategy", "weather_emos", {"win_rate": 0.55})
        entity = kg.get_entity("weather_emos")
        assert entity is not None
        assert entity.entity_id == "weather_emos"
        assert entity.properties["win_rate"] == 0.55

    def test_get_entity_not_found(self, kg):
        entity = kg.get_entity("nonexistent")
        assert entity is None

    def test_add_entity_upsert(self, kg):
        kg.add_entity("strategy", "btc_momentum", {"win_rate": 0.6})
        updated = kg.add_entity("strategy", "btc_momentum", {"win_rate": 0.7, "sharpe": 1.5})
        assert updated.properties["win_rate"] == 0.7
        assert updated.properties["sharpe"] == 1.5

    def test_add_entity_empty_properties(self, kg):
        entity = kg.add_entity("regime", "bull_2026_q1")
        assert entity.properties == {}


class TestRelationCRUD:
    def test_add_relation(self, kg):
        kg.add_entity("strategy", "btc_momentum")
        kg.add_entity("regime", "bull")
        rel = kg.add_relation("btc_momentum", "bull", "performs_well_in", 0.85, 0.72)
        assert rel is not None
        assert rel.from_entity == "btc_momentum"
        assert rel.to_entity == "bull"
        assert rel.relation_type == "performs_well_in"
        assert rel.weight == 0.85

    def test_add_relation_missing_entity(self, kg):
        kg.add_entity("strategy", "btc_momentum")
        rel = kg.add_relation("btc_momentum", "nonexistent", "performs_well_in", 0.5, 0.5)
        assert rel is None

    def test_get_related(self, kg):
        kg.add_entity("strategy", "btc_momentum")
        kg.add_entity("regime", "bull")
        kg.add_entity("regime", "bear")
        kg.add_relation("btc_momentum", "bull", "performs_well_in", 0.85, 0.72)
        kg.add_relation("btc_momentum", "bear", "performs_poorly_in", 0.3, 0.5)
        related = kg.get_related("btc_momentum")
        assert len(related) == 2

    def test_get_related_filtered(self, kg):
        kg.add_entity("strategy", "btc_momentum")
        kg.add_entity("regime", "bull")
        kg.add_entity("regime", "bear")
        kg.add_relation("btc_momentum", "bull", "performs_well_in", 0.85, 0.72)
        kg.add_relation("btc_momentum", "bear", "performs_poorly_in", 0.3, 0.5)
        related = kg.get_related("btc_momentum", relation_type="performs_well_in")
        assert len(related) == 1
        assert related[0].entity_id == "bull"


class TestPatternMatching:
    def test_find_pattern(self, kg):
        kg.add_entity("strategy", "btc_momentum", {"win_rate": 0.65})
        kg.add_entity("regime", "bull")
        kg.add_relation("btc_momentum", "bull", "performs_well_in", 0.85, 0.72)
        results = kg.find_pattern("performs_well_in_bull")
        assert len(results) == 1
        assert results[0].entity_id == "btc_momentum"

    def test_get_strategies_for_regime(self, kg):
        kg.add_entity("strategy", "btc_momentum", {"win_rate": 0.65})
        kg.add_entity("strategy", "copy_trader", {"win_rate": 0.55})
        kg.add_entity("regime", "bull")
        kg.add_relation("btc_momentum", "bull", "performs_well_in", 0.85, 0.72)
        kg.add_relation("copy_trader", "bull", "performs_well_in", 0.6, 0.5)
        results = kg.get_strategies_for_regime(MarketRegime.BULL)
        assert len(results) == 2

    def test_get_regime_performance(self, kg):
        kg.add_entity("strategy", "btc_momentum")
        kg.add_entity("regime", "bull")
        kg.add_entity("regime", "bear")
        kg.add_relation("btc_momentum", "bull", "performs_well_in", 0.85, 0.72)
        kg.add_relation("btc_momentum", "bear", "performs_poorly_in", 0.3, 0.5)
        perf = kg.get_regime_performance("btc_momentum")
        assert "bull" in perf
        assert perf["bull"]["weight"] == 0.85
        assert "bear" in perf
        assert perf["bear"]["weight"] == 0.3


class TestRollback:
    def test_rollback_removes_entities_after_timestamp(self, kg):
        _before = datetime.now(timezone.utc)
        kg.add_entity("strategy", "btc_momentum")
        kg.add_entity("strategy", "weather_emos")
        after = datetime.now(timezone.utc) + timedelta(hours=1)
        deleted = kg.rollback_to(after)
        assert deleted == 0
        assert kg.get_entity("btc_momentum") is not None

    def test_rollback_removes_recent_data(self, kg):
        kg.add_entity("strategy", "btc_momentum")
        import time
        time.sleep(1.1)
        cutoff = datetime.now(timezone.utc)
        time.sleep(0.1)
        kg.add_entity("strategy", "new_strategy")
        deleted = kg.rollback_to(cutoff)
        assert deleted >= 1
        assert kg.get_entity("btc_momentum") is not None
        assert kg.get_entity("new_strategy") is None


class TestValidation:
    def test_validate_entity_missing_fields(self, kg):
        errors = kg.validate_entity("", "", None)
        assert "entity_type is required" in errors
        assert "entity_id is required" in errors

    def test_validate_entity_valid(self, kg):
        errors = kg.validate_entity("strategy", "btc_momentum", {"win_rate": 0.65})
        assert len(errors) == 0

    def test_validate_relation_missing_entities(self, kg):
        errors = kg.validate_relation("nonexistent", "also_nonexistent", "test", 0.5, 0.5)
        assert any("does not exist" in e for e in errors)

    def test_validate_relation_weight_bounds(self, kg):
        kg.add_entity("strategy", "btc_momentum")
        kg.add_entity("regime", "bull")
        errors = kg.validate_relation("btc_momentum", "bull", "test", 1.5, 0.5)
        assert any("weight" in e for e in errors)
        errors = kg.validate_relation("btc_momentum", "bull", "test", 0.5, -0.1)
        assert any("confidence" in e for e in errors)
