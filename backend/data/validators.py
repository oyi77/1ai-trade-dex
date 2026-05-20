"""
Pydantic v2 validation models for external API responses.

Validates data from Polymarket Gamma API, CLOB order book, Coinbase klines,
and OpenMeteo forecasts before downstream processing.
"""

import time
from typing import Union

from pydantic import BaseModel, field_validator, model_validator

# =============================================================================
# Shared sub-models
# =============================================================================


class OrderLevel(BaseModel):
    price: str
    size: str

    @field_validator("price")
    @classmethod
    def price_in_range(cls, v: str) -> str:
        try:
            f = float(v)
        except (ValueError, TypeError):
            raise ValueError(f"price '{v}' is not a valid float")
        if not (0.0 <= f <= 1.0):
            raise ValueError(f"price {f} is not in range [0.0, 1.0]")
        return v

    @field_validator("size")
    @classmethod
    def size_positive(cls, v: str) -> str:
        try:
            f = float(v)
        except (ValueError, TypeError):
            raise ValueError(f"size '{v}' is not a valid float")
        if f <= 0.0:
            raise ValueError(f"size {f} must be > 0")
        return v


class HourlyData(BaseModel):
    time: list[str]
    temperature_2m: list[float]

    @field_validator("temperature_2m")
    @classmethod
    def temperatures_in_range(cls, v: list[float]) -> list[float]:
        for temp in v:
            if not (-80.0 <= temp <= 60.0):
                raise ValueError(
                    f"temperature {temp} is out of range [-80, 60] Celsius"
                )
        return v

    @model_validator(mode="after")
    def lists_same_length(self) -> "HourlyData":
        if len(self.time) != len(self.temperature_2m):
            raise ValueError(
                f"time length ({len(self.time)}) does not match "
                f"temperature_2m length ({len(self.temperature_2m)})"
            )
        return self


# =============================================================================
# API Response Models
# =============================================================================


class GammaMarketResponse(BaseModel):
    id: Union[int, str]
    question: str
    outcomes: list[str]
    outcomePrices: list[str]
    volume: float
    active: bool
    closed: bool
    slug: str | None = None
    conditionId: str | None = None
    endDate: str | None = None

    @field_validator("outcomes")
    @classmethod
    def outcomes_min_two(cls, v: list[str]) -> list[str]:
        if len(v) < 2:
            raise ValueError(f"outcomes must have at least 2 items, got {len(v)}")
        return v

    @field_validator("outcomePrices")
    @classmethod
    def prices_valid(cls, v: list[str]) -> list[str]:
        for raw in v:
            try:
                f = float(raw)
            except (ValueError, TypeError):
                raise ValueError(f"outcomePrices value '{raw}' is not a valid float")
            if not (0.0 <= f <= 1.0):
                raise ValueError(f"outcomePrices value {f} is not in range [0.0, 1.0]")
        return v

    @field_validator("volume")
    @classmethod
    def volume_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError(f"volume {v} must be >= 0")
        return v


class CLOBOrderBookResponse(BaseModel):
    bids: list[OrderLevel]
    asks: list[OrderLevel]
    timestamp: int | None = None


class CoinbaseKlineResponse(BaseModel):
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    @field_validator("open", "high", "low", "close")
    @classmethod
    def prices_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"OHLC price {v} must be > 0")
        return v

    @field_validator("volume")
    @classmethod
    def volume_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError(f"volume {v} must be >= 0")
        return v

    @model_validator(mode="after")
    def ohlc_consistency(self) -> "CoinbaseKlineResponse":
        errors = []
        if self.high < self.low:
            errors.append(f"high ({self.high}) must be >= low ({self.low})")
        if self.high < self.open:
            errors.append(f"high ({self.high}) must be >= open ({self.open})")
        if self.high < self.close:
            errors.append(f"high ({self.high}) must be >= close ({self.close})")
        if self.low > self.open:
            errors.append(f"low ({self.low}) must be <= open ({self.open})")
        if self.low > self.close:
            errors.append(f"low ({self.low}) must be <= close ({self.close})")
        if errors:
            raise ValueError("; ".join(errors))
        return self

    @model_validator(mode="after")
    def timestamp_in_past(self) -> "CoinbaseKlineResponse":
        cutoff = int(time.time()) + 60
        if self.timestamp >= cutoff:
            raise ValueError(
                f"timestamp {self.timestamp} is not in the past (cutoff {cutoff})"
            )
        return self


class OpenMeteoForecastResponse(BaseModel):
    hourly: HourlyData


# =============================================================================
# Helper
# =============================================================================


def validate_response(model_class, data: dict, source: str = "unknown"):
    """
    Validate *data* against *model_class*.

    Raises DataQualityError (or ValueError as fallback) on validation failure.
    Returns the validated model instance on success.
    """
    from pydantic import ValidationError

    try:
        return model_class.model_validate(data)
    except ValidationError as exc:
        field_errors = {
            ".".join(str(loc) for loc in err["loc"]): err["msg"] for err in exc.errors()
        }
        details = {"source": source, "field_errors": field_errors}
        message = (
            f"Validation failed for {model_class.__name__} from '{source}': "
            f"{len(field_errors)} field error(s)"
        )

        try:
            from backend.core.errors import DataQualityError

            raise DataQualityError(message, details=details)
        except ImportError:
            raise ValueError(f"{message} — {field_errors}")
