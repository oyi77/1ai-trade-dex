
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.knowledge_graph import KnowledgeGraph
from backend.core.agi_types import KGEntity, KGRelation, MarketRegime
from backend.models.kg_models import Base, KGEntity as KGEntityModel, KGRelation as KGRelationModel, DecisionAuditLog


def make_db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal(), engine


def make_kg_with_session():
    session, engine = make_db_session()
    kg = KnowledgeGraph(session=session)
    return kg, session, engine


class TestKGPersistEntity:
    def test_persist_new_entity(self):
        kg, session, _ = make_kg_with_session()
        entity = KGEntity(entity_type="strategy", entity_id="s:test1", properties={"win_rate": 0.6})
        result = kg.persist_entity(entity, db=session)
        assert result.entity_id == "s:test1"
        assert result.properties["win_rate"] == 0.6
        model = session.query(KGEntityModel).filter_by(entity_id="s:test1").first()
        assert model is not None
        assert model.properties["win_rate"] == 0.6

    def test_persist_updates_existing_entity(self):
        kg, session, _ = make_kg_with_session()
        entity = KGEntity(entity_type="strategy", entity_id="s:test1", properties={"v": 1})
        kg.persist_entity(entity, db=session)
        entity2 = KGEntity(entity_type="strategy", entity_id="s:test1", properties={"v": 2})
        result = kg.persist_entity(entity2, db=session)
        assert result.properties["v"] == 2
        count = session.query(KGEntityModel).filter_by(entity_id="s:test1").count()
        assert count == 1

    def test_persist_entity_audit_log(self):
        kg, session, _ = make_kg_with_session()
        entity = KGEntity(entity_type="regime", entity_id="r:bull", properties={})
        kg.persist_entity(entity, db=session)
        audit = session.query(DecisionAuditLog).filter_by(decision_type="kg_persist_entity").first()
        assert audit is not None
        assert "s:test1" in str(audit.input_data) or "r:bull" in str(audit.input_data)


class TestKGPersistRelation:
    def test_persist_relation_roundtrip(self):
        kg, session, _ = make_kg_with_session()
        e1 = KGEntity(entity_type="strategy", entity_id="s:a", properties={})
        e2 = KGEntity(entity_type="regime", entity_id="r:bull", properties={})
        kg.persist_entity(e1, db=session)
        kg.persist_entity(e2, db=session)
        rel = KGRelation(from_entity="s:a", to_entity="r:bull", relation_type="performs_well_in", weight=0.8, confidence=0.9)
        result = kg.persist_relation(rel, db=session)
        assert result.from_entity == "s:a"
        assert result.to_entity == "r:bull"
        # Load back
        relations = kg.load_relations("s:a", db=session)
        assert len(relations) == 1
        assert relations[0].relation_type == "performs_well_in"

    def test_persist_relation_missing_entity(self):
        kg, session, _ = make_kg_with_session()
        rel = KGRelation(from_entity="s:nonexistent", to_entity="r:bull", relation_type="x", weight=0.5, confidence=0.5)
        with pytest.raises(ValueError, match="does not exist"):
            kg.persist_relation(rel, db=session)


class TestKGLoadEntity:
    def test_load_existing_entity(self):
        kg, session, _ = make_kg_with_session()
        entity = KGEntity(entity_type="strategy", entity_id="s:load1", properties={"key": "val"})
        kg.persist_entity(entity, db=session)
        loaded = kg.load_entity("s:load1", db=session)
        assert loaded is not None
        assert loaded.entity_id == "s:load1"
        assert loaded.properties["key"] == "val"

    def test_load_nonexistent_entity(self):
        kg, session, _ = make_kg_with_session()
        loaded = kg.load_entity("s:doesnotexist", db=session)
        assert loaded is None


