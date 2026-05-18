"""Request validation models for all API endpoints.

Provides Pydantic models with comprehensive validation for:
- Trade creation
- Signal creation
- Strategy configuration
- Wallet management
- Backtest parameters
- Proposal creation

All models include:
- Field-level validation (types, ranges, patterns)
- Input sanitization (HTML stripping, length limits)
- Clear error messages for validation failures
"""

import re
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, field_validator, model_validator
from enum import Enum
import html


# ============================================================================
# Enums for Validation
# ============================================================================


class TradingMode(str, Enum):
    """Valid trading modes."""
    paper = "paper"
    testnet = "testnet"
    live = "live"


class TradeDirection(str, Enum):
    """Valid trade directions."""
    YES = "YES"
    NO = "NO"
    UP = "UP"
    DOWN = "DOWN"


class Platform(str, Enum):
    """Valid trading platforms."""
    polymarket = "polymarket"
    kalshi = "kalshi"


# ============================================================================
# Validation Utilities
# ============================================================================


def sanitize_string(value: str, max_length: int = 10000) -> str:
    """Sanitize string input by escaping HTML and limiting length."""
    if not value:
        return value
    # Escape HTML entities
    sanitized = html.escape(value.strip())
    # Limit length
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length]
    return sanitized


def validate_ethereum_address(address: str) -> str:
    """Validate Ethereum address format."""
    if not re.match(r'^0x[a-fA-F0-9]{40}$', address):
        raise ValueError('Invalid Ethereum address format')
    return address.lower()


# ============================================================================
# Trade Validation Models
# ============================================================================


class TradeCreateRequest(BaseModel):
    """Request model for creating a new trade."""

    market_ticker: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Market identifier or ticker symbol"
    )
    platform: Platform = Field(
        default=Platform.polymarket,
        description="Trading platform"
    )
    direction: TradeDirection = Field(
        ...,
        description="Trade direction (YES/NO or UP/DOWN)"
    )
    amount: float = Field(
        ...,
        gt=0,
        le=1000000,
        description="Trade amount in USD (must be positive, max $1M)"
    )
    price: Optional[float] = Field(
        None,
        ge=0.01,
        le=0.99,
        description="Limit price (0.01-0.99), None for market order"
    )
    strategy_name: Optional[str] = Field(
        None,
        max_length=100,
        description="Strategy that generated this trade"
    )
    confidence: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Signal confidence (0.0-1.0)"
    )
    reasoning: Optional[str] = Field(
        None,
        max_length=5000,
        description="Trade reasoning or notes"
    )

    @field_validator('market_ticker', 'strategy_name', 'reasoning')
    @classmethod
    def sanitize_text_fields(cls, v: Optional[str]) -> Optional[str]:
        """Sanitize text fields to prevent XSS."""
        if v is None:
            return v
        return sanitize_string(v)

    @model_validator(mode='after')
    def validate_price_for_direction(self):
        """Ensure price is reasonable for the direction."""
        if self.price is not None:
            if self.direction in [TradeDirection.YES, TradeDirection.UP]:
                if self.price < 0.01:
                    raise ValueError('Price too low for YES/UP direction')
            elif self.direction in [TradeDirection.NO, TradeDirection.DOWN]:
                if self.price > 0.99:
                    raise ValueError('Price too high for NO/DOWN direction')
        return self


# ============================================================================
# Signal Validation Models
# ============================================================================


class SignalCreateRequest(BaseModel):
    """Request model for creating a trading signal."""

    market_id: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Market identifier"
    )
    prediction: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Predicted probability (0.0-1.0)"
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Signal confidence (0.0-1.0)"
    )
    reasoning: str = Field(
        ...,
        min_length=10,
        max_length=5000,
        description="Signal reasoning (10-5000 chars)"
    )
    source: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Signal source (strategy name or AI model)"
    )
    weight: float = Field(
        default=1.0,
        ge=0.0,
        le=10.0,
        description="Signal weight for ensemble (0.0-10.0)"
    )

    @field_validator('market_id', 'reasoning', 'source')
    @classmethod
    def sanitize_text_fields(cls, v: str) -> str:
        """Sanitize text fields to prevent XSS."""
        return sanitize_string(v)

    @model_validator(mode='after')
    def validate_confidence_prediction_relationship(self):
        """Ensure confidence is reasonable given prediction."""
        # High confidence should not be given to extreme predictions without good reason
        if self.confidence > 0.9 and (self.prediction < 0.1 or self.prediction > 0.9):
            # This is allowed but we validate the reasoning is substantial
            if len(self.reasoning.strip()) < 50:
                raise ValueError(
                    'High confidence extreme predictions require detailed reasoning (min 50 chars)'
                )
        return self


# ============================================================================
# Strategy Configuration Validation Models
# ============================================================================


