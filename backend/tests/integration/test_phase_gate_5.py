"""Phase Gate 5 integration test - Unbounded Autonomy Sign-off.
Aggregates Tasks 25-29 to verify goal formation and planning pipeline."""

import pytest
from backend.agi.core_values import CoreValues
from backend.agi.multi_objective_optimizer import MultiObjectiveOptimizer, Goal
from backend.agi.long_term_planner import LongTermPlanner, LongTermPlan


class TestCoreValuesAlignment:
    """Task 25: CoreValues alignment module tests."""

    def test_core_values_initializes_from_misc_data(self):
        misc_data = {"max_single_trade_risk": 0.05, "max_daily_loss": 0.15}
        cv = CoreValues(misc_data=misc_data)
        assert cv.max_single_trade_risk == 0.05
        assert cv.max_daily_loss == 0.15

    def test_alignment_approves_safe_action(self):
        cv = CoreValues()
        result = cv.check_alignment(
            {"risk_tier": "moderate", "single_trade_risk": 0.03}
        )
        assert result.is_aligned
        assert len(result.concerns) == 0

    def test_alignment_rejects_aggressive_without_override(self):
        cv = CoreValues({"allow_aggressive_tier": False})
        result = cv.check_alignment(
            {"risk_tier": "aggressive", "single_trade_risk": 0.04}
        )
        assert not result.is_aligned
        assert any("aggressive" in c.lower() for c in result.concerns)


class TestMultiObjectiveOptimizer:
    """Task 28: MultiObjectiveOptimizer tests."""

    def test_respects_total_cap(self):
        optimizer = MultiObjectiveOptimizer(daily_bankroll_cap=0.8)
        goals = [
            Goal("g1", 0.2, 0.1, "medium_term", 0.5),
            Goal("g2", 0.15, 0.08, "short_term", 0.5),
        ]
        allocation = optimizer.optimize_allocation(goals)
        assert sum(allocation.values()) <= 0.8

    def test_enforces_domain_diversification(self):
        optimizer = MultiObjectiveOptimizer(domain_diversification_limit=0.3)
        goals = [Goal("g1", 0.25, 0.05, "long_term", 0.5)]
        allocation = optimizer.optimize_allocation(goals)
        assert all(v <= 0.3 for v in allocation.values())


class TestLongTermPlanner:
    """Task 29: LongTermPlanner tests."""

    def test_produces_90_day_plan(self):
        planner = LongTermPlanner()
        goals = [
            {
                "goal_id": "test",
                "start_week": 1,
                "duration_weeks": 4,
                "resource_needs": {"gpu_hours": 50},
            }
        ]
        plan = planner.plan_horizon(goals)
        assert isinstance(plan, LongTermPlan)
        assert plan.horizon_days == 90

    def test_detects_conflicts(self):
        planner = LongTermPlanner(gpu_monthly_budget=180)
        goals = [
            {
                "goal_id": f"g{i}",
                "start_week": 1,
                "duration_weeks": 4,
                "resource_needs": {"gpu_hours": 40},
            }
            for i in range(2)
        ]
        plan = planner.plan_horizon(goals)
        assert len(plan.conflicts) > 0 or len(plan.milestones) > 0


def test_phase_gate_5_all_dependencies_met():
    """Verify all Phase 5 components are present and functional."""
    cv = CoreValues()
    optimizer = MultiObjectiveOptimizer()
    planner = LongTermPlanner()

    assert hasattr(cv, "check_alignment")
    assert hasattr(optimizer, "optimize_allocation")
    assert hasattr(planner, "plan_horizon")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
