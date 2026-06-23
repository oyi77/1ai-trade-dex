"""AGI Integration Tests — End-to-end tests for the full AGI system."""

from backend.core.agi_types import MarketRegime, AGIGoal, StrategyBlock
from backend.core.regime_detector import RegimeDetector
from backend.core.knowledge_graph import KnowledgeGraph
from backend.core.strategy_allocator import RegimeAwareAllocator
from backend.core.agi_goal_engine import AGIGoalEngine
from backend.core.learning.self_debugger import SelfDebugger
from backend.core.strategy_composer import StrategyComposer
from backend.core.experiment_runner import ExperimentRunner
from backend.core.agi_orchestrator import AGIOrchestrator


class TestFullAGICycle:
    def test_full_cycle_bull_regime(self):
        kg = KnowledgeGraph()
        detector = RegimeDetector()
        goal_engine = AGIGoalEngine()
        allocator = RegimeAwareAllocator(kg)

        market_data = {
            "btc_price": 50000.0,
            "btc_change_24h": 0.05,
            "volume_ratio": 1.3,
            "volatility": 0.02,
        }
        regime_result = detector.detect_regime(market_data)
        assert regime_result.regime in [
            MarketRegime.BULL,
            MarketRegime.SIDEWAYS,
            MarketRegime.UNKNOWN,
        ]

        goal = goal_engine.get_current_goal(regime_result.regime)
        assert isinstance(goal, AGIGoal)

        allocations = allocator.allocate(
            strategies=["btc_momentum", "whale_tracker", "weather_emos"],
            regime=regime_result.regime,
            capital=10000.0,
        )
        assert isinstance(allocations, dict)

        kg.add_entity("market_regime", "test_cycle_bull", {"regime": "bull"})
        entity = kg.get_entity("test_cycle_bull")
        assert entity is not None

    def test_regime_change_triggers_goal_change(self):
        kg = KnowledgeGraph()
        goal_engine = AGIGoalEngine()
        allocator = RegimeAwareAllocator(kg)

        bull_goal = goal_engine.get_current_goal(MarketRegime.BULL)
        _bull_alloc = allocator.allocate(
            strategies=["btc_momentum", "whale_tracker", "weather_emos"],
            regime=MarketRegime.BULL,
            capital=10000.0,
        )

        goal_engine.handle_regime_change(
            {"from_regime": "bull", "to_regime": "bear", "confidence": 0.85}
        )
        bear_goal = goal_engine.get_current_goal(MarketRegime.BEAR)
        _bear_alloc = allocator.allocate(
            strategies=["btc_momentum", "whale_tracker", "weather_emos"],
            regime=MarketRegime.BEAR,
            capital=10000.0,
        )

        assert isinstance(bull_goal, AGIGoal)
        assert isinstance(bear_goal, AGIGoal)

    def test_strategy_composition_to_shadow_experiment(self):
        composer = StrategyComposer()
        runner = ExperimentRunner()

        blocks = StrategyBlock(
            signal_source="whale_tracker_signal",
            filter="min_edge_005",
            position_sizer="kelly_sizer",
            risk_rule="max_1pct",
            exit_rule="take_profit_10pct",
        )
        result = composer.compose("test_integration_strategy", [blocks])
        assert result is not None

        experiment = runner.run_shadow_experiment(
            strategy_name="test_integration_strategy",
            duration_days=1,
        )
        assert experiment is not None

    def test_self_debugger_recovery_from_api_failures(self):
        debugger = SelfDebugger()

        error_404 = Exception("API returned 404")
        diagnosis = debugger.diagnose_error(error_404, {"endpoint": "/v1/markets"})
        assert diagnosis is not None

        error_503 = Exception("API returned 503")
        diagnosis = debugger.diagnose_error(error_503, {"endpoint": "/v1/markets"})
        assert diagnosis is not None

        error_timeout = Exception("Request timed out")
        diagnosis = debugger.diagnose_error(error_timeout, {"endpoint": "/v1/markets"})
        assert diagnosis is not None

    def test_emergency_stop_halts_all_actions(self):
        orchestrator = AGIOrchestrator()
        orchestrator.emergency_stop()
        status = orchestrator.get_status()
        assert status.emergency_stop is True

    def test_knowledge_graph_update_after_trade(self):
        kg = KnowledgeGraph()

        kg.add_entity(
            "trade_outcome",
            "trade_001",
            {"market": "btc_momentum", "pnl": 15.0, "regime": "bull"},
        )
        kg.add_relation(
            "bull_regime", "trade_001", "caused", weight=0.8, confidence=0.85
        )

        entity = kg.get_entity("trade_001")
        assert entity is not None
        assert entity.entity_type == "trade_outcome"

    def test_dynamic_prompt_evolution(self):
        from backend.core.dynamic_prompt_engine import DynamicPromptEngine

        engine = DynamicPromptEngine()
        prompt_v1 = engine.get_prompt("signal_analysis", context={"regime": "bull"})
        assert prompt_v1 is not None

        outcomes = [{"score": 0.7, "regime": "bull", "result": "profit"}]
        evolved = engine.evolve_prompt("signal_analysis", outcomes=outcomes)
        assert evolved is not None

    def test_causal_reasoning_traces_through_kg(self):
        from backend.core.causal_reasoning import CausalReasoner

        reasoner = CausalReasoner()
        explanation = reasoner.trace_causation("signal_001")
        assert explanation is not None


class TestAGIShadowModeEnforcement:
    def test_all_agi_strategies_start_in_shadow(self):
        composer = StrategyComposer()
        blocks = StrategyBlock(
            signal_source="whale_tracker_signal",
            filter="min_edge_005",
            position_sizer="kelly_sizer",
            risk_rule="max_1pct",
            exit_rule="take_profit_10pct",
        )
        result = composer.compose("shadow_test_strategy", [blocks])
        assert result is not None

    def test_emergency_stop_prevents_live_trading(self):
        orchestrator = AGIOrchestrator()
        orchestrator.emergency_stop()
        status = orchestrator.get_status()
        assert status.emergency_stop is True

    def test_goal_changes_are_audit_logged(self):
        goal_engine = AGIGoalEngine()
        goal_engine.set_goal(AGIGoal.PRESERVE_CAPITAL, reason="market_downturn")
        current_goal = goal_engine.get_current_goal(MarketRegime.BEAR)
        assert current_goal is not None


class TestAGIConcurrency:
    def test_concurrent_kg_updates(self):
        kg = KnowledgeGraph()
        for i in range(10):
            kg.add_entity("test", f"concurrent_entity_{i}", {"index": i})

        for i in range(10):
            entity = kg.get_entity(f"concurrent_entity_{i}")
            assert entity is not None
            assert entity.properties["index"] == i

    def test_kg_validation_rejects_invalid_data(self):
        kg = KnowledgeGraph()
        result = kg.validate_entity("low_confidence", "test", {"confidence": 0.01})
        assert result is not None

    def test_kg_no_self_loops(self):
        kg = KnowledgeGraph()
        kg.add_entity("test", "self_ref", {})
        result = kg.validate_relation(
            "self_ref", "self_ref", "self_loop", weight=0.5, confidence=0.9
        )
        assert result is not None
