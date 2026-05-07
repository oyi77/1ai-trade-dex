import pytest
from backend.core.validation import (
    TradeValidator,
    SignalValidator,
    ApprovalValidator,
    ValidationError,
    log_validation_error,
)


class TestTradeValidator:

    def test_validate_trade_amount_positive(self):
        TradeValidator.validate_trade_amount(2.0)
        TradeValidator.validate_trade_amount(0.01)

    def test_validate_trade_amount_zero_fails(self):
        with pytest.raises(ValidationError) as exc:
            TradeValidator.validate_trade_amount(0.0)
        assert "must be positive" in exc.value.message
        assert exc.value.field == "size"

    def test_validate_trade_amount_negative_fails(self):
        with pytest.raises(ValidationError) as exc:
            TradeValidator.validate_trade_amount(-5.0)
        assert "must be positive" in exc.value.message

    def test_validate_trade_amount_exceeds_max(self):
        with pytest.raises(ValidationError) as exc:
            TradeValidator.validate_trade_amount(1001.0)
        assert "exceeds max position size" in exc.value.message

    def test_validate_confidence_valid_range(self):
        TradeValidator.validate_confidence(0.0)
        TradeValidator.validate_confidence(0.5)
        TradeValidator.validate_confidence(1.0)
        TradeValidator.validate_confidence(None)

    def test_validate_confidence_out_of_range(self):
        with pytest.raises(ValidationError) as exc:
            TradeValidator.validate_confidence(1.5)
        assert "must be in range [0, 1]" in exc.value.message

        with pytest.raises(ValidationError) as exc:
            TradeValidator.validate_confidence(-0.1)
        assert "must be in range [0, 1]" in exc.value.message

    def test_validate_price_valid_range(self):
        TradeValidator.validate_price(0.01)
        TradeValidator.validate_price(0.5)
        TradeValidator.validate_price(0.99)

    def test_validate_price_out_of_range(self):
        with pytest.raises(ValidationError) as exc:
            TradeValidator.validate_price(0.005)
        assert "must be in range [0.01, 0.99]" in exc.value.message

        with pytest.raises(ValidationError) as exc:
            TradeValidator.validate_price(1.0)
        assert "must be in range [0.01, 0.99]" in exc.value.message

    def test_validate_probability_valid_range(self):
        TradeValidator.validate_probability(0.0)
        TradeValidator.validate_probability(0.5)
        TradeValidator.validate_probability(1.0)

    def test_validate_probability_out_of_range(self):
        with pytest.raises(ValidationError) as exc:
            TradeValidator.validate_probability(1.1)
        assert "must be in range [0, 1]" in exc.value.message

    def test_validate_edge_valid_range(self):
        TradeValidator.validate_edge(-1.0)
        TradeValidator.validate_edge(0.0)
        TradeValidator.validate_edge(1.0)

    def test_validate_edge_out_of_range(self):
        with pytest.raises(ValidationError) as exc:
            TradeValidator.validate_edge(1.5)
        assert "must be in range [-1, 1]" in exc.value.message

        with pytest.raises(ValidationError) as exc:
            TradeValidator.validate_edge(-1.5)
        assert "must be in range [-1, 1]" in exc.value.message

    def test_validate_direction_valid(self):
        for direction in ["up", "down", "yes", "no", "YES", "NO"]:
            TradeValidator.validate_direction(direction)

    def test_validate_direction_invalid(self):
        with pytest.raises(ValidationError) as exc:
            TradeValidator.validate_direction("invalid")
        assert "must be one of" in exc.value.message

    def test_validate_trading_mode_valid(self):
        for mode in ["paper", "testnet", "live"]:
            TradeValidator.validate_trading_mode(mode)

    def test_validate_trading_mode_invalid(self):
        with pytest.raises(ValidationError) as exc:
            TradeValidator.validate_trading_mode("production")
        assert "must be one of" in exc.value.message

    def test_validate_result_valid(self):
        for result in ["pending", "win", "loss", "expired", "push", "closed"]:
            TradeValidator.validate_result(result)

    def test_validate_result_invalid(self):
        with pytest.raises(ValidationError) as exc:
            TradeValidator.validate_result("unknown")
        assert "must be one of" in exc.value.message

    def test_validate_trade_data_valid(self):
        data = {
            "size": 2.0,
            "entry_price": 0.65,
            "market_price_at_entry": 0.60,
            "confidence": 0.75,
            "model_probability": 0.70,
            "edge_at_entry": 0.05,
            "direction": "up",
            "trading_mode": "paper",
            "result": "pending",
        }
        TradeValidator.validate_trade_data(data)

    def test_validate_trade_data_invalid_size(self):
        data = {"size": -5.0}
        with pytest.raises(ValidationError) as exc:
            TradeValidator.validate_trade_data(data)
        assert "must be positive" in exc.value.message

    def test_validate_trade_data_invalid_price(self):
        data = {"entry_price": 1.5}
        with pytest.raises(ValidationError) as exc:
            TradeValidator.validate_trade_data(data)
        assert "must be in range [0.01, 0.99]" in exc.value.message

    def test_validate_trade_data_invalid_confidence(self):
        data = {"confidence": 2.0}
        with pytest.raises(ValidationError) as exc:
            TradeValidator.validate_trade_data(data)
        assert "must be in range [0, 1]" in exc.value.message


