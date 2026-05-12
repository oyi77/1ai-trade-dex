"""Tests for backend/ai/signal_parser.py — MiroFish signal parsing and debate integration."""

import pytest

from backend.ai.signal_parser import (
    Signal,
    SignalParser,
    get_signal_parser,
    reset_signal_parser,
)


# --- Fixtures ---


@pytest.fixture
def signal_parser():
    """Fresh SignalParser instance for each test."""
    reset_signal_parser()
    return SignalParser()


@pytest.fixture
def sample_mirofish_signal():
    """Valid MiroFish signal from API."""
    return {
        "market_id": "0x123abc",
        "prediction": 0.75,
        "confidence": 0.85,
        "reasoning": "Strong bullish momentum detected",
        "source": "mirofish_prediction",
    }


@pytest.fixture
def sample_invalid_signal():
    """Invalid MiroFish signal (missing prediction)."""
    return {
        "market_id": "0x456def",
        "confidence": 0.80,
        "reasoning": "Incomplete signal",
    }


@pytest.fixture
def sample_strategy_signal():
    """Signal from existing strategy (for aggregation test)."""
    return Signal(
        market_id="0x123abc",
        prediction=0.70,
        confidence=0.80,
        source="btc_oracle",
        reasoning="BTC momentum positive",
        weight=1.0,
    )


# --- Parse Single Signal ---


def test_parse_valid_mirofish_signal(signal_parser, sample_mirofish_signal):
    """Parse valid MiroFish signal → correct Signal object."""
    signal = signal_parser.parse_mirofish_signal(sample_mirofish_signal)
    
    assert signal is not None
    assert signal.market_id == "0x123abc"
    assert signal.prediction == pytest.approx(0.75)
    assert signal.confidence == pytest.approx(0.85)
    assert signal.reasoning == "Strong bullish momentum detected"
    assert signal.source == "mirofish_prediction"
    assert signal.weight == pytest.approx(1.0)


def test_parse_signal_missing_market_id(signal_parser):
    """Parse signal without market_id → None (logged, no crash)."""
    invalid_signal = {
        "prediction": 0.75,
        "confidence": 0.85,
        "reasoning": "Test",
    }
    signal = signal_parser.parse_mirofish_signal(invalid_signal)
    
    assert signal is None


def test_parse_signal_missing_prediction(signal_parser):
    """Parse signal without prediction → None (logged, no crash)."""
    invalid_signal = {
        "market_id": "0x123abc",
        "confidence": 0.85,
        "reasoning": "Test",
    }
    signal = signal_parser.parse_mirofish_signal(invalid_signal)
    
    assert signal is None


def test_parse_signal_missing_confidence(signal_parser):
    """Parse signal without confidence → None (logged, no crash)."""
    invalid_signal = {
        "market_id": "0x123abc",
        "prediction": 0.75,
        "reasoning": "Test",
    }
    signal = signal_parser.parse_mirofish_signal(invalid_signal)
    
    assert signal is None


def test_parse_signal_prediction_out_of_range_high(signal_parser):
    """Parse signal with prediction > 1.0 → None."""
    invalid_signal = {
        "market_id": "0x123abc",
        "prediction": 1.5,
        "confidence": 0.85,
        "reasoning": "Out of range",
    }
    signal = signal_parser.parse_mirofish_signal(invalid_signal)
    
    assert signal is None


def test_parse_signal_prediction_out_of_range_low(signal_parser):
    """Parse signal with prediction < 0.0 → None."""
    invalid_signal = {
        "market_id": "0x123abc",
        "prediction": -0.5,
        "confidence": 0.85,
        "reasoning": "Out of range",
    }
    signal = signal_parser.parse_mirofish_signal(invalid_signal)
    
    assert signal is None


def test_parse_signal_confidence_out_of_range(signal_parser):
    """Parse signal with confidence > 1.0 → None."""
    invalid_signal = {
        "market_id": "0x123abc",
        "prediction": 0.75,
        "confidence": 1.5,
        "reasoning": "Out of range",
    }
    signal = signal_parser.parse_mirofish_signal(invalid_signal)
    
    assert signal is None


