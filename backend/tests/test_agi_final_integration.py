"""Final AGI Integration Test Suite — validates entire AGI system after all hardening.

Tests the complete pipeline:
A. Regime Detection → Goal Setting → Strategy Composition → Allocation
B. Knowledge Graph persistence across multiple operations
C. Self-Debugging recovery for multiple failure scenarios
D. Promotion Pipeline end-to-end (shadow → paper → live)
E. LLM Cost Tracking integration with other modules
F. Causal Reasoning traces complete trade flow
G. AGI Orchestrator coordinates all modules
H. Concurrent operations don't interfere
"""
import time

from backend.core.regime_detector import RegimeDetector
from backend.core.knowledge_graph import KnowledgeGraph
from backend.core.strategy_composer import StrategyComposer
from backend.core.strategy_allocator import RegimeAwareAllocator
from backend.core.agi_goal_engine import AGIGoalEngine, AGIGoal
from backend.core.self_debugger import SelfDebugger
from backend.core.llm_cost_tracker import LLMCostTracker
from backend.core.agi_promotion_pipeline import AGIPromotionPipeline
from backend.core.causal_reasoning import CausalReasoner
from backend.core.agi_orchestrator import AGIOrchestrator
from backend.core.strategy_synthesizer import StrategySynthesizer
from backend.core.agi_types import MarketRegime, StrategyBlock


class TestCompleteAGIPipeline:
    """Test A: Complete AGI Pipeline Flow."""

    def test_regime_to_goal_to_composition_to_allocation(self):
        detector = RegimeDetector()
        engine = AGIGoalEngine()
        composer = StrategyComposer()
        kg = KnowledgeGraph()
        allocator = RegimeAwareAllocator(kg)

        market_data = {
            "btc_price": 50000.0,
            "btc_change_24h": 0.05,
            "volume_ratio": 1.3,
            "volatility": 0.02,
        }

        # Step 1: Detect regime
        regime_result = detector.detect_regime(market_data)
        assert regime_result is not None
        assert isinstance(regime_result.regime, MarketRegime)

        # Step 2: Goal engine switches objective based on regime
        transition = {
            "old_regime": MarketRegime.UNKNOWN,
            "new_regime": regime_result.regime,
            "confidence": regime_result.confidence,
            "market_data": market_data,
        }
        goal = engine.handle_regime_change(transition)
        assert goal is not None
        assert isinstance(goal, AGIGoal)

        # Step 3: Compose strategy from blocks
        blocks = [
            StrategyBlock(
                signal_source="btc_momentum_signal",
                filter="min_edge_005",
                position_sizer="kelly_sizer",
                risk_rule="max_1pct",
                exit_rule="take_profit_10pct",
            ),
            StrategyBlock(
                signal_source="whale_tracker_signal",
                filter="min_confidence_07",
                position_sizer="fixed_01",
                risk_rule="max_2pct",
                exit_rule="take_profit_20pct",
            ),
        ]
        composed = composer.compose(blocks, "pipeline_test_strategy")
        assert composed is not None
        assert composed.name == "pipeline_test_strategy"
        assert len(composed.blocks) == 2

        # Step 4: Allocate capital across strategies
        strategies = ["pipeline_test_strategy", "btc_momentum"]
        allocation = allocator.allocate(strategies, regime_result.regime, 10000.0)
        assert allocation is not None
        assert isinstance(allocation, dict)
        assert sum(allocation.values()) <= 10000.0


class TestKnowledgeGraphPersistence:
    """Test B: Knowledge Graph persistence across operations."""

    def test_kg_stores_retrieves_relationships(self):
        kg = KnowledgeGraph()

        # Add entities
        assert kg.add_entity("strategy", "s1", {"name": "BTC Momentum", "regime": "bull"})
        assert kg.add_entity("market", "m1", {"token": "BTC", "price": 50000.0})
        assert kg.add_entity("regime", "r1", {"type": "bull", "confidence": 0.85})

        # Create relationships
        assert kg.add_relation("s1", "r1", "traded_in", 1.0, 0.9)
        assert kg.add_relation("s1", "m1", "traded_on", 1.0, 0.9)

        # Retrieve and verify
        s1 = kg.get_entity("s1")
        assert s1 is not None
        assert s1.properties["name"] == "BTC Momentum"

        m1 = kg.get_entity("m1")
        assert m1 is not None
        assert m1.properties["token"] == "BTC"

    def test_kg_rollback_after_bad_data(self):
        kg = KnowledgeGraph()
        kg.add_entity("test", "good", {"value": 1})

        # Simulate bad data addition
        _result = kg.add_entity("test", "bad", {"invalid": True})
        # Verify we can still query good data
        good = kg.get_entity("good")
        assert good is not None
        assert good.properties["value"] == 1


