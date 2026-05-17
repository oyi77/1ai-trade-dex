import numpy as np
from scipy.optimize import minimize
from dataclasses import dataclass
from typing import List, Dict, Optional

@dataclass
class Goal:
    goal_id: str
    expected_return: float
    risk_score: float
    time_horizon: str
    bankroll_allocation_requested: float

class MultiObjectiveOptimizer:
    def __init__(self, daily_bankroll_cap: float = 1.0,
                 domain_diversification_limit: float = 0.3,
                 objective_weights: Optional[dict] = None):
        self.daily_bankroll_cap = daily_bankroll_cap
        self.domain_diversification_limit = domain_diversification_limit
        self.objective_weights = objective_weights or {
            'return': 0.4, 'risk': -0.3, 'time_horizon_penalty': -0.2, 'diversity_bonus': 0.1}

    def optimize_allocation(self, goals: List[Goal]) -> Dict[str, float]:
        if not goals:
            return {}
        try:
            result = self._optimize(goals)
            if result.success:
                return self._process_optimization_result(result, goals)
            return self._fallback_allocation(goals, self.daily_bankroll_cap, self.domain_diversification_limit)
        except Exception:
            return self._fallback_allocation(goals, self.daily_bankroll_cap, self.domain_diversification_limit)

    def _optimize(self, goals: List[Goal]):
        n_goals = len(goals)
        initial_guess = np.ones(n_goals) * min(self.daily_bankroll_cap / max(1, n_goals), self.domain_diversification_limit)
        bounds = [(0, self.domain_diversification_limit) for _ in range(n_goals)]
        constraints = [{'type': 'ineq', 'fun': lambda x: self.daily_bankroll_cap - np.sum(x)}]
        return minimize(fun=self._objective_function, x0=initial_guess, args=(goals,), bounds=bounds,
                       constraints=constraints, method='SLSQP', options={'maxiter': 1000, 'ftol': 1e-9})

    def _objective_function(self, x, goals: List[Goal]) -> float:
        allocations = np.array(x)
        total_utility = 0
        for i, goal in enumerate(goals):
            goal_utility = self.objective_weights['return'] * goal.expected_return
            goal_utility += self.objective_weights['risk'] * goal.risk_score
            goal_utility += self.objective_weights['time_horizon_penalty'] * self._time_horizon_penalty(goal.time_horizon)
            total_utility += allocations[i] * goal_utility
        return -total_utility

    def _time_horizon_penalty(self, time_horizon: str) -> float:
        return {'short_term': 0.1, 'medium_term': 0.3, 'long_term': 0.6}.get(time_horizon, 0.3)

    def _process_optimization_result(self, result, goals: List[Goal]) -> Dict[str, float]:
        return {goal.goal_id: float(result.x[i]) for i, goal in enumerate(goals)}

    def _fallback_allocation(self, goals: List[Goal], daily_cap: float, domain_limit: float) -> Dict[str, float]:
        if not goals:
            return {}
        n_goals = len(goals)
        allocation_per_goal = min(domain_limit, daily_cap / n_goals)
        return {g.goal_id: allocation_per_goal for g in goals}

    def get_health_metrics(self, allocations: Dict[str, float], goals: List[Goal]) -> Dict[str, float]:
        return {'allocation_efficiency': 0.5, 'risk_concentration': 0.5, 'time_diversification': 0.5}
