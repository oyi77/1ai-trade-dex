import pytest
import datetime
from unittest.mock import patch
from backend.services.mirofish_mock_server import generate_signal

def test_generate_signal_empty_templates():
    """Test generate_signal when SIGNAL_TEMPLATES is empty."""
    with patch('backend.services.mirofish_mock_server.SIGNAL_TEMPLATES', []):
        signal = generate_signal()

        assert isinstance(signal, dict)
        assert signal["market_id"] == "unknown"
        assert signal["market_question"] == "Waiting for live market data..."
        assert signal["market_type"] == "unknown"
        assert signal["prediction"] == 0.5
        assert signal["confidence"] == 0.5
        assert signal["edge"] == 0.0
        assert signal["fair_value"] == 0.5
        assert signal["current_price"] == 0.5
        assert "No live Polymarket data available" in signal["reasoning"]
        assert signal["sources"] == []
        assert "generated_at" in signal
        assert isinstance(signal["generated_at"], str)
        assert signal["signal_id"].startswith("mock_")

def test_generate_signal_with_templates():
    """Test generate_signal when SIGNAL_TEMPLATES has data."""
    mock_template = {
        "market_id": "poly_test_1",
        "market_question": "Will AI take over?",
        "market_type": "crypto",
        "prediction": 0.8,
        "confidence": 0.7,
        "edge": 0.1,
        "fair_value": 0.75,
        "current_price": 0.8,
        "reasoning": "Live Polymarket: Will AI take over?...",
        "sources": ["Polymarket Gamma API", "live order book"],
    }
    with patch('backend.services.mirofish_mock_server.SIGNAL_TEMPLATES', [mock_template]):
        with patch('backend.services.mirofish_mock_server.random.uniform', return_value=0.03):
            signal = generate_signal()

            assert isinstance(signal, dict)
            assert signal["market_id"] == "poly_test_1"
            assert signal["market_question"] == "Will AI take over?"
            assert signal["market_type"] == "crypto"
            assert signal["prediction"] == 0.8
            # noise is 0.03
            assert signal["confidence"] == min(0.95, mock_template["confidence"] + 0.03)
            assert signal["edge"] == mock_template["edge"] + 0.03
            assert signal["fair_value"] == 0.75
            assert signal["current_price"] == min(0.9, mock_template["current_price"] + 0.03 * 0.5)
            assert signal["reasoning"] == "Live Polymarket: Will AI take over?..."
            assert signal["sources"] == ["Polymarket Gamma API", "live order book"]
            assert "generated_at" in signal
            assert isinstance(signal["generated_at"], str)
            assert signal["signal_id"].startswith("livepoly_")

def test_generate_signal_bounds():
    """Test generate_signal boundary conditions for confidence, edge, and current_price."""
    # Test lower bounds
    low_template = {
        "market_id": "low_test",
        "market_question": "Low?",
        "market_type": "crypto",
        "prediction": 0.1,
        "confidence": 0.1, # Should be bumped to 0.5 min
        "edge": -0.1, # Should be bumped to 0.02 min
        "fair_value": 0.1,
        "current_price": 0.05, # Should be bumped to 0.1 min
        "reasoning": "...",
        "sources": [],
    }
    with patch('backend.services.mirofish_mock_server.SIGNAL_TEMPLATES', [low_template]):
        with patch('backend.services.mirofish_mock_server.random.uniform', return_value=-0.05):
            signal = generate_signal()
            assert signal["confidence"] == 0.5
            assert signal["edge"] == 0.02
            assert signal["current_price"] == 0.1

    # Test upper bounds
    high_template = {
        "market_id": "high_test",
        "market_question": "High?",
        "market_type": "crypto",
        "prediction": 0.9,
        "confidence": 0.98, # Should be capped at 0.95
        "edge": 0.5,
        "fair_value": 0.9,
        "current_price": 0.98, # Should be capped at 0.9
        "reasoning": "...",
        "sources": [],
    }
    with patch('backend.services.mirofish_mock_server.SIGNAL_TEMPLATES', [high_template]):
        with patch('backend.services.mirofish_mock_server.random.uniform', return_value=0.05):
            signal = generate_signal()
            assert signal["confidence"] == 0.95
            assert signal["edge"] == 0.55 # 0.5 + 0.05
            assert signal["current_price"] == 0.9