class StrategyConfigRequest(BaseModel):
    """Request model for updating strategy configuration."""

    enabled: Optional[bool] = Field(
        None,
        description="Enable or disable the strategy"
    )
    interval_seconds: Optional[int] = Field(
        None,
        ge=10,
        le=86400,
        description="Strategy execution interval (10s - 24h)"
    )
    trading_mode: Optional[TradingMode] = Field(
        None,
        description="Trading mode override for this strategy"
    )
    params: Optional[Dict[str, Any]] = Field(
        None,
        description="Strategy-specific parameters"
    )

    @field_validator('params')
    @classmethod
    def validate_params(cls, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Validate and sanitize strategy parameters."""
        if v is None:
            return v

        # Limit nested depth to prevent DoS
        def check_depth(obj, depth=0):
            if depth > 5:
                raise ValueError('Parameter nesting too deep (max 5 levels)')
            if isinstance(obj, dict):
                for value in obj.values():
                    check_depth(value, depth + 1)
            elif isinstance(obj, list):
                for item in obj:
                    check_depth(item, depth + 1)

        check_depth(v)

        # Sanitize string values
        def sanitize_dict(obj):
            if isinstance(obj, dict):
                return {k: sanitize_dict(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [sanitize_dict(item) for item in obj]
            elif isinstance(obj, str):
                return sanitize_string(obj, max_length=1000)
            return obj

        return sanitize_dict(v)


# ============================================================================
# Wallet Validation Models
# ============================================================================


class WalletConfigCreateRequest(BaseModel):
    """Request model for creating wallet configuration."""

    address: str = Field(
        ...,
        min_length=42,
        max_length=42,
        description="Ethereum wallet address (0x...)"
    )
    pseudonym: Optional[str] = Field(
        None,
        max_length=100,
        description="Wallet nickname"
    )
    source: Optional[str] = Field(
        default="user",
        max_length=50,
        description="Wallet source (user, imported, generated)"
    )
    tags: Optional[List[str]] = Field(
        None,
        max_length=20,
        description="Wallet tags (max 20)"
    )
    enabled: Optional[bool] = Field(
        default=True,
        description="Enable wallet for trading"
    )

    @field_validator('address')
    @classmethod
    def validate_address(cls, v: str) -> str:
        """Validate Ethereum address format."""
        return validate_ethereum_address(v)

    @field_validator('pseudonym', 'source')
    @classmethod
    def sanitize_text_fields(cls, v: Optional[str]) -> Optional[str]:
        """Sanitize text fields."""
        if v is None:
            return v
        return sanitize_string(v, max_length=100)

    @field_validator('tags')
    @classmethod
    def validate_tags(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """Validate and sanitize tags."""
        if v is None:
            return v
        if len(v) > 20:
            raise ValueError('Maximum 20 tags allowed')
        return [sanitize_string(tag, max_length=50) for tag in v if tag.strip()]


class WalletConfigUpdateRequest(BaseModel):
    """Request model for updating wallet configuration."""

    pseudonym: Optional[str] = Field(
        None,
        max_length=100,
        description="Wallet nickname"
    )
    tags: Optional[List[str]] = Field(
        None,
        max_length=20,
        description="Wallet tags"
    )
    enabled: Optional[bool] = Field(
        None,
        description="Enable/disable wallet"
    )
    notes: Optional[str] = Field(
        None,
        max_length=2000,
        description="Wallet notes"
    )

    @field_validator('pseudonym', 'notes')
    @classmethod
    def sanitize_text_fields(cls, v: Optional[str], info) -> Optional[str]:
        """Sanitize text fields."""
        if v is None:
            return v
        max_len = 2000 if info.field_name == 'notes' else 100
        return sanitize_string(v, max_length=max_len)

    @field_validator('tags')
    @classmethod
    def validate_tags(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """Validate and sanitize tags."""
        if v is None:
            return v
        if len(v) > 20:
            raise ValueError('Maximum 20 tags allowed')
        return [sanitize_string(tag, max_length=50) for tag in v if tag.strip()]


# ============================================================================
# Backtest Validation Models
# ============================================================================


class BacktestRunRequest(BaseModel):
    """Request model for running a backtest."""

    strategy_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Strategy to backtest"
    )
    start_date: Optional[str] = Field(
        None,
        description="Backtest start date (ISO format)"
    )
    end_date: Optional[str] = Field(
        None,
        description="Backtest end date (ISO format)"
    )
    initial_bankroll: float = Field(
        default=10000.0,
        gt=0,
        le=10000000,
        description="Initial bankroll ($0-$10M)"
    )
    kelly_fraction: float = Field(
        default=0.25,
        ge=0.01,
        le=1.0,
        description="Kelly fraction (0.01-1.0)"
    )
    max_trade_size: float = Field(
        default=1000.0,
        gt=0,
        le=100000,
        description="Max trade size ($0-$100K)"
    )
    max_position_fraction: float = Field(
        default=0.1,
        ge=0.01,
        le=1.0,
        description="Max position as fraction of bankroll (0.01-1.0)"
    )
    max_total_exposure: float = Field(
        default=0.5,
        ge=0.01,
        le=1.0,
        description="Max total exposure as fraction of bankroll (0.01-1.0)"
    )
    daily_loss_limit: float = Field(
        default=500.0,
        gt=0,
        le=100000,
        description="Daily loss limit ($0-$100K)"
    )

    @field_validator('strategy_name')
    @classmethod
    def sanitize_strategy_name(cls, v: str) -> str:
        """Sanitize strategy name."""
        return sanitize_string(v, max_length=100)

    @field_validator('start_date', 'end_date')
    @classmethod
    def validate_dates(cls, v: Optional[str]) -> Optional[str]:
        """Validate date format."""
        if v is None:
            return v
        try:
            datetime.fromisoformat(v.replace('Z', '+00:00'))
        except ValueError:
            raise ValueError('Invalid date format. Use ISO 8601 format (YYYY-MM-DDTHH:MM:SS)')
        return v

    @model_validator(mode='after')
    def validate_date_range(self):
        """Ensure start_date is before end_date."""
        if self.start_date and self.end_date:
            start = datetime.fromisoformat(self.start_date.replace('Z', '+00:00'))
            end = datetime.fromisoformat(self.end_date.replace('Z', '+00:00'))
            if start >= end:
                raise ValueError('start_date must be before end_date')
        return self


# ============================================================================
# Proposal Validation Models
# ============================================================================


class ProposalCreateRequest(BaseModel):
    """Request model for creating a strategy proposal."""

    strategy_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Strategy name"
    )
    change_details: Dict[str, Any] = Field(
        ...,
        description="Proposed configuration changes"
    )
    expected_impact: float = Field(
        ...,
        ge=-1.0,
        le=1.0,
        description="Expected impact on performance (-1.0 to 1.0)"
    )

    @field_validator('strategy_name')
    @classmethod
    def sanitize_strategy_name(cls, v: str) -> str:
        """Sanitize strategy name."""
        return sanitize_string(v, max_length=100)

    @field_validator('change_details')
    @classmethod
    def validate_change_details(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and sanitize change details."""
        if not v:
            raise ValueError('change_details cannot be empty')

        # Limit nested depth
        def check_depth(obj, depth=0):
            if depth > 5:
                raise ValueError('Change details nesting too deep (max 5 levels)')
            if isinstance(obj, dict):
                for value in obj.values():
                    check_depth(value, depth + 1)
            elif isinstance(obj, list):
                for item in obj:
                    check_depth(item, depth + 1)

        check_depth(v)

        # Sanitize string values
        def sanitize_dict(obj):
            if isinstance(obj, dict):
                return {k: sanitize_dict(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [sanitize_dict(item) for item in obj]
            elif isinstance(obj, str):
                return sanitize_string(obj, max_length=1000)
            return obj

        return sanitize_dict(v)


class ProposalApprovalRequest(BaseModel):
    """Request model for approving/rejecting a proposal."""

    admin_user_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Admin user identifier"
    )
    reason: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Approval/rejection reason"
    )

    @field_validator('admin_user_id', 'reason')
    @classmethod
    def sanitize_text_fields(cls, v: str) -> str:
        """Sanitize text fields."""
        sanitized = sanitize_string(v, max_length=2000)
        if not sanitized.strip():
            raise ValueError('Field cannot be empty or whitespace only')
        return sanitized


# ============================================================================
# Auth Validation Models
# ============================================================================


class CredentialsUpdateRequest(BaseModel):
    """Request model for updating trading credentials."""

    private_key: Optional[str] = Field(
        None,
        min_length=64,
        max_length=66,
        description="Private key (64-66 hex chars)"
    )
    api_key: Optional[str] = Field(
        None,
        max_length=500,
        description="API key"
    )
    api_secret: Optional[str] = Field(
        None,
        max_length=500,
        description="API secret"
    )
    api_passphrase: Optional[str] = Field(
        None,
        max_length=500,
        description="API passphrase"
    )

    @field_validator('private_key')
    @classmethod
    def validate_private_key(cls, v: Optional[str]) -> Optional[str]:
        """Validate private key format."""
        if v is None:
            return v
        # Remove 0x prefix if present
        key = v.strip()
        if key.startswith('0x'):
            key = key[2:]
        # Validate hex format
        if not re.match(r'^[a-fA-F0-9]{64}$', key):
            raise ValueError('Invalid private key format (must be 64 hex characters)')
        return '0x' + key.lower()

    @model_validator(mode='after')
    def validate_at_least_one_field(self):
        """Ensure at least one credential field is provided."""
        if not any([
            self.private_key,
            self.api_key,
            self.api_secret,
            self.api_passphrase
        ]):
            raise ValueError('At least one credential field must be provided')
        return self