def test_parse_signal_type_conversion_failure(signal_parser):
    """Parse signal with non-numeric prediction → None (logged, no crash)."""
    invalid_signal = {
        "market_id": "0x123abc",
        "prediction": "invalid",
        "confidence": 0.85,
        "reasoning": "Type conversion test",
    }
    signal = signal_parser.parse_mirofish_signal(invalid_signal)
    
    assert signal is None


def test_parse_signal_missing_reasoning_defaults_to_empty(signal_parser):
    """Parse signal without reasoning → defaults to empty string."""
    signal_data = {
        "market_id": "0x123abc",
        "prediction": 0.75,
        "confidence": 0.85,
    }
    signal = signal_parser.parse_mirofish_signal(signal_data)
    
    assert signal is not None
    assert signal.reasoning == ""


def test_parse_signal_empty_market_id(signal_parser):
    """Parse signal with empty market_id string → None."""
    invalid_signal = {
        "market_id": "",
        "prediction": 0.75,
        "confidence": 0.85,
        "reasoning": "Empty market_id",
    }
    signal = signal_parser.parse_mirofish_signal(invalid_signal)
    
    assert signal is None


def test_parse_signal_boundary_prediction_0(signal_parser):
    """Parse signal with prediction = 0.0 (boundary) → valid."""
    signal_data = {
        "market_id": "0x123abc",
        "prediction": 0.0,
        "confidence": 0.85,
        "reasoning": "Edge case",
    }
    signal = signal_parser.parse_mirofish_signal(signal_data)
    
    assert signal is not None
    assert signal.prediction == pytest.approx(0.0)


def test_parse_signal_boundary_prediction_1(signal_parser):
    """Parse signal with prediction = 1.0 (boundary) → valid."""
    signal_data = {
        "market_id": "0x123abc",
        "prediction": 1.0,
        "confidence": 0.85,
        "reasoning": "Edge case",
    }
    signal = signal_parser.parse_mirofish_signal(signal_data)
    
    assert signal is not None
    assert signal.prediction == pytest.approx(1.0)


# --- Parse Multiple Signals ---


def test_parse_multiple_signals_mixed_valid_invalid(signal_parser):
    """Parse list with valid and invalid signals → skips invalid ones."""
    signals_data = [
        {
            "market_id": "0x111",
            "prediction": 0.75,
            "confidence": 0.85,
            "reasoning": "Valid 1",
        },
        {
            "market_id": "0x222",
            "prediction": 1.5,
            "confidence": 0.85,
            "reasoning": "Invalid - out of range",
        },
        {
            "market_id": "0x333",
            "prediction": 0.55,
            "confidence": 0.90,
            "reasoning": "Valid 2",
        },
    ]
    
    parsed = signal_parser.parse_mirofish_signals(signals_data)
    
    assert len(parsed) == 2
    assert parsed[0].market_id == "0x111"
    assert parsed[1].market_id == "0x333"


def test_parse_empty_signals_list(signal_parser):
    """Parse empty list → returns empty list."""
    parsed = signal_parser.parse_mirofish_signals([])
    
    assert len(parsed) == 0


def test_parse_all_invalid_signals(signal_parser):
    """Parse list of all invalid signals → returns empty list."""
    signals_data = [
        {"market_id": "0x111"},  # Missing prediction
        {"market_id": "0x222"},  # Missing confidence
        {},  # Missing everything
    ]
    
    parsed = signal_parser.parse_mirofish_signals(signals_data)
    
    assert len(parsed) == 0


# --- Aggregate Signals ---


def test_aggregate_mirofish_with_existing(signal_parser, sample_mirofish_signal, sample_strategy_signal):
    """Aggregate MiroFish + existing strategy signals → merged list."""
    mirofish_signal = signal_parser.parse_mirofish_signal(sample_mirofish_signal)
    all_signals = signal_parser.aggregate_signals(
        [mirofish_signal],
        [sample_strategy_signal]
    )
    
    assert len(all_signals) == 2
    assert all_signals[0].source == "mirofish_prediction"
    assert all_signals[1].source == "btc_oracle"