class TestKGLoadRelations:
    def test_load_relations_with_filter(self):
        kg, session, _ = make_kg_with_session()
        e1 = KGEntity(entity_type="strategy", entity_id="s:a", properties={})
        e2 = KGEntity(entity_type="regime", entity_id="r:bull", properties={})
        e3 = KGEntity(entity_type="regime", entity_id="r:bear", properties={})
        kg.persist_entity(e1, db=session)
        kg.persist_entity(e2, db=session)
        kg.persist_entity(e3, db=session)
        rel1 = KGRelation(from_entity="s:a", to_entity="r:bull", relation_type="performs_well_in", weight=0.8, confidence=0.9)
        rel2 = KGRelation(from_entity="s:a", to_entity="r:bear", relation_type="performs_poorly_in", weight=0.3, confidence=0.8)
        kg.persist_relation(rel1, db=session)
        kg.persist_relation(rel2, db=session)
        bull_rels = kg.load_relations("s:a", relation_type="performs_well_in", db=session)
        assert len(bull_rels) == 1
        assert bull_rels[0].to_entity == "r:bull"
        all_rels = kg.load_relations("s:a", db=session)
        assert len(all_rels) == 2


class TestKGSnapshotAndRollback:
    def test_create_snapshot_returns_id(self):
        kg, session, _ = make_kg_with_session()
        snap_id = kg.create_snapshot()
        assert snap_id.startswith("snap_")
        assert len(snap_id) > 10

    def test_snapshot_audit_entry(self):
        kg, session, _ = make_kg_with_session()
        snap_id = kg.create_snapshot()
        audit = session.query(DecisionAuditLog).filter_by(decision_type="kg_snapshot").first()
        assert audit is not None
        assert snap_id in str(audit.output_data) or snap_id in str(audit.input_data)

    def test_rollback_removes_post_snapshot_data(self):
        kg, session, _ = make_kg_with_session()
        # Create pre-snapshot entity
        e1 = KGEntity(entity_type="strategy", entity_id="s:before", properties={"v": 1})
        kg.persist_entity(e1, db=session)
        snap_id = kg.create_snapshot()
        # Add post-snapshot data
        e2 = KGEntity(entity_type="strategy", entity_id="s:after", properties={"v": 2})
        kg.persist_entity(e2, db=session)
        rel = KGRelation(from_entity="s:before", to_entity="s:after", relation_type="related", weight=0.5, confidence=0.8)
        kg.persist_relation(rel, db=session)
        # Verify post-snapshot data exists
        assert kg.load_entity("s:after", db=session) is not None
        # Rollback
        deleted = kg.rollback_to_snapshot(snap_id)
        assert deleted >= 2  # at least entity + relation
        # Verify rollback
        assert kg.load_entity("s:before", db=session) is not None
        assert kg.load_entity("s:after", db=session) is None

    def test_rollback_audit_entry(self):
        kg, session, _ = make_kg_with_session()
        e1 = KGEntity(entity_type="strategy", entity_id="s:x", properties={})
        kg.persist_entity(e1, db=session)
        snap_id = kg.create_snapshot()
        e2 = KGEntity(entity_type="strategy", entity_id="s:y", properties={})
        kg.persist_entity(e2, db=session)
        kg.rollback_to_snapshot(snap_id)
        audit = session.query(DecisionAuditLog).filter_by(decision_type="kg_rollback").first()
        assert audit is not None
        assert snap_id in str(audit.input_data)

    def test_rollback_nonexistent_snapshot(self):
        kg, session, _ = make_kg_with_session()
        deleted = kg.rollback_to_snapshot("snap_doesnotexist")
        assert deleted == 0


class TestKGValidationEnhanced:
    def test_reject_confidence_below_01(self):
        kg, session, _ = make_kg_with_session()
        e1 = KGEntity(entity_type="strategy", entity_id="s:a", properties={})
        e2 = KGEntity(entity_type="regime", entity_id="r:bull", properties={})
        kg.persist_entity(e1, db=session)
        kg.persist_entity(e2, db=session)
        errors = kg.validate_relation("s:a", "r:bull", "performs_well_in", 0.5, 0.05)
        assert any("0.1" in e for e in errors)

    def test_accept_confidence_at_01(self):
        kg, session, _ = make_kg_with_session()
        e1 = KGEntity(entity_type="strategy", entity_id="s:a", properties={})
        e2 = KGEntity(entity_type="regime", entity_id="r:bull", properties={})
        kg.persist_entity(e1, db=session)
        kg.persist_entity(e2, db=session)
        errors = kg.validate_relation("s:a", "r:bull", "performs_well_in", 0.5, 0.1)
        assert not any("0.1" in e for e in errors)

    def test_reject_self_loop(self):
        kg, session, _ = make_kg_with_session()
        e1 = KGEntity(entity_type="strategy", entity_id="s:a", properties={})
        kg.persist_entity(e1, db=session)
        errors = kg.validate_relation("s:a", "s:a", "related", 0.5, 0.5)
        assert any("self-loop" in e for e in errors)

    def test_persist_rejects_self_loop(self):
        kg, session, _ = make_kg_with_session()
        e1 = KGEntity(entity_type="strategy", entity_id="s:a", properties={})
        kg.persist_entity(e1, db=session)
        rel = KGRelation(from_entity="s:a", to_entity="s:a", relation_type="related", weight=0.5, confidence=0.5)
        with pytest.raises(ValueError, match="self-loop"):
            kg.persist_relation(rel, db=session)

    def test_persist_rejects_low_confidence(self):
        kg, session, _ = make_kg_with_session()
        e1 = KGEntity(entity_type="strategy", entity_id="s:a", properties={})
        e2 = KGEntity(entity_type="regime", entity_id="r:bull", properties={})
        kg.persist_entity(e1, db=session)
        kg.persist_entity(e2, db=session)
        rel = KGRelation(from_entity="s:a", to_entity="r:bull", relation_type="x", weight=0.5, confidence=0.05)
        with pytest.raises(ValueError, match="0.1"):
            kg.persist_relation(rel, db=session)


