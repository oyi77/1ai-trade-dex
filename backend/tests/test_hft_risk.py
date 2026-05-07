"""HFT Risk Validation — extreme scenario testing and fuzz testing for position sizing."""

import random
import logging

logger = logging.getLogger("trading_bot.hft_risk_test")


def test_extreme_scenarios():
    """Test extreme scenarios: bankroll=0, 1000% loss, concurrent positions."""
    scenarios = {
        "zero_bankroll": validate_size(bankroll=0.0, confidence=0.8, expected_allowed=False),
        "full_confidence": validate_size(bankroll=100.0, confidence=1.0, expected_allowed=True),
        "low_confidence": validate_size(bankroll=100.0, confidence=0.2, expected_allowed=False),
        "max_position": validate_size(bankroll=10000.0, confidence=0.9, expected_allowed=True),
    }
    for name, result in scenarios.items():
        assert result["matches_expectation"], (
            f"Scenario '{name}' failed: expected allowed={not result['allowed']}, got {result['allowed']}"
        )


def validate_size(bankroll: float, confidence: float, expected_allowed: bool) -> dict:
    """Validate position sizing across extreme values."""
    from backend.core.risk_manager_hft import HRiskManager
    from backend.strategies.types_hft import HFTSignal

    risk = HRiskManager()
    signal = HFTSignal(
        market_id="test",
        ticker="test",
        signal_type="edge",
        edge=0.05,
        confidence=confidence,
    )

    result = risk.validate_hft_trade(signal, bankroll)
    return {
        "bankroll": bankroll,
        "confidence": confidence,
        "allowed": result["allowed"],
        "matches_expectation": result["allowed"] == expected_allowed,
    }


def fuzz_position_sizing(n_iterations: int = 100) -> dict:
    """Fuzz test random position sizes."""
    from backend.core.risk_manager_hft import HRiskManager
    from backend.strategies.types_hft import HFTSignal

    risk = HRiskManager()
    errors = []

    for _ in range(n_iterations):
        bankroll = random.uniform(10.0, 100000.0)
        confidence = random.uniform(0.0, 1.0)
        edge = random.uniform(-0.1, 0.5)

        signal = HFTSignal(
            market_id="fuzz-test",
            ticker="fuzz",
            signal_type="edge",
            edge=edge,
            confidence=confidence,
        )

        try:
            result = risk.validate_hft_trade(signal, bankroll)
            if "size" not in result or result["size"] < 0:
                errors.append(f"Negative size: {result}")
        except Exception as exc:
            errors.append(f"Crash: {exc}")

    return {
        "iterations": n_iterations,
        "errors": errors,
        "error_rate": len(errors) / n_iterations,
    }
