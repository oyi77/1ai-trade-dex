"""Tests for proposal_generator module (Wave 4b)."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from backend.ai.proposal_generator import ProposalGenerator, StrategyProposal
from backend.models.database import Trade, StrategyConfig, StrategyProposal as DBProposal


@pytest.fixture
def sample_trades():
    """Create sample trades for testing."""
    trades = []
    for i in range(20):
        trade = Trade(
            id=i + 1,
            market_ticker=f"BTC-{i}",
            platform="polymarket",
            direction="up" if i % 2 == 0 else "down",
            entry_price=0.5 + (i * 0.01),
            size=10.0,
            timestamp=datetime.now(timezone.utc),
            settled=True,
            settlement_value=1.0 if i % 3 == 0 else 0.0,
            pnl=5.0 if i % 3 == 0 else -3.0,
            model_probability=0.6,
            market_price_at_entry=0.5,
            edge_at_entry=0.1,
            strategy="btc_momentum" if i < 10 else "weather_emos",
            confidence=0.7
        )
        trades.append(trade)
    return trades


@pytest.fixture
def mock_claude_response():
    """Mock Claude API response."""
    return """STRATEGY: btc_momentum
CHANGE_TYPE: parameter_adjustment
CHANGE_DETAILS: {"min_edge": 0.08, "max_position_usd": 150}
EXPECTED_IMPACT: Increase win rate by filtering low-edge trades and allowing larger positions on high-confidence signals.
REASONING: Analysis shows that trades with edge < 0.08 have 40% win rate vs 65% for edge > 0.08. Increasing position size on winners will improve overall PnL.
CONFIDENCE: 0.75
PRIORITY: high
ESTIMATED_IMPROVEMENT: 8.5"""


class TestProposalGenerator:
    """Test suite for ProposalGenerator."""

    def test_init(self):
        """Test ProposalGenerator initialization."""
        generator = ProposalGenerator()
        assert generator is not None
        assert generator.trade_analyzer is not None
        assert generator.claude_analyzer is not None

    @pytest.mark.asyncio
    async def test_generate_proposal_empty_trades(self):
        """Test generate_proposal with empty trade list."""
        generator = ProposalGenerator()
        result = await generator.generate_proposal([])
        assert result is None

    @pytest.mark.asyncio
    async def test_generate_proposal_success(self, sample_trades, mock_claude_response, db):
        """Test successful proposal generation."""
        generator = ProposalGenerator()

        db.add(StrategyConfig(
            strategy_name="btc_momentum",
            enabled=True,
            interval_seconds=60,
            params='{"min_edge": 0.05}'
        ))
        db.commit()

        with patch.object(generator.claude_analyzer, '_get_client') as mock_client:
            mock_message = MagicMock()
            mock_message.content = [MagicMock(text=mock_claude_response)]
            mock_message.usage.input_tokens = 500
            mock_message.usage.output_tokens = 200

            mock_client.return_value.messages.create = AsyncMock(return_value=mock_message)

            proposal = await generator.generate_proposal(sample_trades)

            assert proposal is not None
            assert proposal.strategy_name == "btc_momentum"
            assert proposal.change_type == "parameter_adjustment"
            assert proposal.change_details == {"min_edge": 0.08, "max_position_usd": 150}
            assert proposal.confidence == 0.75
            assert proposal.priority == "high"
            assert proposal.estimated_improvement == 8.5

    def test_get_strategy_configs(self, db):
        """Test retrieving strategy configurations."""
        db.add(StrategyConfig(
            strategy_name="test_strategy",
            enabled=True,
            interval_seconds=120,
            params='{"param1": "value1"}'
        ))
        db.commit()

        generator = ProposalGenerator()
        configs = generator._get_strategy_configs()

        assert "test_strategy" in configs
        assert configs["test_strategy"]["enabled"] is True
        assert configs["test_strategy"]["interval_seconds"] == 120
        assert configs["test_strategy"]["params"]["param1"] == "value1"

    def test_calculate_performance_metrics_empty(self):
        """Test performance metrics with empty trades."""
        generator = ProposalGenerator()
        metrics = generator._calculate_performance_metrics([])
        assert metrics == {}

    def test_calculate_performance_metrics(self, sample_trades):
        """Test performance metrics calculation."""
        generator = ProposalGenerator()
        metrics = generator._calculate_performance_metrics(sample_trades)

        assert metrics["total_trades"] == 20
        assert metrics["winning_trades"] > 0
        assert metrics["losing_trades"] > 0
        assert 0.0 <= metrics["win_rate"] <= 1.0
        assert "strategy_performance" in metrics
        assert "btc_momentum" in metrics["strategy_performance"]
        assert "weather_emos" in metrics["strategy_performance"]

    def test_build_claude_prompt(self, sample_trades):
        """Test Claude prompt building."""
        generator = ProposalGenerator()

        trade_analysis = {
            "total_trades": 20,
            "win_rate": 0.35,
            "common_win_factors": ["high_confidence_signal", "strong_edge"],
            "common_loss_factors": ["weak_edge", "poor_entry_price"],
            "edge_score": 0.6
        }

        strategy_configs = {
            "btc_momentum": {
                "enabled": True,
                "interval_seconds": 60,
                "params": {"min_edge": 0.05}
            }
        }

        performance_metrics = {
            "total_trades": 20,
            "win_rate": 0.35,
            "total_pnl": 10.0,
            "avg_pnl": 0.5,
            "strategy_performance": {
                "btc_momentum": {"trades": 10, "win_rate": 0.4, "pnl": 5.0}
            }
        }

        prompt = generator._build_claude_prompt(
            trade_analysis=trade_analysis,
            strategy_configs=strategy_configs,
            performance_metrics=performance_metrics,
            recent_trades=sample_trades
        )

        assert "PERFORMANCE SUMMARY" in prompt
        assert "STRATEGY PERFORMANCE" in prompt
        assert "TRADE ANALYSIS" in prompt
        assert "CURRENT STRATEGY CONFIGURATIONS" in prompt
        assert "btc_momentum" in prompt
        assert "35.0%" in prompt

    def test_parse_claude_response_success(self, mock_claude_response):
        """Test parsing valid Claude response."""
        generator = ProposalGenerator()

        proposal = generator._parse_claude_response(
            mock_claude_response,
            {"total_trades": 20}
        )

        assert proposal is not None
        assert proposal.strategy_name == "btc_momentum"
        assert proposal.change_type == "parameter_adjustment"
        assert proposal.change_details["min_edge"] == 0.08
        assert proposal.confidence == 0.75
        assert proposal.priority == "high"

    def test_parse_claude_response_invalid(self):
        """Test parsing invalid Claude response."""
        generator = ProposalGenerator()

        invalid_response = "This is not a valid response format"
        proposal = generator._parse_claude_response(invalid_response, {})

        assert proposal is None

    def test_parse_claude_response_invalid_json(self):
        """Test parsing response with invalid JSON."""
        generator = ProposalGenerator()

        response = """STRATEGY: test
