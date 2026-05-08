
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.dynamic_prompt_engine import (
    DynamicPromptEngine,
    PromptVersion,
    PromptComparison,
)
from backend.models.kg_models import Base, KGEntity as KGEntityModel


def make_prompt_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    engine = DynamicPromptEngine(session=session)
    return engine, session, engine


class TestDynamicPromptEngineGetPrompt:
    def test_get_prompt_empty_when_no_versions(self):
        engine, _, _ = make_prompt_session()
        result = engine.get_prompt("nonexistent")
        assert result == ""

    def test_get_prompt_returns_latest_version(self):
        engine, session, _ = make_prompt_session()
        entity = KGEntityModel(
            entity_type="prompt_version",
            entity_id="prompt:test:v1",
            properties={
                "template_id": "test",
                "version": "v1",
                "prompt_text": "You are a trader. {context}",
                "win_rate": 0.5,
                "trade_count": 10,
            },
        )
        session.add(entity)
        session.commit()
        result = engine.get_prompt("test")
        assert "You are a trader" in result

    def test_get_prompt_with_context_replacement(self):
        engine, session, _ = make_prompt_session()
        entity = KGEntityModel(
            entity_type="prompt_version",
            entity_id="prompt:test:v1",
            properties={
                "template_id": "test",
                "version": "v1",
                "prompt_text": "Analyze {market} with {confidence}",
                "win_rate": 0.5,
                "trade_count": 10,
            },
        )
        session.add(entity)
        session.commit()
        result = engine.get_prompt("test", context={"market": "BTC", "confidence": "0.8"})
        assert "BTC" in result
        assert "0.8" in result


class TestDynamicPromptEngineEvolve:
    def test_evolve_creates_new_version(self):
        engine, session, _ = make_prompt_session()
        entity = KGEntityModel(
            entity_type="prompt_version",
            entity_id="prompt:test:v1",
            properties={
                "template_id": "test",
                "version": "v1",
                "prompt_text": "Original prompt",
                "win_rate": 0.5,
                "trade_count": 10,
            },
        )
        session.add(entity)
        session.commit()
        outcomes = [{"result": "win"} for _ in range(10)]
        result = engine.evolve_prompt("test", outcomes)
        assert result.version.startswith("v")
        assert result.win_rate == 1.0
        assert result.trade_count == 10

    def test_evolve_stores_in_kg(self):
        engine, session, _ = make_prompt_session()
        entity = KGEntityModel(
            entity_type="prompt_version",
            entity_id="prompt:test:v1",
            properties={
                "template_id": "test",
                "version": "v1",
                "prompt_text": "Original",
                "win_rate": 0.5,
                "trade_count": 10,
            },
        )
        session.add(entity)
        session.commit()
        outcomes = [{"result": "win"} for _ in range(5)]
        engine.evolve_prompt("test", outcomes)
        versions = session.query(KGEntityModel).filter_by(entity_type="prompt_version").all()
        assert len(versions) == 2

    def test_evolve_creates_relation(self):
        engine, session, _ = make_prompt_session()
        entity = KGEntityModel(
            entity_type="prompt_version",
            entity_id="prompt:test:v1",
            properties={
                "template_id": "test",
                "version": "v1",
                "prompt_text": "Original",
                "win_rate": 0.5,
                "trade_count": 10,
            },
        )
        session.add(entity)
        session.commit()
        outcomes = [{"result": "win"} for _ in range(5)]
        engine.evolve_prompt("test", outcomes)
        from backend.models.kg_models import KGRelation as KGRelationModel
        relations = session.query(KGRelationModel).all()
        assert len(relations) >= 1


class TestDynamicPromptEngineCompare:
    def test_compare_returns_winner_based_on_win_rate(self):
        engine, session, _ = make_prompt_session()
        entity_a = KGEntityModel(
            entity_type="prompt_version",
            entity_id="prompt:test:va",
            properties={
                "template_id": "test",
                "version": "va",
                "prompt_text": "Version A",
                "win_rate": 0.5,
                "trade_count": 60,
            },
        )
        entity_b = KGEntityModel(
            entity_type="prompt_version",
            entity_id="prompt:test:vb",
            properties={
                "template_id": "test",
                "version": "vb",
                "prompt_text": "Version B",
                "win_rate": 0.6,
                "trade_count": 60,
            },
        )
        session.add_all([entity_a, entity_b])
        session.commit()
        result = engine.compare_prompts("test", "va", "vb")
        assert result.winner == "vb"
        assert result.confidence > 0.0

    def test_compare_keeps_version_a_when_insufficient_trades(self):
        engine, session, _ = make_prompt_session()
        entity_a = KGEntityModel(
            entity_type="prompt_version",
            entity_id="prompt:test:va",
            properties={
                "template_id": "test",
                "version": "va",
                "prompt_text": "Version A",
                "win_rate": 0.5,
                "trade_count": 10,
            },
        )
        entity_b = KGEntityModel(
            entity_type="prompt_version",
            entity_id="prompt:test:vb",
            properties={
                "template_id": "test",
                "version": "vb",
                "prompt_text": "Version B",
                "win_rate": 0.9,
                "trade_count": 10,
            },
        )
        session.add_all([entity_a, entity_b])
        session.commit()
        result = engine.compare_prompts("test", "va", "vb")
        assert result.winner == "va"

    def test_compare_nonexistent_version(self):
        engine, _, _ = make_prompt_session()
        result = engine.compare_prompts("test", "v_nonexistent", "v_also_nonexistent")
        assert result.winner is None


class TestDynamicPromptEngineRollback:
    def test_rollback_removes_newer_versions(self):
        engine, session, _ = make_prompt_session()
        entity_v1 = KGEntityModel(
            entity_type="prompt_version",
            entity_id="prompt:test:v1",
            properties={
                "template_id": "test",
                "version": "v1",
                "prompt_text": "V1",
                "win_rate": 0.5,
                "trade_count": 10,
            },
        )
        entity_v2 = KGEntityModel(
            entity_type="prompt_version",
            entity_id="prompt:test:v2",
            properties={
                "template_id": "test",
                "version": "v2",
                "prompt_text": "V2",
                "win_rate": 0.6,
                "trade_count": 20,
            },
        )
        session.add_all([entity_v1, entity_v2])
        session.commit()
        deleted = engine.rollback_prompt("test", "v1")
        assert deleted >= 1
        remaining = session.query(KGEntityModel).filter_by(entity_type="prompt_version").count()
        assert remaining == 1

    def test_rollback_nonexistent_version(self):
        engine, _, _ = make_prompt_session()
        deleted = engine.rollback_prompt("test", "v_nonexistent")
        assert deleted == 0


class TestPromptVersion:
    def test_to_dict(self):
        pv = PromptVersion(
            template_id="test",
            version="v1",
            prompt_text="Test prompt",
            win_rate=0.75,
            trade_count=100,
        )
        d = pv.to_dict()
        assert d["template_id"] == "test"
        assert d["version"] == "v1"
        assert d["win_rate"] == 0.75

    def test_from_dict(self):
        d = {
            "template_id": "test",
            "version": "v1",
            "prompt_text": "Test",
            "win_rate": 0.8,
            "trade_count": 50,
        }
        pv = PromptVersion.from_dict(d)
        assert pv.template_id == "test"
        assert pv.version == "v1"


class TestPromptComparison:
    def test_comparison_creation(self):
        pc = PromptComparison(version_a="va", version_b="vb", winner="vb", confidence=0.8)
        assert pc.version_a == "va"
        assert pc.winner == "vb"
        assert pc.confidence == 0.8