class TestKGQueryRegimePerformance:
    def test_query_regime_performance(self):
        kg, session, _ = make_kg_with_session()
        e1 = KGEntity(entity_type="strategy", entity_id="s:test", properties={})
        e2 = KGEntity(entity_type="regime", entity_id="bull", properties={})
        kg.persist_entity(e1, db=session)
        kg.persist_entity(e2, db=session)
        rel = KGRelation(from_entity="s:test", to_entity="bull", relation_type="performs_well_in", weight=0.8, confidence=0.9)
        kg.persist_relation(rel, db=session)
        perf = kg.query_regime_performance("s:test", db=session)
        assert MarketRegime.BULL in perf
        assert perf[MarketRegime.BULL]["weight"] == 0.8

    def test_query_regime_performance_no_data(self):
        kg, session, _ = make_kg_with_session()
        perf = kg.query_regime_performance("s:nonexistent", db=session)
        assert perf == {}


class TestKGQueryBestStrategies:
    def test_query_best_strategies(self):
        kg, session, _ = make_kg_with_session()
        # Create regime
        regime = KGEntity(entity_type="regime", entity_id="bull", properties={})
        kg.persist_entity(regime, db=session)
        # Create strategies with different weights
        for i, w in enumerate([0.9, 0.6, 0.8]):
            s = KGEntity(entity_type="strategy", entity_id=f"s:strat{i}", properties={})
            kg.persist_entity(s, db=session)
            rel = KGRelation(from_entity=f"s:strat{i}", to_entity="bull", relation_type="performs_well_in", weight=w, confidence=0.9)
            kg.persist_relation(rel, db=session)
        best = kg.query_best_strategies(MarketRegime.BULL, db=session, limit=2)
        assert len(best) <= 2
        assert best[0].entity_id == "s:strat0"  # highest weight 0.9

    def test_query_best_strategies_no_regime(self):
        kg, session, _ = make_kg_with_session()
        best = kg.query_best_strategies(MarketRegime.CRISIS, db=session)
        assert best == []


class TestKGConcurrentAccess:
    def test_concurrent_entity_creation(self):
        """Verify no data corruption with sequential 'concurrent' writes."""
        kg, session, engine = make_kg_with_session()
        # Simulate concurrent writes by creating entities in sequence
        entities = []
        for i in range(5):
            e = KGEntity(entity_type="strategy", entity_id=f"s:concurrent{i}", properties={"i": i})
            result = kg.persist_entity(e, db=session)
            entities.append(result)
        count = session.query(KGEntityModel).count()
        assert count == 5

    def test_concurrent_relation_creation(self):
        kg, session, _ = make_kg_with_session()
        # Create entities first
        for i in range(3):
            e = KGEntity(entity_type="strategy", entity_id=f"s:cr{i}", properties={})
            kg.persist_entity(e, db=session)
        # Create relations
        for i in range(2):
            rel = KGRelation(from_entity=f"s:cr{i}", to_entity=f"s:cr{i+1}", relation_type="next", weight=0.5, confidence=0.8)
            kg.persist_relation(rel, db=session)
        count = session.query(KGRelationModel).count()
        assert count == 2