CHANGE_TYPE: parameter_adjustment
CHANGE_DETAILS: {invalid json}
EXPECTED_IMPACT: Test
REASONING: Test"""

        proposal = generator._parse_claude_response(response, {})
        assert proposal is None

    def test_parse_claude_response_clamps_confidence(self):
        """Test that confidence is clamped to [0, 1]."""
        generator = ProposalGenerator()

        response = """STRATEGY: test
CHANGE_TYPE: parameter_adjustment
CHANGE_DETAILS: {"param": 1}
EXPECTED_IMPACT: Test
REASONING: Test
CONFIDENCE: 1.5
PRIORITY: high"""

        proposal = generator._parse_claude_response(response, {})
        assert proposal is not None
        assert proposal.confidence == 1.0

    def test_store_proposal(self, db):
        """Test storing proposal in database."""
        generator = ProposalGenerator()

        proposal = StrategyProposal(
            strategy_name="test_strategy",
            change_type="parameter_adjustment",
            change_details={"param": "value"},
            expected_impact="Test impact",
            reasoning="Test reasoning",
            confidence=0.8,
            priority="high"
        )

        proposal_id = generator._store_proposal(proposal)

        assert proposal_id > 0

        db_proposal = db.query(DBProposal).filter(DBProposal.id == proposal_id).first()
        assert db_proposal is not None
        assert db_proposal.strategy_name == "test_strategy"
        assert db_proposal.admin_decision == "pending"
        assert db_proposal.change_details == {"param": "value"}

    def test_get_pending_proposals_empty(self, db):
        """Test getting pending proposals when none exist."""
        db.query(DBProposal).delete()
        db.commit()

        generator = ProposalGenerator()
        proposals = generator.get_pending_proposals()
        assert proposals == []

    def test_get_pending_proposals(self, db):
        """Test getting pending proposals."""
        db.query(DBProposal).delete()
        db.commit()

        db.add(DBProposal(
            strategy_name="test1",
            change_details={"param": 1},
            expected_impact="Impact 1",
            admin_decision="pending"
        ))
        db.add(DBProposal(
            strategy_name="test2",
            change_details={"param": 2},
            expected_impact="Impact 2",
            admin_decision="approved"
        ))
        db.commit()

        generator = ProposalGenerator()
        proposals = generator.get_pending_proposals()

        assert len(proposals) == 1
        assert proposals[0]["strategy_name"] == "test1"
        assert proposals[0]["admin_decision"] == "pending"

    def test_approve_proposal_success(self, db):
        """Test approving a proposal."""
        proposal = DBProposal(
            strategy_name="test",
            change_details={"param": 1},
            expected_impact="Test",
            admin_decision="pending"
        )
        db.add(proposal)
        db.commit()

        generator = ProposalGenerator()
        success = generator.approve_proposal(proposal.id, "admin123")

        assert success is True

        db.refresh(proposal)
        assert proposal.admin_decision == "approved"
        assert proposal.admin_user_id == "admin123"
        assert proposal.executed_at is not None

    def test_approve_proposal_not_found(self, db):
        """Test approving non-existent proposal."""
        generator = ProposalGenerator()
        success = generator.approve_proposal(99999, "admin123")
        assert success is False

    def test_approve_proposal_already_processed(self, db):
        """Test approving already processed proposal."""
        proposal = DBProposal(
            strategy_name="test",
            change_details={"param": 1},
            expected_impact="Test",
            admin_decision="approved"
        )
        db.add(proposal)
        db.commit()

        generator = ProposalGenerator()
        success = generator.approve_proposal(proposal.id, "admin123")
        assert success is False

    def test_reject_proposal_success(self, db):
        """Test rejecting a proposal."""
        proposal = DBProposal(
            strategy_name="test",
            change_details={"param": 1},
            expected_impact="Test",
            admin_decision="pending"
        )
        db.add(proposal)
        db.commit()

        generator = ProposalGenerator()
        success = generator.reject_proposal(proposal.id, "admin123")

        assert success is True

        db.refresh(proposal)
        assert proposal.admin_decision == "rejected"
        assert proposal.admin_user_id == "admin123"

    def test_reject_proposal_not_found(self, db):
        """Test rejecting non-existent proposal."""
        generator = ProposalGenerator()
        success = generator.reject_proposal(99999, "admin123")
        assert success is False

    def test_format_strategy_configs(self):
        """Test formatting strategy configs for prompt."""
        generator = ProposalGenerator()

        configs = {
            "strategy1": {
                "enabled": True,
                "interval_seconds": 60,
                "params": {"min_edge": 0.05}
            },
            "strategy2": {
                "enabled": False,
                "interval_seconds": 120,
                "params": {}
            }
        }

        formatted = generator._format_strategy_configs(configs)

        assert "strategy1" in formatted
        assert "strategy2" in formatted
        assert "enabled=True" in formatted
        assert "interval=60s" in formatted
