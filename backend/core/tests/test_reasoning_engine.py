from unittest.mock import patch

import pytest
from backend.core.reasoning_engine import (
    ReasoningContext,
    ReasoningResult,
    ReasoningEngine,
)


class TestReasoningContext:
    def test_reasoning_context_creation(self):
        ctx = ReasoningContext(
            domain="finance",
            query="What is the cause of inflation?",
            evidence=["price_index_up", "supply_chain_constraints"],
            constraints=["must_be_evidence_based"]
        )
        assert ctx.domain == "finance"
        assert ctx.query == "What is the cause of inflation?"
        assert ctx.evidence == ["price_index_up", "supply_chain_constraints"]
        assert ctx.constraints == ["must_be_evidence_based"]

    def test_reasoning_context_defaults(self):
        ctx = ReasoningContext(domain="physics", query="E=mc^2")
        assert ctx.evidence == []
        assert ctx.constraints == []

    def test_reasoning_context_immutable(self):
        ctx = ReasoningContext(domain="test", query="test")
        with pytest.raises(AttributeError):
            ctx.domain = "new_domain"


class TestReasoningResult:
    def test_reasoning_result_creation(self):
        res = ReasoningResult(
            conclusion="Inflation is caused by supply constraints",
            confidence=0.85,
            trace=["step1", "step2"],
            supporting_evidence=["evidence1"]
        )
        assert res.conclusion == "Inflation is caused by supply constraints"
        assert res.confidence == 0.85
        assert res.trace == ["step1", "step2"]
        assert res.supporting_evidence == ["evidence1"]

    def test_reasoning_result_defaults(self):
        res = ReasoningResult(conclusion="test", confidence=0.5)
        assert res.trace == []
        assert res.supporting_evidence == []

    def test_reasoning_result_immutable(self):
        res = ReasoningResult(conclusion="test", confidence=0.5)
        with pytest.raises(AttributeError):
            res.conclusion = "new_conclusion"


class TestReasoningEngine:
    def test_reasoning_engine_instantiation(self):
        engine = ReasoningEngine()
        assert engine is not None

    def test_basic_reasoning_flow(self):
        engine = ReasoningEngine()
        ctx = ReasoningContext(
            domain="finance",
            query="What causes market volatility?",
            evidence=["uncertainty", "policy_changes"]
        )
        result = engine.reason(ctx)

        assert isinstance(result, ReasoningResult)
        assert "Processed conclusion" in result.conclusion
        assert result.confidence == 0.85
        assert len(result.trace) == 3
        assert len(result.supporting_evidence) == 2

    def test_basic_reasoning_flow_no_evidence(self):
        engine = ReasoningEngine()
        ctx = ReasoningContext(domain="test", query="test query")
        result = engine.reason(ctx)

        assert result.confidence == 0.5
        assert len(result.supporting_evidence) == 0

    @patch("backend.core.reasoning_engine.logger")
    def test_chain_steps_success(self, mock_logger):
        engine = ReasoningEngine()

        def step1(x):
            return x + 1

        def step2(x):
            return x * 2

        result = engine.chain_steps([step1, step2], initial_input=5)

        assert isinstance(result, ReasoningResult)
        assert result.conclusion == "12"  # (5 + 1) * 2
        assert result.confidence == 1.0
        assert "Executing step1" in result.trace[0]
        assert "Result of step1" in result.trace[1]

    @patch("backend.core.reasoning_engine.logger")
    def test_chain_steps_failure(self, mock_logger):
        engine = ReasoningEngine()

        def step1(x):
            return x + 1

        def step2(x):
            raise ValueError("Intentional error")

        result = engine.chain_steps([step1, step2], initial_input=5)

        assert isinstance(result, ReasoningResult)
        assert "Error during chain execution" in result.conclusion
        assert result.confidence == 0.0

    def test_evaluate_hypothesis_with_evidence(self):
        engine = ReasoningEngine()
        score = engine.evaluate_hypothesis(
            "Inflation is rising",
            ["price_index_up", "supply_constraints", "wage_increases"]
        )
        assert score == pytest.approx(0.6)  # min(1.0, 3 * 0.2)

    def test_evaluate_hypothesis_no_evidence(self):
        engine = ReasoningEngine()
        score = engine.evaluate_hypothesis("Inflation is rising", [])
        assert score == 0.0

    def test_cross_domain_generalization(self):
        engine = ReasoningEngine()
        result = engine.generalize(
            from_domain="physics",
            to_domain="economics",
            knowledge="gravity"
        )

        assert isinstance(result, str)
        assert "physics" in result
        assert "economics" in result
        assert "gravity" in result
        assert "Transferred" in result

    @patch("backend.core.reasoning_engine.logger")
    def test_logging_on_reason(self, mock_logger):
        engine = ReasoningEngine()
        ctx = ReasoningContext(domain="test", query="test")

        # Mock the return value of bind to be another mock
        mock_bound_logger = mock_logger.bind.return_value

        engine.reason(ctx)

        # Verify bind was called with the correct task
        mock_logger.bind.assert_called_with(task="reasoning_engine")
        # Verify the bound logger's info method was called
        mock_bound_logger.info.assert_called()