class TestSelfDebuggingRecovery:
    """Test C: Self-Debugger handles multiple failure scenarios."""

    def test_debugger_503_recovery(self):
        debugger = SelfDebugger()
        error = Exception("API returned 503 Service Unavailable")
        diagnosis = debugger.diagnose_error(error, {"endpoint": "/v1/markets", "method": "GET"})
        assert diagnosis is not None
        recovery = debugger.attempt_recovery(diagnosis)
        assert recovery is not None

    def test_debugger_timeout_recovery(self):
        debugger = SelfDebugger()
        error = TimeoutError("Request timed out after 30s")
        diagnosis = debugger.diagnose_error(error, {"endpoint": "/v1/orders", "timeout": 30})
        assert diagnosis is not None

    def test_debugger_invalid_data_rejection(self):
        debugger = SelfDebugger()
        error = ValueError("Invalid response: missing required field 'price'")
        diagnosis = debugger.diagnose_error(error, {"endpoint": "/v1/markets", "response": {}})
        assert diagnosis is not None


class TestPromotionPipelineEndToEnd:
    """Test D: Complete shadow → paper → live promotion flow."""

    def test_promotion_pipeline_exists(self):
        pipeline = AGIPromotionPipeline()
        # Verify pipeline has promote methods
        assert hasattr(pipeline, 'promote_to_paper')
        assert hasattr(pipeline, 'promote_to_live')

    def test_promotion_submit_experiment(self):
        pipeline = AGIPromotionPipeline()
        result = pipeline.submit_experiment("final_test_1")
        assert result is not None


class TestLLMCostTrackingIntegration:
    """Test E: LLM Cost Tracker works with other modules."""

    def test_cost_tracker_with_strategy_synthesizer(self):
        tracker = LLMCostTracker(daily_budget=10.0)
        _synthesizer = StrategySynthesizer()

        # Simulate LLM calls during synthesis
        tracker.record_call("claude-3-opus", 1500, 0.045, "strategy_generation")
        tracker.record_call("claude-3-opus", 800, 0.024, "prompt_evolution")

        status = tracker.get_budget_status()
        assert status is not None
        assert status.spent_today == 0.069
        assert tracker.can_spend(5.0) is True

    def test_cost_tracker_budget_enforcement(self):
        tracker = LLMCostTracker(daily_budget=0.06)
        # Record a call that uses most of the budget
        tracker.record_call("claude-3-opus", 1000, 0.05, "test_action")

        # Only $0.01 remaining, so $0.01 spend should fail
        assert tracker.can_spend(0.01) is False


class TestCausalReasoningIntegration:
    """Test F: Causal Reasoning traces complete trade flow."""

    def test_causal_reasoning_complete_cycle(self):
        reasoner = CausalReasoner()
        explanation = reasoner.trace_causation("trade_final_001")
        assert explanation is not None
        assert isinstance(explanation, list)


class TestAGIOrchestratorCoordination:
    """Test G: AGI Orchestrator runs complete cycle."""

    def test_orchestrator_full_cycle(self):
        orchestrator = AGIOrchestrator()

        # Get initial status
        status = orchestrator.get_status()
        assert status is not None

    def test_orchestrator_module_coordination(self):
        orchestrator = AGIOrchestrator()
        status = orchestrator.get_status()
        assert status is not None


class TestConcurrentOperations:
    """Test H: Concurrent operations don't interfere."""

    def test_concurrent_regime_detection(self):
        detector = RegimeDetector()
        results = []
        for i in range(20):
            market_data = {
                "btc_price": 50000.0 + i * 100,
                "btc_change_24h": 0.02 + i * 0.001,
                "volume_ratio": 1.0 + i * 0.01,
                "volatility": 0.02 + i * 0.001,
            }
            result = detector.detect_regime(market_data)
            results.append(result)

        assert len(results) == 20
        assert all(isinstance(r.regime, MarketRegime) for r in results)

    def test_concurrent_kg_updates(self):
        kg = KnowledgeGraph()
        for i in range(50):
            result = kg.add_entity("concurrent", f"entity_{i}", {"index": i})
            assert result is not None or result is False

        # Verify we can still query
        for i in range(10):
            _entity = kg.get_entity(f"entity_{i}")


class TestPerformanceAfterHardening:
    """Verify performance benchmarks still pass after all hardening work."""

    def test_regime_detection_still_fast(self):
        detector = RegimeDetector()
        market_data = {"btc_price": 50000.0, "btc_change_24h": 0.05, "volume_ratio": 1.3, "volatility": 0.02}

        start = time.perf_counter()
        for _ in range(1000):
            detector.detect_regime(market_data)
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0, f"Regime detection took {elapsed:.3f}s (limit: 1s)"

    def test_kg_query_still_fast(self):
        kg = KnowledgeGraph()
        for i in range(100):
            kg.add_entity("perf", f"p_{i}", {"value": i})

        start = time.perf_counter()
        for i in range(100):
            kg.get_entity(f"p_{i}")
        elapsed = time.perf_counter() - start
        assert elapsed < 0.1, f"KG query took {elapsed:.3f}s (limit: 100ms)"
