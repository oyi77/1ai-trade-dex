from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
from collections import defaultdict

@dataclass
class Milestone:
    milestone_id: str
    goal_id: str
    week: int
    resource_requirements: Dict[str, float]
    status: str = "pending"
    completed_at: Optional[datetime] = None

@dataclass
class ResourceConflict:
    conflict_id: str
    week: int
    resource_type: str
    requested: float
    budget: float
    goals_involved: List[str]

@dataclass
class LongTermPlan:
    plan_id: str
    created_at: datetime
    horizon_days: int = 90
    milestones: List[Milestone] = field(default_factory=list)
    conflicts: List[ResourceConflict] = field(default_factory=list)
    gpu_monthly_budget: float = 180.0
    llm_monthly_budget: float = 10000.0
    bankroll_reserve: float = 0.0

class LongTermPlanner:
    def __init__(
        self,
        horizon_days: int = 90,
        gpu_monthly_budget: float = 180.0,
        llm_monthly_budget: float = 10000.0,
    ):
        self.horizon_days = horizon_days
        self.gpu_monthly_budget = gpu_monthly_budget
        self.llm_monthly_budget = llm_monthly_budget
        self._current_plan: Optional[LongTermPlan] = None
        self._goals: List[dict] = []

    def plan_horizon(self, goals: List[dict]) -> LongTermPlan:
        self._goals = goals
        plan_id = f"plan_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        plan = LongTermPlan(plan_id=plan_id, created_at=datetime.now())
        milestones = []
        conflicts = []
        weekly_allocations: Dict[int, Dict[str, float]] = defaultdict(
            lambda: defaultdict(float)
        )
        for goal in goals:
            goal_id = goal.get("goal_id", f"goal_{len(milestones)}")
            resource_needs = goal.get("resource_needs", {})
            start_week = goal.get("start_week", 1)
            duration_weeks = goal.get("duration_weeks", 4)
            for w in range(start_week, start_week + duration_weeks):
                if w > self.horizon_days // 7:
                    continue
                for resource_type, amount in resource_needs.items():
                    weekly_allocations[w][resource_type] += amount
        for week, resources in sorted(weekly_allocations.items()):
            for resource_type, total_requested in resources.items():
                if resource_type == "gpu_hours":
                    monthly_budget = self.gpu_monthly_budget / 4
                elif resource_type == "llm_calls":
                    monthly_budget = self.llm_monthly_budget / 4
                else:
                    monthly_budget = float("inf")
                if total_requested > monthly_budget:
                    conflict = ResourceConflict(
                        conflict_id=f"conflict_{week}_{resource_type}",
                        week=week,
                        resource_type=resource_type,
                        requested=total_requested,
                        budget=monthly_budget,
                        goals_involved=[
                            g["goal_id"]
                            for g in goals
                            if week >= g.get("start_week", 1)
                            and week < g.get("start_week", 1) + g.get("duration_weeks", 4)
                            and resource_type in g.get("resource_needs", {})
                        ],
                    )
                    conflicts.append(conflict)
        for goal in goals:
            goal_id = goal.get("goal_id", f"goal_{len(milestones)}")
            start_week = goal.get("start_week", 1)
            resource_needs = goal.get("resource_needs", {})
            ms = Milestone(
                milestone_id=f"ms_{goal_id}_w{start_week}",
                goal_id=goal_id,
                week=start_week,
                resource_requirements=resource_needs,
            )
            milestones.append(ms)
        plan.milestones = milestones
        plan.conflicts = conflicts
        self._current_plan = plan
        return plan

    def resolve_conflict(
        self, conflict: ResourceConflict, reschedule_to_week: Optional[int] = None
    ) -> bool:
        if self._current_plan is None:
            return False
        if reschedule_to_week is None:
            reschedule_to_week = conflict.week + 1
        for milestone in self._current_plan.milestones:
            if milestone.goal_id in conflict.goals_involved:
                milestone.week = reschedule_to_week
        return True

    def to_botstate_dict(self) -> dict:
        if self._current_plan is None:
            return {}
        return {
            "plan_id": self._current_plan.plan_id,
            "created_at": self._current_plan.created_at.isoformat(),
            "horizon_days": self._current_plan.horizon_days,
            "milestones": [
                {
                    "milestone_id": m.milestone_id,
                    "goal_id": m.goal_id,
                    "week": m.week,
                    "resource_requirements": m.resource_requirements,
                    "status": m.status,
                    "completed_at": m.completed_at.isoformat()
                    if m.completed_at
                    else None,
                }
                for m in self._current_plan.milestones
            ],
            "conflicts": [
                {
                    "conflict_id": c.conflict_id,
                    "week": c.week,
                    "resource_type": c.resource_type,
                    "requested": c.requested,
                    "budget": c.budget,
                    "goals_involved": c.goals_involved,
                }
                for c in self._current_plan.conflicts
            ],
        }

    def from_botstate_dict(self, data: dict) -> bool:
        if not data or "plan_id" not in data:
            return False
        plan = LongTermPlan(
            plan_id=data["plan_id"],
            created_at=datetime.fromisoformat(data["created_at"]),
            horizon_days=data.get("horizon_days", 90),
        )
        plan.milestones = [
            Milestone(
                milestone_id=m["milestone_id"],
                goal_id=m["goal_id"],
                week=m["week"],
                resource_requirements=m["resource_requirements"],
                status=m.get("status", "pending"),
                completed_at=datetime.fromisoformat(m["completed_at"])
                if m.get("completed_at")
                else None,
            )
            for m in data.get("milestones", [])
        ]
        plan.conflicts = [
            ResourceConflict(
                conflict_id=c["conflict_id"],
                week=c["week"],
                resource_type=c["resource_type"],
                requested=c["requested"],
                budget=c["budget"],
                goals_involved=c["goals_involved"],
            )
            for c in data.get("conflicts", [])
        ]
        self._current_plan = plan
        return True

    def get_milestones_for_week(self, week: int) -> List[Milestone]:
        if self._current_plan is None:
            return []
        return [m for m in self._current_plan.milestones if m.week == week]

    def mark_milestone_complete(self, milestone_id: str) -> bool:
        if self._current_plan is None:
            return False
        for milestone in self._current_plan.milestones:
            if milestone.milestone_id == milestone_id:
                milestone.status = "completed"
                milestone.completed_at = datetime.now()
                return True
        return False
