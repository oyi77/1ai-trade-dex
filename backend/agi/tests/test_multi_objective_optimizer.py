from backend.agi.multi_objective_optimizer import MultiObjectiveOptimizer, Goal

class TestMultiObjectiveOptimizer:
    """Unit tests for MultiObjectiveOptimizer (Task 28 of agi-evolution.md)"""

    def test_respects_total_cap(self):
        """Test that optimizer respects daily bankroll cap."""
        optimizer = MultiObjectiveOptimizer(daily_bankroll_cap=0.8)
        goals = [
            Goal(goal_id="g1", expected_return=0.2, risk_score=0.1, time_horizon="medium_term", bankroll_allocation_requested=0.5),
            Goal(goal_id="g2", expected_return=0.15, risk_score=0.08, time_horizon="short_term", bankroll_allocation_requested=0.5),
        ]

        allocation = optimizer.optimize_allocation(goals)
        total = sum(allocation.values())

        assert total <= 0.8, f"Total allocation {total} exceeds cap 0.8"
        assert total > 0, "No allocation made"

    def test_enforces_domain_diversification(self):
        """Test that no single goal gets more than domain diversification limit."""
        optimizer = MultiObjectiveOptimizer(domain_diversification_limit=0.3)
        goals = [
            Goal(goal_id="g1", expected_return=0.25, risk_score=0.05, time_horizon="long_term", bankroll_allocation_requested=0.5),
            Goal(goal_id="g2", expected_return=0.15, risk_score=0.1, time_horizon="medium_term", bankroll_allocation_requested=0.5),
        ]

        allocation = optimizer.optimize_allocation(goals)

        for goal_id, allocated in allocation.items():
            assert allocated <= 0.3, f"Goal {goal_id} allocated {allocated} > 0.3 limit"

    def test_balances_time_horizons(self):
        """Test that optimizer balances between short-term and long-term goals."""
        optimizer = MultiObjectiveOptimizer(daily_bankroll_cap=1.0)
        goals = [
            Goal(goal_id="short", expected_return=0.2, risk_score=0.1, time_horizon="short_term", bankroll_allocation_requested=0.5),
            Goal(goal_id="long", expected_return=0.18, risk_score=0.08, time_horizon="long_term", bankroll_allocation_requested=0.5),
        ]

        allocation = optimizer.optimize_allocation(goals)

        # Both goals should get some allocation
        assert allocation["short"] > 0, "Short-term goal got no allocation"
        assert allocation["long"] > 0, "Long-term goal got no allocation"

        # Long-term should get less due to time horizon penalty
        assert allocation["long"] < allocation["short"], \
            "Long-term should have less allocation due to time horizon penalty"

    def test_domain_diversification_limit_scenario(self):
        """Test QA scenario: diversification prevents single-domain overallocation."""
        optimizer = MultiObjectiveOptimizer(daily_bankroll_cap=1.0, domain_diversification_limit=0.3)
        goals = [
            Goal(goal_id="domain_a", expected_return=0.2, risk_score=0.15, time_horizon="medium_term", bankroll_allocation_requested=0.4),
            Goal(goal_id="domain_b", expected_return=0.18, risk_score=0.12, time_horizon="medium_term", bankroll_allocation_requested=0.4),
            Goal(goal_id="domain_c", expected_return=0.15, risk_score=0.1, time_horizon="short_term", bankroll_allocation_requested=0.2),
            Goal(goal_id="domain_d", expected_return=0.12, risk_score=0.08, time_horizon="long_term", bankroll_allocation_requested=0.1),
        ]

        allocation = optimizer.optimize_allocation(goals)
        total = sum(allocation.values())

        # Check diversification limit
        for goal_id, allocated in allocation.items():
            assert allocated <= 0.3, f"Goal {goal_id} allocated {allocated} > 0.3 limit"

        # Check total cap
        assert total <= 1.0, f"Total allocation {total} exceeds 1.0 cap"

        # Domain A should be reduced from its requested 40% to <= 30%
        assert allocation["domain_a"] <= 0.3, "Domain A exceeds diversification limit"

        # Domain B should also be reduced from its requested 40% to <= 30%
        assert allocation["domain_b"] <= 0.3, "Domain B exceeds diversification limit"

    def test_empty_goals_returns_empty_dict(self):
        """Test that empty goal list returns empty allocation dict."""
        optimizer = MultiObjectiveOptimizer()
        allocation = optimizer.optimize_allocation([])
        assert allocation == {}, "Empty goals should return empty dict"

    def test_health_metrics(self):
        """Test that health metrics are returned correctly."""
        optimizer = MultiObjectiveOptimizer()
        goals = [
            Goal(goal_id="g1", expected_return=0.2, risk_score=0.1, time_horizon="short_term", bankroll_allocation_requested=0.5),
            Goal(goal_id="g2", expected_return=0.15, risk_score=0.08, time_horizon="long_term", bankroll_allocation_requested=0.5),
        ]
        allocation = optimizer.optimize_allocation(goals)
        metrics = optimizer.get_health_metrics(allocation, goals)

        assert 'allocation_efficiency' in metrics
        assert 'risk_concentration' in metrics
        assert 'time_diversification' in metrics
