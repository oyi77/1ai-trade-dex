"""Tests for LifecycleManager.

Wave 11: Lifecycle Stage Machine — Part 4
Tests the full lifecycle stage transitions and auto-kill conditions.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from sqlalchemy.orm import Session

from backend.application.agi.lifecycle_manager import (
    LifecycleManager,
    should_promote_paper_to_live,
    check_rehabilitation_eligibility,
    AUTO_KILL_CONDITIONS
)
from backend.domain.genome.models import StrategyGenome, FitnessMetrics, DeathCertificate, LineageData
from backend.domain.evolution.evolution_action import EvolutionAction


def create_test_genome(stage="DRAFT", **metrics_kwargs) -> StrategyGenome:
    """Helper to create test genomes with custom metrics."""
    metrics = FitnessMetrics(
        sharpe_ratio=metrics_kwargs.get("sharpe_ratio", 0.0),
        win_rate=metrics_kwargs.get("win_rate", 0.5),
        profit_factor=metrics_kwargs.get("profit_factor", 1.0),
        max_drawdown_pct=metrics_kwargs.get("max_drawdown_pct", 0.10),
        brier_score=metrics_kwargs.get("brier_score", 0.20),
        alpha_per_trade=metrics_kwargs.get("alpha_per_trade", 0.01),
        capital_rotation_efficiency=metrics_kwargs.get("capital_rotation_efficiency", 0.5),
        total_trades=metrics_kwargs.get("total_trades", 50)
    )
    
    return StrategyGenome(
        genome_id="test_genome_123",
        strategy_name="Test Strategy",
        archetype="momentum",
        stage=stage,
        chromosomes={},
        fitness_metrics=metrics
    )


def test_auto_kill_conditions():
    """Test auto-kill conditions."""
    # Test 50% drawdown condition
    metrics = FitnessMetrics(max_drawdown_pct=0.51)
    assert AUTO_KILL_CONDITIONS[0](metrics) == True
    
    metrics = FitnessMetrics(max_drawdown_pct=0.49)
    assert AUTO_KILL_CONDITIONS[0](metrics) == False
    
    # Test Sharpe + win rate condition
    metrics = FitnessMetrics(sharpe_ratio=-2.1, win_rate=0.04)
    assert AUTO_KILL_CONDITIONS[1](metrics) == True
    
    metrics = FitnessMetrics(sharpe_ratio=-1.9, win_rate=0.06)
    assert AUTO_KILL_CONDITIONS[1](metrics) == False
    
    # Test brier score condition
    metrics = FitnessMetrics(brier_score=0.36)
    assert AUTO_KILL_CONDITIONS[2](metrics) == True
    
    metrics = FitnessMetrics(brier_score=0.34)
    assert AUTO_KILL_CONDITIONS[2](metrics) == False
    
    # Test that we have 3 auto-kill conditions
    assert len(AUTO_KILL_CONDITIONS) == 3


def test_should_promote_paper_to_live():
    """Test regime-aware paper to live promotion."""
    # Test minimum trade requirement
    genome = create_test_genome(
        stage="PAPER",
        total_trades=49,
        sharpe_ratio=0.6,
        win_rate=0.6
    )
    assert should_promote_paper_to_live(genome, "volatile") == False
    
    # Test max drawdown requirement
    genome = create_test_genome(
        stage="PAPER",
        total_trades=50,
        max_drawdown_pct=0.21,
        sharpe_ratio=0.6,
        win_rate=0.6
    )
    assert should_promote_paper_to_live(genome, "volatile") == False
    
    # Test volatile regime thresholds
    genome = create_test_genome(
        stage="PAPER",
        total_trades=50,
        max_drawdown_pct=0.19,
        sharpe_ratio=0.60,
        win_rate=0.50
    )
    assert should_promote_paper_to_live(genome, "volatile") == True
    
    genome = create_test_genome(
        stage="PAPER",
        total_trades=50,
        max_drawdown_pct=0.19,
        sharpe_ratio=0.59,
        win_rate=0.50
    )
    assert should_promote_paper_to_live(genome, "volatile") == False
    
    # Test trending regime thresholds
    genome = create_test_genome(
        stage="PAPER",
        total_trades=50,
        max_drawdown_pct=0.19,
        sharpe_ratio=0.40,
        win_rate=0.55
    )
    assert should_promote_paper_to_live(genome, "trending") == True
    
    # Test default regime thresholds
    genome = create_test_genome(
        stage="PAPER",
        total_trades=50,
        max_drawdown_pct=0.19,
        sharpe_ratio=0.50,
        win_rate=0.50
    )
    assert should_promote_paper_to_live(genome, "unknown_regime") == True


def test_draft_to_shadow_transition():
    """Test DRAFT → SHADOW transition logic."""
    manager = LifecycleManager()
    
    # Test successful transition to SHADOW
    genome = create_test_genome(
        stage="DRAFT",
        sharpe_ratio=0.35,
        max_drawdown_pct=0.20
    )
    
    with patch.object(manager, '_get_stage_entered_at') as mock_stage:
        mock_stage.return_value = datetime.now(timezone.utc) - timedelta(hours=1)
        result = manager.evaluate_stage_transition(genome, "volatile", MagicMock())
        assert result == "SHADOW"
    
    # Test transition to GRAVEYARD (auto-kill)
    genome = create_test_genome(
        stage="DRAFT",
        sharpe_ratio=0.25,
        max_drawdown_pct=0.60  # High drawdown triggers auto-kill
    )
    
    result = manager.evaluate_stage_transition(genome, "volatile", MagicMock())
    assert result == "GRAVEYARD"
    
    # Test no transition (insufficient performance)
    genome = create_test_genome(
        stage="DRAFT",
        sharpe_ratio=0.25,
        max_drawdown_pct=0.20
    )
    
    result = manager.evaluate_stage_transition(genome, "volatile", MagicMock())
    assert result is None


def test_shadow_to_paper_transition():
    """Test SHADOW → PAPER transition logic."""
    manager = LifecycleManager()
    
    # Test successful transition to PAPER
    genome = create_test_genome(
        stage="SHADOW",
        win_rate=0.65  # High signal accuracy
    )
    
    with patch.object(LifecycleManager, '_get_stage_entered_at') as mock_stage:
        mock_stage.return_value = datetime.now(timezone.utc) - timedelta(hours=25)
        with patch.object(LifecycleManager, '_check_auto_kill') as mock_kill:
            mock_kill.return_value = False
            result = manager.evaluate_stage_transition(genome, "volatile", MagicMock())
            assert result == "PAPER"
    
    # Test no transition (insufficient time in stage)
    with patch.object(LifecycleManager, '_get_stage_entered_at') as mock_stage:
        mock_stage.return_value = datetime.now(timezone.utc) - timedelta(hours=23)
        with patch.object(LifecycleManager, '_check_auto_kill') as mock_kill:
            mock_kill.return_value = False
            result = manager.evaluate_stage_transition(genome, "volatile", MagicMock())
            assert result is None
    
    # Test transition to GRAVEYARD (auto-kill with high brier score)
    genome = create_test_genome(
        stage="SHADOW",
        win_rate=0.55,  # Less than 0.60 threshold so doesn't promote to PAPER
        brier_score=0.36
    )

    with patch.object(LifecycleManager, '_get_stage_entered_at') as mock_stage:
        mock_stage.return_value = datetime.now(timezone.utc) - timedelta(hours=25)
        result = manager.evaluate_stage_transition(genome, "volatile", MagicMock())
        assert result == "GRAVEYARD"


def test_paper_to_live_transition():
    """Test PAPER → LIVE transition logic."""
    manager = LifecycleManager()
    
    # Test successful transition using should_promote_paper_to_live
    genome = create_test_genome(
        stage="PAPER",
        total_trades=60,
        max_drawdown_pct=0.15,
        sharpe_ratio=0.65,
        win_rate=0.55
    )
    
    result = manager.evaluate_stage_transition(genome, "volatile", MagicMock())
    assert result == "LIVE"
    
    # Test no transition (insufficient metrics)
    genome = create_test_genome(
        stage="PAPER",
        total_trades=40,
        max_drawdown_pct=0.15,
        sharpe_ratio=0.65,
        win_rate=0.55
    )
    
    result = manager.evaluate_stage_transition(genome, "volatile", MagicMock())
    assert result is None


def test_live_to_breeding_transition():
    """Test LIVE → BREEDING transition logic."""
    manager = LifecycleManager()
    
    # Test successful transition to BREEDING
    genome = create_test_genome(
        stage="LIVE",
        sharpe_ratio=3.0,
        win_rate=0.85,
        profit_factor=2.0,
        max_drawdown_pct=0.05,
        total_trades=100
    )
    
    with patch.object(manager, '_get_stage_entered_at') as mock_stage:
        mock_stage.return_value = datetime.now(timezone.utc) - timedelta(days=15)
        result = manager.evaluate_stage_transition(genome, "volatile", MagicMock())
        assert result == "BREEDING"
    
    # Test no transition (insufficient time in LIVE)
    with patch.object(manager, '_get_stage_entered_at') as mock_stage:
        mock_stage.return_value = datetime.now(timezone.utc) - timedelta(days=13)
        result = manager.evaluate_stage_transition(genome, "volatile", MagicMock())
        assert result is None
    
    # Test transition to GRAVEYARD (auto-kill with high drawdown)
    genome = create_test_genome(
        stage="LIVE",
        max_drawdown_pct=0.55,
        total_trades=100
    )
    
    result = manager.evaluate_stage_transition(genome, "volatile", MagicMock())
    assert result == "GRAVEYARD"


def test_breeding_to_legend_transition():
    """Test BREEDING → LEGEND transition logic."""
    manager = LifecycleManager()
    
    # Test successful transition to LEGEND
    genome = create_test_genome(
        stage="BREEDING",
        sharpe_ratio=3.0,
        win_rate=0.90,
        profit_factor=3.0,
        max_drawdown_pct=0.03,
        alpha_per_trade=0.5,
        capital_rotation_efficiency=0.9,
        total_trades=200
    )
    
    with patch.object(manager, '_get_stage_entered_at') as mock_stage:
        with patch.object(manager, '_get_total_pnl_for_genome') as mock_pnl:
            # Mock that genome has been in LIVE for 60+ days
            mock_stage.return_value = datetime.now(timezone.utc) - timedelta(days=70)
            mock_pnl.return_value = 600.0  # $600 PnL > $500 threshold
            
            result = manager.evaluate_stage_transition(genome, "volatile", MagicMock())
            assert result == "LEGEND"
    
    # Test no transition (insufficient PnL)
    genome_no_legend = create_test_genome(
        stage="BREEDING",
        sharpe_ratio=3.0,
        win_rate=0.85,
        profit_factor=2.0,
        max_drawdown_pct=0.05,
        total_trades=200
    )
    with patch.object(manager, '_get_stage_entered_at') as mock_stage:
        with patch.object(manager, '_get_total_pnl_for_genome') as mock_pnl:
            mock_stage.return_value = datetime.now(timezone.utc) - timedelta(days=70)
            mock_pnl.return_value = 400.0  # $400 PnL < $500 threshold

            result = manager.evaluate_stage_transition(genome_no_legend, "volatile", MagicMock())
            assert result is None


def test_breeding_to_live_downgrade():
    """Test BREEDING → LIVE downgrade when fitness drops."""
    manager = LifecycleManager()
    
    # Test downgrade to LIVE when fitness drops below 0.75
    genome = create_test_genome(
        stage="BREEDING",
        sharpe_ratio=1.5,
        win_rate=0.60,
        total_trades=100
    )
    
    result = manager.evaluate_stage_transition(genome, "volatile", MagicMock())
    assert result == "LIVE"


def test_check_auto_kill():
    """Test auto-kill detection."""
    manager = LifecycleManager()
    
    # Test high drawdown kill
    genome = create_test_genome(
        max_drawdown_pct=0.55
    )
    
    cert = manager.check_auto_kill(genome)
    assert cert is not None
    assert cert.reason == "auto_kill"
    assert cert.killer_condition == str(AUTO_KILL_CONDITIONS[0])
    
    # Test Sharpe + win rate kill
    genome = create_test_genome(
        sharpe_ratio=-2.5,
        win_rate=0.04
    )
    
    cert = manager.check_auto_kill(genome)
    assert cert is not None
    assert cert.killer_condition == str(AUTO_KILL_CONDITIONS[1])
    
    # Test no kill
    genome = create_test_genome(
        sharpe_ratio=0.5,
        win_rate=0.55
    )
    
    cert = manager.check_auto_kill(genome)
    assert cert is None


def test_execute_transition():
    """Test transition execution and event publishing."""
    manager = LifecycleManager()
    genome = create_test_genome(stage="DRAFT")
    
    mock_db = MagicMock(spec=Session)
    mock_genome_registry = MagicMock()
    mock_genome_registry.genome_id = genome.genome_id
    mock_genome_registry.stage = "DRAFT"
    mock_genome_registry.stage_entered_at = datetime.now(timezone.utc)
    
    mock_db.query.return_value.filter.return_value.first.return_value = mock_genome_registry
    
    with patch('backend.application.agi.lifecycle_manager.publish_event') as mock_publish:
        action = manager.execute_transition(genome, "SHADOW", mock_db)
        
        # Verify action properties
        assert action.action_type == "promotion"
        assert action.genome_id == genome.genome_id
        assert action.from_stage == "DRAFT"
        assert action.to_stage == "SHADOW"
        assert "fitness_score" in action.details
        
        # Verify event was published
        assert mock_publish.called
        call_args = mock_publish.call_args[0]
        assert call_args[0] == "lifecycle_transition"
        assert call_args[1]["genome_id"] == genome.genome_id
        assert call_args[1]["from_stage"] == "DRAFT"
        assert call_args[1]["to_stage"] == "SHADOW"


def test_check_rehabilitation_eligibility():
    """Test GRAVEYARD rehabilitation eligibility."""
    manager = LifecycleManager()
    
    # Test not in GRAVEYARD
    genome = create_test_genome(stage="LIVE")
    mock_db = MagicMock()
    
    assert check_rehabilitation_eligibility(genome, mock_db) == False
    
    # Test in GRAVEYARD but insufficient trades
    genome = create_test_genome(stage="GRAVEYARD")
    mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
    
    assert check_rehabilitation_eligibility(genome, mock_db) == False
    
    # Test successful rehabilitation
    mock_trade1 = MagicMock()
    mock_trade1.pnl = 10.0
    mock_trade2 = MagicMock()
    mock_trade2.pnl = -5.0
    mock_trade3 = MagicMock()
    mock_trade3.pnl = 8.0
    
    mock_trades = [mock_trade1, mock_trade2, mock_trade3, mock_trade1, mock_trade2]
    mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = mock_trades
    
    # 4 winning trades out of 5 = 80% win rate, positive PnL
    assert check_rehabilitation_eligibility(genome, mock_db) == True
    
    # Test insufficient win rate
    mock_trade4 = MagicMock()
    mock_trade4.pnl = -15.0
    mock_trades = [mock_trade1, mock_trade4, mock_trade4, mock_trade4, mock_trade4]  # 1 win, 4 losses
    mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = mock_trades
    
    assert check_rehabilitation_eligibility(genome, mock_db) == False


def test_legend_stage_no_transition():
    """Test that LEGEND stage has no automatic exits."""
    manager = LifecycleManager()
    
    genome = create_test_genome(stage="LEGEND")
    
    result = manager.evaluate_stage_transition(genome, "volatile", MagicMock())
    assert result is None


def test_graveyard_rehabilitation():
    """Test GRAVEYARD → DRAFT rehabilitation."""
    manager = LifecycleManager()
    
    genome = create_test_genome(stage="GRAVEYARD")
    
    # Mock successful rehabilitation check
    with patch('backend.application.agi.lifecycle_manager.check_rehabilitation_eligibility') as mock_check:
        mock_check.return_value = True
        
        result = manager.evaluate_stage_transition(genome, "volatile", MagicMock())
        assert result == "DRAFT"
    
    # Mock failed rehabilitation check
    with patch('backend.application.agi.lifecycle_manager.check_rehabilitation_eligibility') as mock_check:
        mock_check.return_value = False
        
        result = manager.evaluate_stage_transition(genome, "volatile", MagicMock())
        assert result is None
