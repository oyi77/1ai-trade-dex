"""Tests for necromancer.py - Wave 9 Meta-Learning Layer."""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch
from collections import Counter

from backend.application.agi.necromancer import (
    run_necromancy_analysis,
    NecromancyReport,
    find_genes_overrepresented_in,
    generate_anti_patterns
)


def test_find_genes_overrepresented_in():
    """Test gene overrepresentation detection."""
    # Test with empty list
    result = find_genes_overrepresented_in([], threshold=0.70)
    assert result == []
    
    # Test with genomes having common genes
    genomes = [
        {"chromosomes": {"perception": {"signal_source": "polymarket"}}},
        {"chromosomes": {"perception": {"signal_source": "polymarket"}}},
        {"chromosomes": {"perception": {"signal_source": "polymarket"}}},
    ]
    
    result = find_genes_overrepresented_in(genomes, threshold=0.70)
    assert len(result) == 1
    assert result[0]["gene"] == "perception.signal_source.polymarket"
    assert result[0]["frequency"] == 1.0


def test_generate_anti_patterns():
    """Test anti-pattern generation."""
    # Test with empty list
    result = generate_anti_patterns([])
    assert result == []
    
    # Test with genomes having death causes
    dead_genomes = [
        {"death_certificate": {"killer_condition": "CAUSE_SLIPPAGE_HIGH"}},
        {"death_certificate": {"killer_condition": "CAUSE_SLIPPAGE_HIGH"}},
        {"death_certificate": {"killer_condition": "CAUSE_LATE_ENTRY"}},
    ]
    
    result = generate_anti_patterns(dead_genomes)
    assert len(result) >= 1
    assert result[0]["pattern_name"] == "anti_CAUSE_SLIPPAGE_HIGH"


def test_run_necromancy_analysis():
    """Test full necromancy analysis workflow."""
    db = MagicMock()
    
    with patch('backend.application.agi.necromancer.load_graveyard', return_value=[]):
        with patch('backend.application.agi.necromancer.load_legends', return_value=[]):
            with patch('backend.application.agi.necromancer.publish_event') as mock_publish:
                report = run_necromancy_analysis(db)
                
                assert isinstance(report, NecromancyReport)
                assert report.death_causes == {}
                assert report.high_risk_genes == []
                assert report.legend_genes == []
                
                # Check event publishing
                assert mock_publish.called
                call_args = [call[0][0] for call in mock_publish.call_args_list]
                assert "necromancy_report" in call_args


def test_necromancy_report_structure():
    """Test NecromancyReport dataclass structure."""
    report = NecromancyReport(
        date=datetime.now(),
        death_causes={"cause1": 5, "cause2": 3},
        high_risk_genes=[{"gene": "risk.high_leverage", "frequency": 0.8}],
        legend_genes=[{"gene": "meta.adaptive", "frequency": 0.9}],
        new_anti_patterns=[{"pattern_name": "anti_slippage", "severity": "high"}]
    )
    
    assert report.date is not None
    assert report.death_causes == {"cause1": 5, "cause2": 3}
    assert len(report.high_risk_genes) == 1
    assert len(report.legend_genes) == 1
    assert len(report.new_anti_patterns) == 1
