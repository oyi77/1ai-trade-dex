from backend.agi.long_term_planner import LongTermPlanner, LongTermPlan

def test_long_term_planner_produces_90_day_rolling_plan():
    planner = LongTermPlanner()
    goals = [{"goal_id": "test_goal_1", "start_week": 1, "duration_weeks": 4, "resource_needs": {"gpu_hours": 50, "llm_calls": 200}}]
    plan = planner.plan_horizon(goals)
    assert isinstance(plan, LongTermPlan)
    assert plan.horizon_days == 90
    assert plan.milestones
    assert plan.milestones[0].goal_id == "test_goal_1"

def test_long_term_planner_detects_and_resolves_resource_conflicts():
    planner = LongTermPlanner(gpu_monthly_budget=180, llm_monthly_budget=1000)
    goals = [{"goal_id": f"goal_{i}", "start_week": 1, "duration_weeks": 4, "resource_needs": {"gpu_hours": 30}} for i in range(2)]
    plan = planner.plan_horizon(goals)
    assert plan.conflicts
    conflict = plan.conflicts[0]
    resolution_result = planner.resolve_conflict(conflict, reschedule_to_week=2)
    assert resolution_result
    updated_milestones = planner.get_milestones_for_week(2)
    assert updated_milestones

def test_long_term_planner_milestones_visible_in_botstate():
    planner = LongTermPlanner()
    goals = [{"goal_id": "botstate_test", "start_week": 1, "duration_weeks": 2, "resource_needs": {"gpu_hours": 20}}]
    plan = planner.plan_horizon(goals)
    botstate_data = planner.to_botstate_dict()
    assert botstate_data
    new_planner = LongTermPlanner()
    load_result = new_planner.from_botstate_dict(botstate_data)
    assert load_result
    loaded_milestones = new_planner.get_milestones_for_week(1)
    assert loaded_milestones
    assert loaded_milestones[0].goal_id == "botstate_test"