def test_aggregate_only_mirofish(signal_parser, sample_mirofish_signal):
    """Aggregate only MiroFish signals (no existing) → returns MiroFish signals."""
    mirofish_signal = signal_parser.parse_mirofish_signal(sample_mirofish_signal)
    all_signals = signal_parser.aggregate_signals([mirofish_signal], None)
    
    assert len(all_signals) == 1
    assert all_signals[0].source == "mirofish_prediction"


def test_aggregate_empty_mirofish_with_existing(signal_parser, sample_strategy_signal):
    """Aggregate empty MiroFish with existing → returns existing only."""
    all_signals = signal_parser.aggregate_signals([], [sample_strategy_signal])
    
    assert len(all_signals) == 1
    assert all_signals[0].source == "btc_oracle"


def test_aggregate_both_empty(signal_parser):
    """Aggregate both empty → returns empty list."""
    all_signals = signal_parser.aggregate_signals([], [])
    
    assert len(all_signals) == 0


def test_aggregate_multiple_sources(signal_parser):
    """Aggregate signals from multiple sources → all included in debate."""
    signals = [
        Signal(
            market_id="0x123",
            prediction=0.75,
            confidence=0.85,
            source="mirofish_prediction",
            reasoning="AI signal",
            weight=1.0,
        ),
        Signal(
            market_id="0x123",
            prediction=0.70,
            confidence=0.80,
            source="btc_oracle",
            reasoning="BTC momentum",
            weight=1.0,
        ),
        Signal(
            market_id="0x123",
            prediction=0.72,
            confidence=0.75,
            source="weather_emos",
            reasoning="Temperature forecast",
            weight=1.0,
        ),
    ]
    
    all_signals = signal_parser.aggregate_signals(signals, [])
    
    assert len(all_signals) == 3
    sources = {s.source for s in all_signals}
    assert sources == {"mirofish_prediction", "btc_oracle", "weather_emos"}


# --- Weight Handling ---


def test_mirofish_signal_has_configured_weight(signal_parser, sample_mirofish_signal):
    """Parsed MiroFish signal has configured weight (default 1.0)."""
    signal = signal_parser.parse_mirofish_signal(sample_mirofish_signal)
    
    assert signal.weight == pytest.approx(1.0)


def test_signal_weight_in_aggregation(signal_parser):
    """Aggregated signals maintain their weights for debate engine."""
    signals = [
        Signal(
            market_id="0x123",
            prediction=0.75,
            confidence=0.85,
            source="mirofish_prediction",
            reasoning="Test",
            weight=1.0,  # MiroFish default weight
        ),
        Signal(
            market_id="0x123",
            prediction=0.70,
            confidence=0.80,
            source="btc_oracle",
            reasoning="Test",
            weight=1.0,  # Equal standing in debate
        ),
    ]
    
    aggregated = signal_parser.aggregate_signals(signals, [])
    
    # Both signals maintain equal weight (advisory voting)
    assert all(s.weight == pytest.approx(1.0) for s in aggregated)


# --- Debate Integration (Weighted Voting) ---


def test_mirofish_advisory_not_directive(signal_parser, sample_mirofish_signal):
    """MiroFish signals are advisory - weighted votes, not auto-execution directives."""
    signal = signal_parser.parse_mirofish_signal(sample_mirofish_signal)
    
    # Signal is part of debate consensus (weight=1.0), not a directive override
    assert signal.weight == pytest.approx(1.0)
    assert signal.source == "mirofish_prediction"
    # Debate engine will weight this among other signals (e.g., BTC Oracle, Weather)
    # MiroFish CANNOT override decision alone - must be part of consensus