class TestSignalValidator:

    def test_validate_signal_data_valid(self):
        data = {
            "confidence": 0.8,
            "model_probability": 0.75,
            "market_price": 0.65,
            "edge": 0.10,
            "kelly_fraction": 0.05,
            "suggested_size": 10.0,
            "direction": "up",
        }
        SignalValidator.validate_signal_data(data)

    def test_validate_signal_data_invalid_confidence(self):
        data = {"confidence": 1.5}
        with pytest.raises(ValidationError) as exc:
            SignalValidator.validate_signal_data(data)
        assert "must be in range [0, 1]" in exc.value.message

    def test_validate_signal_data_invalid_suggested_size(self):
        data = {"suggested_size": -10.0}
        with pytest.raises(ValidationError) as exc:
            SignalValidator.validate_signal_data(data)
        assert "must be positive" in exc.value.message

    def test_validate_signal_data_zero_suggested_size(self):
        data = {"suggested_size": 0.0}
        with pytest.raises(ValidationError) as exc:
            SignalValidator.validate_signal_data(data)
        assert "must be positive" in exc.value.message


class TestApprovalValidator:

    def test_validate_approval_data_valid(self):
        data = {
            "size": 2.0,
            "confidence": 0.8,
            "status": "pending",
        }
        ApprovalValidator.validate_approval_data(data)

    def test_validate_approval_data_invalid_status(self):
        data = {"status": "unknown"}
        with pytest.raises(ValidationError) as exc:
            ApprovalValidator.validate_approval_data(data)
        assert "must be one of" in exc.value.message

    def test_validate_approval_data_invalid_size(self):
        data = {"size": 0.0}
        with pytest.raises(ValidationError) as exc:
            ApprovalValidator.validate_approval_data(data)
        assert "must be positive" in exc.value.message


class TestValidationErrorLogging:

    def test_log_validation_error(self, caplog):
        error = ValidationError("Test error", field="test_field", value=123)
        log_validation_error(error, context="test_context")

        assert "Validation error in test_context" in caplog.text
        assert "test_field" in caplog.text


class TestDatabaseConstraintValidation:

    def test_trade_constraints_match_validator(self):
        valid_data = {
            "size": 2.0,
            "entry_price": 0.65,
            "confidence": 0.75,
            "model_probability": 0.70,
            "edge_at_entry": 0.05,
            "direction": "up",
            "trading_mode": "paper",
        }
        TradeValidator.validate_trade_data(valid_data)

        invalid_data = {
            "size": -5.0,
            "entry_price": 1.5,
            "confidence": 2.0,
        }
        with pytest.raises(ValidationError):
            TradeValidator.validate_trade_data(invalid_data)

    def test_signal_constraints_match_validator(self):
        valid_data = {
            "confidence": 0.8,
            "model_probability": 0.75,
            "market_price": 0.65,
            "edge": 0.10,
            "kelly_fraction": 0.05,
            "suggested_size": 10.0,
        }
        SignalValidator.validate_signal_data(valid_data)

        invalid_data = {
            "confidence": 1.5,
            "suggested_size": -10.0,
        }
        with pytest.raises(ValidationError):
            SignalValidator.validate_signal_data(invalid_data)
