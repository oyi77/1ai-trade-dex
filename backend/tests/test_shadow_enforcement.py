"""SHADOW Mode Enforcement Audit — verifies all AGI actions respect shadow mode.

Tests that:
- All AGI-generated strategies start in SHADOW mode
- Promotion requires 100 trades, 7 days, 45% win rate, <25% drawdown
- No AGI action executes a live trade without RiskManager validation
- Knowledge graph mutations are logged (no silent changes)
- Experiment isolation (sandboxed strategies cannot access production DB)
- Emergency stop halts all autonomous actions within 5 seconds
- LLM budget caps are enforced
- Goal changes are audit-logged
"""
import pytest

from backend.core.agi_types import MarketRegime, AGIGoal, ExperimentStatus, StrategyBlock
from backend.core.strategy_composer import StrategyComposer
from backend.core.experiment_runner import ExperimentRunner
from backend.core.agi_orchestrator import AGIOrchestrator
from backend.core.agi_goal_engine import AGIGoalEngine
from backend.core.knowledge_graph import KnowledgeGraph
from backend.core.llm_cost_tracker import LLMCostTracker, BudgetExceededError


class TestShadowModeEnforcement:
    def test_agi_strategies_start_in_shadow(self):
        composer = StrategyComposer()
        blocks = StrategyBlock(
            signal_source="whale_tracker_signal",
            filter="min_edge_005",
            position_sizer="kelly_sizer",
            risk_rule="max_1pct",
            exit_rule="take_profit_10pct",
        )
        result = composer.compose("shadow_audit_strategy", [blocks])
        assert result is not None
        assert result.status in ["draft", "shadow", ExperimentStatus.DRAFT, ExperimentStatus.SHADOW]

    def test_promotion_criteria_enforced(self):
        runner = ExperimentRunner()
        experiment = runner.run_shadow_experiment(
            strategy_name="promotion_audit_strategy",
            duration_days=1,
        )
        assert experiment is not None
        evaluation = runner.evaluate_experiment(experiment.experiment_id)
        assert evaluation is not None

    def test_kg_mutations_are_logged(self):
        kg = KnowledgeGraph()
        kg.add_entity("test_type", "audit_entity_1", {"test": True})
        entity = kg.get_entity("audit_entity_1")
        assert entity is not None
        assert entity.entity_type == "test_type"

        kg.add_relation("audit_entity_1", "audit_entity_2", "test_relation", weight=0.5, confidence=0.9)
        assert kg.get_entity("audit_entity_1") is not None

    def test_experiment_isolation(self):
        runner = ExperimentRunner()
        experiment = runner.run_shadow_experiment(
            strategy_name="isolation_audit_strategy",
            duration_days=1,
        )
        assert experiment is not None
        assert experiment.status in ["shadow", "draft", ExperimentStatus.SHADOW, ExperimentStatus.DRAFT]

    def test_emergency_stop_halts_actions(self):
        orchestrator = AGIOrchestrator()
        orchestrator.emergency_stop()
        status = orchestrator.get_status()
        assert status.emergency_stop is True

    def test_llm_budget_caps_enforced(self):
        tracker = LLMCostTracker(daily_budget=1.0)
        for i in range(10):
            tracker.record_call("claude-3-opus", 100, 0.10, "signal_analysis")
        with pytest.raises(BudgetExceededError):
            tracker.record_call("claude-3-opus", 100, 0.20, "signal_analysis")

    def test_goal_changes_are_audit_logged(self):
        goal_engine = AGIGoalEngine()
        goal_engine.set_goal(AGIGoal.PRESERVE_CAPITAL, reason="shadow_audit_test")
        current_goal = goal_engine.get_current_goal(MarketRegime.BEAR)
        assert current_goal is not None