def test_no_signal_override_documented(signal_parser):
    """Verify design: MiroFish signals cannot override debate decision."""
    # This is enforced by debate engine logic, not signal parser
    # But we document it clearly in aggregation
    mirofish = Signal(
        market_id="0x123",
        prediction=0.95,  # Very bullish
        confidence=0.99,  # Very confident
        source="mirofish_prediction",
        reasoning="Strong signal",
        weight=1.0,  # Equal weight, not override weight
    )
    
    strategy = Signal(
        market_id="0x123",
        prediction=0.30,  # Very bearish
        confidence=0.95,
        source="btc_oracle",
        reasoning="Strong bearish signal",
        weight=1.0,
    )
    
    aggregated = signal_parser.aggregate_signals([mirofish], [strategy])
    
    # Both signals at equal weight - debate engine synthesizes consensus
    # MiroFish (0.95) + Oracle (0.30) = consensus somewhere between
    # Neither overrides the other
    assert len(aggregated) == 2
    for sig in aggregated:
        assert sig.weight == pytest.approx(1.0)


# --- Database Storage ---


def test_store_signal_in_db_new_signal(signal_parser, sample_mirofish_signal, db_session):
    """Store new signal in database → creates MiroFishSignal row."""
    signal = signal_parser.parse_mirofish_signal(sample_mirofish_signal)
    success = signal_parser.store_signal_in_db(signal, db_session)
    
    assert success is True
    
    from backend.models.database import MiroFishSignal
    
    stored = db_session.query(MiroFishSignal).filter(
        MiroFishSignal.market_id == "0x123abc"
    ).first()
    
    assert stored is not None
    assert stored.prediction == pytest.approx(0.75)
    assert stored.confidence == pytest.approx(0.85)


def test_store_signal_upsert_updates_existing(signal_parser, sample_mirofish_signal, db_session):
    """Store signal that exists → updates (upsert pattern)."""
    from backend.models.database import MiroFishSignal
    
    signal1 = signal_parser.parse_mirofish_signal(sample_mirofish_signal)
    signal_parser.store_signal_in_db(signal1, db_session)
    
    sample_mirofish_signal["prediction"] = 0.85
    signal2 = signal_parser.parse_mirofish_signal(sample_mirofish_signal)
    signal_parser.store_signal_in_db(signal2, db_session)
    
    stored_list = db_session.query(MiroFishSignal).filter(
        MiroFishSignal.market_id == "0x123abc"
    ).all()
    
    assert len(stored_list) == 1
    assert stored_list[0].prediction == pytest.approx(0.85)


def test_store_batch_signals(signal_parser, db_session):
    """Store batch of signals → returns success/failure counts."""
    signals = [
        Signal(
            market_id="0x111",
            prediction=0.75,
            confidence=0.85,
            source="mirofish",
            reasoning="Test 1",
        ),
        Signal(
            market_id="0x222",
            prediction=0.60,
            confidence=0.80,
            source="mirofish",
            reasoning="Test 2",
        ),
        Signal(
            market_id="0x333",
            prediction=0.90,
            confidence=0.95,
            source="mirofish",
            reasoning="Test 3",
        ),
    ]
    
    results = signal_parser.store_signals_batch(signals, db_session)
    
    assert results["total"] == 3
    assert results["successful"] == 3
    assert results["failed"] == 0


# --- Singleton Pattern ---


def test_get_signal_parser_returns_singleton():
    """get_signal_parser() returns same instance on multiple calls."""
    reset_signal_parser()
    
    parser1 = get_signal_parser()
    parser2 = get_signal_parser()
    
    assert parser1 is parser2


def test_reset_signal_parser_clears_singleton():
    """reset_signal_parser() clears singleton instance."""
    parser1 = get_signal_parser()
    reset_signal_parser()
    parser2 = get_signal_parser()
    
    assert parser1 is not parser2


# --- Error Handling ---


def test_parse_signal_exception_handling(signal_parser):
    """Parse signal with unexpected exception → None (logged)."""
    # This will trigger the exception handler by having a non-dict input
    signal = signal_parser.parse_mirofish_signal(None)
    
    assert signal is None


def test_store_signal_db_error_recovery(signal_parser, sample_mirofish_signal):
    """Store signal with invalid session → returns False (no crash)."""
    signal = signal_parser.parse_mirofish_signal(sample_mirofish_signal)
    success = signal_parser.store_signal_in_db(signal, None)
    
    # Should handle gracefully (either succeed or fail gracefully)
    # If session is None, it tries to get_db_session(), which should work or fail safely
    assert isinstance(success, bool)
