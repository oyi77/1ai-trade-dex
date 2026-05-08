import logging
from typing import Optional, Dict, Any
from datetime import datetime, timezone

from backend.config import settings

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    def __init__(self, message: str, field: str = None, value: Any = None):
        self.message = message
        self.field = field
        self.value = value
        super().__init__(message)


class TradeValidator:

    @staticmethod
    def validate_trade_amount(size: float, field_name: str = "size") -> None:
        if size <= 0:
            raise ValidationError(
                f"Trade {field_name} must be positive, got {size}",
                field=field_name,
                value=size
            )

        max_size = settings.MAX_TRADE_SIZE
        if size > max_size:
            raise ValidationError(
                f"Trade {field_name} {size} exceeds max position size {max_size}",
                field=field_name,
                value=size
            )

    @staticmethod
    def validate_confidence(confidence: Optional[float], field_name: str = "confidence") -> None:
        if confidence is None:
            return

        if not (0 <= confidence <= 1):
            raise ValidationError(
                f"{field_name} must be in range [0, 1], got {confidence}",
                field=field_name,
                value=confidence
            )

    @staticmethod
    def validate_price(price: float, field_name: str = "price") -> None:
        if not (0.01 <= price <= 0.99):
            raise ValidationError(
                f"{field_name} must be in range [0.01, 0.99], got {price}",
                field=field_name,
                value=price
            )

    @staticmethod
    def validate_probability(prob: float, field_name: str = "probability") -> None:
        if not (0 <= prob <= 1):
            raise ValidationError(
                f"{field_name} must be in range [0, 1], got {prob}",
                field=field_name,
                value=prob
            )

    @staticmethod
    def validate_edge(edge: float, field_name: str = "edge") -> None:
        if not (-1 <= edge <= 1):
            raise ValidationError(
                f"{field_name} must be in range [-1, 1], got {edge}",
                field=field_name,
                value=edge
            )

    @staticmethod
    def validate_direction(direction: str, field_name: str = "direction") -> None:
        valid_directions = {"up", "down", "yes", "no", "YES", "NO"}
        if direction not in valid_directions:
            raise ValidationError(
                f"{field_name} must be one of {valid_directions}, got '{direction}'",
                field=field_name,
                value=direction
            )

    @staticmethod
    def validate_trading_mode(mode: str, field_name: str = "trading_mode") -> None:
        valid_modes = {"paper", "testnet", "live"}
        if mode not in valid_modes:
            raise ValidationError(
                f"{field_name} must be one of {valid_modes}, got '{mode}'",
                field=field_name,
                value=mode
            )

    @staticmethod
    def validate_result(result: str, field_name: str = "result") -> None:
        valid_results = {"pending", "win", "loss", "expired", "push", "closed"}
        if result not in valid_results:
            raise ValidationError(
                f"{field_name} must be one of {valid_results}, got '{result}'",
                field=field_name,
                value=result
            )

    @staticmethod
    def validate_kelly_fraction(kelly: float, field_name: str = "kelly_fraction") -> None:
        if not (0 <= kelly <= 1):
            raise ValidationError(
                f"{field_name} must be in range [0, 1], got {kelly}",
                field=field_name,
                value=kelly
            )

    @classmethod
    def validate_trade_data(cls, data: Dict[str, Any]) -> None:
        if "size" in data:
            cls.validate_trade_amount(data["size"], "size")

        if "entry_price" in data:
            cls.validate_price(data["entry_price"], "entry_price")

        if "market_price_at_entry" in data:
            cls.validate_price(data["market_price_at_entry"], "market_price_at_entry")

        if "confidence" in data and data["confidence"] is not None:
            cls.validate_confidence(data["confidence"], "confidence")

        if "model_probability" in data:
            cls.validate_probability(data["model_probability"], "model_probability")

        if "edge_at_entry" in data:
            cls.validate_edge(data["edge_at_entry"], "edge_at_entry")

        if "direction" in data:
            cls.validate_direction(data["direction"], "direction")

        if "trading_mode" in data:
            cls.validate_trading_mode(data["trading_mode"], "trading_mode")

        if "result" in data:
            cls.validate_result(data["result"], "result")


class SignalValidator:

    @classmethod
    def validate_signal_data(cls, data: Dict[str, Any]) -> None:
        if "confidence" in data:
            TradeValidator.validate_confidence(data["confidence"], "confidence")

        if "model_probability" in data:
            TradeValidator.validate_probability(data["model_probability"], "model_probability")

        if "market_price" in data:
            TradeValidator.validate_price(data["market_price"], "market_price")

        if "edge" in data:
            TradeValidator.validate_edge(data["edge"], "edge")

        if "kelly_fraction" in data:
            TradeValidator.validate_kelly_fraction(data["kelly_fraction"], "kelly_fraction")

        if "suggested_size" in data:
            if data["suggested_size"] <= 0:
                raise ValidationError(
                    f"suggested_size must be positive, got {data['suggested_size']}",
                    field="suggested_size",
                    value=data["suggested_size"]
                )

        if "direction" in data:
            TradeValidator.validate_direction(data["direction"], "direction")


class ApprovalValidator:

    @classmethod
    def validate_approval_data(cls, data: Dict[str, Any]) -> None:
        if "size" in data:
            TradeValidator.validate_trade_amount(data["size"], "size")

        if "confidence" in data:
            TradeValidator.validate_confidence(data["confidence"], "confidence")

        if "status" in data:
            valid_statuses = {"pending", "approved", "rejected"}
            if data["status"] not in valid_statuses:
                raise ValidationError(
                    f"status must be one of {valid_statuses}, got '{data['status']}'",
                    field="status",
                    value=data["status"]
                )


def log_validation_error(error: ValidationError, context: str = "") -> None:
    log_msg = f"Validation error in {context}: {error.message}"
    if error.field:
        log_msg += f" (field: {error.field})"
    if error.value is not None:
        log_msg += f" (value: {error.value})"

    logger.error(log_msg, extra={
        "validation_error": True,
        "field": error.field,
        "value": error.value,
        "context": context,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
