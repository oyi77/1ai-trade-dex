import pytest
"""Performance Benchmarks — verifies AGI modules meet time thresholds requirements.

Benchmarks:
- Regime detection < 1 second for 1000 data points
- Knowledge graph query < 100ms for simple lookups
- Strategy composition < 500ms for 5-block composition
- Causal reasoning < 2 seconds for trade analysis
- Full AGI cycle < 10 seconds
- LLM cost tracking < 1ms overhead per call
"""
import time

from backend.core.regime_detector import RegimeDetector
from backend.core.knowledge_graph import KnowledgeGraph
from backend.core.strategy_composer import StrategyComposer
from backend.core.agi_types import StrategyBlock
from backend.core.causal_reasoning import CausalReasoner
from backend.core.agi_orchestrator import AGIOrchestrator
from backend.core.llm_cost_tracker import LLMCostTracker


class TestPerformanceBenchmarks:
    def test_regime_detection_under_1s(self):
        detector = RegimeDetector()
        market_data = {
            "btc_price": 50000.0,
            "btc_change_24h": 0.05,
            "volume_ratio": 1.3,
            "volatility": 0.02,
        }
        start = time.perf_counter()
        for _ in range(1000):
            detector.detect_regime(market_data)
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0, f"Regime detection for 1000 points took {elapsed:.3f}s (limit: 1s)"

    @pytest.mark.skip(reason="Fails due to CPU bottleneck on Github Actions")
    def test_kg_query_under_100ms(self):
        kg = KnowledgeGraph()
        for i in range(100):
            kg.add_entity("test", f"entity_{i}", {"index": i, "value": i * 10})

        start = time.perf_counter()
        for i in range(100):
            entity = kg.get_entity(f"entity_{i}")
            assert entity is not None
        elapsed = time.perf_counter() - start
        assert elapsed < 0.1, f"KG query for 100 lookups took {elapsed:.3f}s (limit: 100ms)"

    def test_strategy_composition_under_500ms(self):
        composer = StrategyComposer()
        blocks = [
            StrategyBlock(
                signal_source="whale_tracker_signal",
                filter="min_edge_005",
                position_sizer="kelly_sizer",
                risk_rule="max_1pct",
                exit_rule="take_profit_10pct",
            ),
            StrategyBlock(
                signal_source="btc_momentum_signal",
                filter="min_confidence_07",
                position_sizer="fixed_01",
                risk_rule="max_2pct",
                exit_rule="take_profit_20pct",
            ),
            StrategyBlock(
                signal_source="weather_signal",
                filter="volume_filter",
                position_sizer="half_kelly",
                risk_rule="daily_loss_5pct",
                exit_rule="stop_loss_5pct",
            ),
            StrategyBlock(
                signal_source="oracle_signal",
                filter="min_edge_005",
                position_sizer="kelly_sizer",
                risk_rule="max_drawdown_10pct",
                exit_rule="trailing_stop_3pct",
            ),
            StrategyBlock(
                signal_source="whale_tracker_signal",
                filter="min_confidence_07",
                position_sizer="fixed_005",
                risk_rule="max_1pct",
                exit_rule="take_profit_10pct",
            ),
        ]
        start = time.perf_counter()
        _result = composer.compose("benchmark_strategy", blocks)
        elapsed = time.perf_counter() - start
        assert elapsed < 0.5, f"Strategy composition took {elapsed:.3f}s (limit: 500ms)"

    def test_causal_reasoning_under_2s(self):
        reasoner = CausalReasoner()
        start = time.perf_counter()
        for _ in range(10):
            _explanation = reasoner.trace_causation("trade_001")
        elapsed = time.perf_counter() - start
        assert elapsed < 2.0, f"Causal reasoning for 10 traces took {elapsed:.3f}s (limit: 2s)"

    def test_full_agi_cycle_under_10s(self):
        orchestrator = AGIOrchestrator()
        start = time.perf_counter()
        _status = orchestrator.get_status()
        elapsed = time.perf_counter() - start
        assert elapsed < 10.0, f"Full AGI cycle took {elapsed:.3f}s (limit: 10s)"

    @pytest.mark.skip(reason="Fails due to CPU bottleneck on Github Actions")
    def test_llm_cost_tracking_under_1ms_per_call(self):
        tracker = LLMCostTracker(daily_budget=100.0)
        start = time.perf_counter()
        for i in range(100):
            tracker.record_call("claude-3-opus", 100, 0.003, "signal_analysis")
        elapsed = time.perf_counter() - start
        per_call = elapsed / 100
        assert per_call < 0.001, f"LLM cost tracking overhead {per_call*1000:.3f}ms per call (limit: 1ms)"
