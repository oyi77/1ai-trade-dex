"""Tests for FinancialKnowledgeManager — register/query/store methods."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.cognitive_core import MockCore
from backend.core.financial_knowledge import FinancialKnowledgeManager
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


@pytest.fixture
def core():
    return MockCore()


@pytest.fixture
def fkm(kg, core):
    return FinancialKnowledgeManager(kg, core)


class TestAlphaSignalManagement:
    def test_register_alpha_signal(self, fkm):
        entity = fkm.register_alpha_signal(
            signal_id="momentum_breakout",
            signal_type="momentum",
            universe="crypto",
            lookback=20,
            ic=0.05,
            ir=0.8,
        )
        assert entity.entity_type == "alpha_signal"
        assert entity.entity_id == "alpha:momentum_breakout"
        assert entity.properties["signal_type"] == "momentum"
        assert entity.properties["universe"] == "crypto"
        assert entity.properties["lookback"] == 20
        assert entity.properties["ic"] == 0.05

    def test_register_alpha_stored_in_core(self, fkm, core):
        fkm.register_alpha_signal(
            signal_id="vol_squeeze",
            signal_type="volatility",
            universe="polymarket",
            lookback=10,
        )
        memories = core.recall("vol_squeeze", namespace="alpha_signals")
        assert len(memories) >= 1

    def test_get_alphas_for_regime(self, fkm, kg):
        # Register alpha and regime, link them
        fkm.register_alpha_signal("test_alpha", "momentum", "crypto", 20)
        kg.add_entity("regime", "regime:bull")
        kg.add_relation("alpha:test_alpha", "regime:bull", "performs_well_in", 0.8, 0.7)
        results = fkm.get_alphas_for_regime("bull")
        assert len(results) == 1
        assert results[0].entity_id == "alpha:test_alpha"

    def test_get_alphas_for_regime_empty(self, fkm):
        results = fkm.get_alphas_for_regime("nonexistent_regime")
        assert results == []

    def test_update_alpha_performance(self, fkm):
        fkm.register_alpha_signal("my_alpha", "mean_reversion", "stocks", 5)
        fkm.update_alpha_performance("my_alpha", ic=0.08, ir=1.2)
        entity = fkm._kg.get_entity("alpha:my_alpha")
        assert entity is not None
        assert entity.properties["ic"] == 0.08
        assert entity.properties["ir"] == 1.2

    def test_update_alpha_performance_missing(self, fkm):
        # Should not raise, just log warning
        fkm.update_alpha_performance("nonexistent", ic=0.1, ir=1.0)


class TestStrategyTemplateManagement:
    def test_register_strategy_template(self, fkm):
        entity = fkm.register_strategy_template(
            template_id="mean_revert_1h",
            strategy_class="MeanReversionStrategy",
            entry={"signal": "z_score_reversal", "min_confidence": 0.6},
            exit={"take_profit_pct": 0.08, "stop_loss_pct": 0.04},
            risk={"max_position_pct": 0.05, "kelly_fraction": 0.25},
            regime_effectiveness={"sideways": 0.8, "bull": 0.4, "bear": 0.3},
            description="Mean reversion on 1h timeframe",
        )
        assert entity.entity_type == "strategy_template"
        assert entity.entity_id == "template:mean_revert_1h"
        assert entity.properties["strategy_class"] == "MeanReversionStrategy"
        assert entity.properties["regime_effectiveness"]["sideways"] == 0.8

    def test_register_template_stored_in_core(self, fkm, core):
        fkm.register_strategy_template(
            template_id="t1",
            strategy_class="TestStrategy",
            entry={"signal": "test"},
            exit={},
            risk={},
        )
        memories = core.recall("t1", namespace="strategy_templates")
        assert len(memories) >= 1

    def test_get_templates_for_regime(self, fkm):
        fkm.register_strategy_template(
            template_id="t_bull",
            strategy_class="BullStrategy",
            entry={"signal": "bull_signal"},
            exit={},
            risk={},
            regime_effectiveness={"bull": 0.9, "bear": 0.1},
        )
        fkm.register_strategy_template(
            template_id="t_bear",
            strategy_class="BearStrategy",
            entry={"signal": "bear_signal"},
            exit={},
            risk={},
            regime_effectiveness={"bull": 0.1, "bear": 0.85},
        )
        bull_templates = fkm.get_templates_for_regime("bull")
        assert len(bull_templates) == 1
        assert bull_templates[0].entity_id == "template:t_bull"

    def test_get_templates_for_regime_empty(self, fkm):
        results = fkm.get_templates_for_regime("crisis")
        assert results == []


class TestTradeMemory:
    def test_store_trade_with_context(self, fkm, kg):
        fkm.store_trade_with_context(
            trade_id="trade_001",
            strategy="longshot_bias",
            regime="sideways",
            events=["price_spike", "volume_surge"],
            lesson="Longshot NO bias works best in calm markets",
        )
        entity = kg.get_entity("trade_ctx:trade_001")
        assert entity is not None
        assert entity.properties["strategy"] == "longshot_bias"
        assert entity.properties["regime"] == "sideways"
        assert "price_spike" in entity.properties["events"]
        assert entity.properties["lesson"] == "Longshot NO bias works best in calm markets"

    def test_store_trade_creates_relations(self, fkm, kg):
        fkm.store_trade_with_context("t2", "momentum", "bull", [], "test lesson")
        # Should have executed_by relation to strategy
        related = kg.get_related("trade_ctx:t2", relation_type="executed_by")
        assert len(related) >= 1

    def test_store_trade_lesson_in_core(self, fkm, core):
        fkm.store_trade_with_context("t3", "arb", "bear", [], "arb lesson")
        memories = core.recall("arb", namespace="trade_lessons")
        assert len(memories) >= 1

    def test_find_similar_trades(self, fkm):
        fkm.store_trade_with_context("s1", "momentum", "bull", [], "lesson1")
        fkm.store_trade_with_context("s2", "momentum", "bear", [], "lesson2")
        fkm.store_trade_with_context("s3", "arb", "bull", [], "lesson3")
        # Match by strategy
        results = fkm.find_similar_trades("momentum", "sideways")
        assert len(results) == 2  # both momentum trades match

    def test_find_similar_trades_by_regime(self, fkm):
        fkm.store_trade_with_context("r1", "strat_a", "bull", [], "l1")
        fkm.store_trade_with_context("r2", "strat_b", "bull", [], "l2")
        fkm.store_trade_with_context("r3", "strat_a", "bear", [], "l3")
        results = fkm.find_similar_trades("strat_c", "bull")
        assert len(results) == 2  # matches by regime

    def test_find_similar_trades_limit(self, fkm):
        for i in range(20):
            fkm.store_trade_with_context(f"lim_{i}", "s", "r", [], f"lesson_{i}")
        results = fkm.find_similar_trades("s", "r", limit=5)
        assert len(results) == 5

    def test_get_lesson_for_context(self, fkm):
        fkm.store_trade_with_context("lg1", "test_strat", "bull", [], "important lesson")
        lesson = fkm.get_lesson_for_context("test_strat", "bull")
        assert lesson == "important lesson"

    def test_get_lesson_for_context_none(self, fkm):
        lesson = fkm.get_lesson_for_context("unknown", "unknown")
        assert lesson is None


class TestCrossDomainReasoning:
    def test_suggest_strategy_for_conditions(self, fkm, kg):
        fkm.register_strategy_template(
            template_id="mr_bull",
            strategy_class="MR",
            entry={"signal": "x"},
            exit={},
            risk={},
            regime_effectiveness={"bull": 0.85},
            description="MR in bull",
        )
        kg.add_entity("regime", "regime:bull")
        kg.add_entity("strategy", "strategy:alpha_strat")
        kg.add_relation("strategy:alpha_strat", "regime:bull", "performs_well_in", 0.9, 0.8)

        suggestions = fkm.suggest_strategy_for_conditions("bull", "BTC")
        assert len(suggestions) >= 1
        # Template should appear
        template_suggestions = [s for s in suggestions if s.get("source") == "template"]
        assert len(template_suggestions) == 1
        assert template_suggestions[0]["template_id"] == "template:mr_bull"

    def test_suggest_strategy_empty(self, fkm):
        suggestions = fkm.suggest_strategy_for_conditions("crisis", "UNKNOWN")
        assert suggestions == []

    def test_get_knowledge_gaps(self, fkm):
        gaps = fkm.get_knowledge_gaps()
        assert len(gaps) > 0  # fresh KG should have gaps
        assert any("alpha signals" in g.lower() for g in gaps)

    def test_get_knowledge_gaps_with_data(self, fkm):
        # Add enough data to reduce gaps
        for i in range(5):
            fkm.register_alpha_signal(f"a{i}", "type", "uni", 10)
            fkm.register_strategy_template(f"t{i}", "cls", {}, {}, {})
        for i in range(15):
            fkm.store_trade_with_context(f"tr{i}", "str", "reg", [], "lesson")
        for r in ["bull", "bear", "sideways"]:
            fkm._kg.add_entity("regime", f"regime:{r}")
        gaps = fkm.get_knowledge_gaps()
        # Should have fewer or no gaps now
        assert len(gaps) < 4
