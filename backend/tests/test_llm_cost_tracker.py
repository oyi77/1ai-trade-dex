"""Tests for LLM Cost Tracker — budget enforcement, cost tracking, daily reset."""
import pytest
from unittest.mock import patch

from backend.core.llm_cost_tracker import (
    LLMCostTracker,
    BudgetExceededError,
    COST_LIMITS,
)


class TestLLMCostTracker:
    def test_record_call_tracks_spending(self):
        tracker = LLMCostTracker(daily_budget=10.0)
        tracker.record_call("claude-3-opus", 1500, 0.045, "strategy_generation")
        status = tracker.get_budget_status()
        assert status.spent_today == pytest.approx(0.045)
        assert status.call_count == 1

    def test_can_spend_within_budget(self):
        tracker = LLMCostTracker(daily_budget=10.0)
        assert tracker.can_spend(5.0) is True
        assert tracker.can_spend(10.0) is True
        assert tracker.can_spend(10.01) is False

    def test_can_spend_exceeds_budget(self):
        tracker = LLMCostTracker(daily_budget=1.0)
        for i in range(10):
            tracker.record_call("claude-3-opus", 100, 0.10, "signal_analysis")
        assert tracker.can_spend(0.20) is False

    def test_budget_exceeded_raises_error(self):
        tracker = LLMCostTracker(daily_budget=1.0)
        for i in range(10):
            tracker.record_call("claude-3-opus", 100, 0.10, "signal_analysis")
        with pytest.raises(BudgetExceededError):
            tracker.record_call("claude-3-opus", 100, 0.20, "signal_analysis")

    def test_get_budget_status(self):
        tracker = LLMCostTracker(daily_budget=10.0)
        tracker.record_call("claude-3-opus", 1500, 0.045, "strategy_generation")
        status = tracker.get_budget_status()
        assert status.daily_budget == 10.0
        assert status.spent_today == pytest.approx(0.045)
        assert status.remaining == pytest.approx(9.955)
        assert status.call_count == 1
        assert status.can_spend is True

    def test_get_cost_by_purpose(self):
        tracker = LLMCostTracker(daily_budget=10.0)
        tracker.record_call("claude-3-opus", 1500, 0.045, "strategy_generation")
        tracker.record_call("groq-llama", 500, 0.005, "signal_analysis")
        tracker.record_call("claude-3-opus", 2000, 0.06, "strategy_generation")
        strategy_cost = tracker.get_cost_by_purpose("strategy_generation")
        assert strategy_cost == pytest.approx(0.105)

    def test_daily_reset_clears_spending(self):
        tracker = LLMCostTracker(daily_budget=10.0)
        tracker.record_call("claude-3-opus", 1500, 0.045, "strategy_generation")
        assert tracker.get_budget_status().spent_today > 0
        tracker.reset_daily_budget()
        status = tracker.get_budget_status()
        assert status.spent_today == 0.0
        assert status.remaining == 10.0

    def test_per_action_limits_exist(self):
        assert "strategy_generation" in COST_LIMITS
        assert COST_LIMITS["strategy_generation"] == 0.50
        assert COST_LIMITS["prompt_evolution"] == 0.10
        assert COST_LIMITS["causal_analysis"] == 0.05

    def test_zero_cost_always_allowed(self):
        tracker = LLMCostTracker(daily_budget=0.01)
        assert tracker.can_spend(0) is True

    def test_negative_cost_always_allowed(self):
        tracker = LLMCostTracker(daily_budget=0.01)
        assert tracker.can_spend(-1.0) is True

    def test_multiple_calls_accumulate(self):
        tracker = LLMCostTracker(daily_budget=10.0)
        for i in range(5):
            tracker.record_call("claude-3-opus", 1000, 0.03, "signal_analysis")
        status = tracker.get_budget_status()
        assert status.spent_today == pytest.approx(0.15)
        assert status.call_count == 5

    def test_env_var_daily_budget(self):
        import os
        original = os.environ.get("LLM_DAILY_BUDGET")
        os.environ["LLM_DAILY_BUDGET"] = "5.0"
        tracker = LLMCostTracker()
        assert tracker.daily_budget == 5.0
        if original is not None:
            os.environ["LLM_DAILY_BUDGET"] = original
        else:
            del os.environ["LLM_DAILY_BUDGET"]

    def test_budget_remaining_in_record(self):
        tracker = LLMCostTracker(daily_budget=10.0)
        tracker.record_call("claude-3-opus", 1500, 0.045, "strategy_generation")
        assert tracker.calls[0].budget_remaining == pytest.approx(9.955)

    def test_alert_at_80_percent_budget(self):
        """Verify warning log fires when 80% budget threshold is crossed."""
        tracker = LLMCostTracker(daily_budget=10.0)
        # Spend up to just below 80% ($7.90)
        tracker.record_call("claude-3-opus", 1000, 7.90, "signal_analysis")
        # This call crosses 80% ($8.00+) — should trigger alert
        with patch("backend.core.llm_cost_tracker.logger") as mock_logger:
            tracker.record_call("claude-3-opus", 1000, 0.20, "signal_analysis")
            mock_logger.warning.assert_called()
            warning_msg = mock_logger.warning.call_args[0][0]
            assert "80%" in warning_msg

    def test_no_alert_below_80_percent(self):
        """Verify no alert when below 80% threshold."""
        tracker = LLMCostTracker(daily_budget=10.0)
        with patch("backend.core.llm_cost_tracker.logger") as mock_logger:
            tracker.record_call("claude-3-opus", 1000, 5.00, "signal_analysis")
            mock_logger.warning.assert_not_called()

    def test_alert_fires_only_once_at_threshold(self):
        """Verify alert fires only when crossing 80%, not on every call after."""
        tracker = LLMCostTracker(daily_budget=10.0)
        tracker.record_call("claude-3-opus", 1000, 7.90, "signal_analysis")
        # First call crossing 80% — should alert
        with patch("backend.core.llm_cost_tracker.logger") as mock_logger:
            tracker.record_call("claude-3-opus", 1000, 0.20, "signal_analysis")
            assert mock_logger.warning.call_count == 1
        # Second call above 80% — should NOT alert again
        with patch("backend.core.llm_cost_tracker.logger") as mock_logger:
            tracker.record_call("claude-3-opus", 1000, 0.50, "signal_analysis")
            mock_logger.warning.assert_not_called()
