"""Normalized order types for the market provider plugin system."""
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any


class OrderSide(str, Enum):
    YES = "yes"
    NO = "no"
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    FOK = "fill_or_kill"
    IOC = "immediate_or_cancel"


class OrderStatus(str, Enum):
    PENDING = "pending"
    OPEN = "open"
    PARTIAL = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class PositionSide(str, Enum):
    LONG = "long"
    SHORT = "short"


class VenueCapability(str, Enum):
    LIMIT_ORDERS = "limit_orders"
    MARKET_ORDERS = "market_orders"
    FOK_ORDERS = "fok_orders"
    SHORT_SELLING = "short_selling"
    STREAMING_FILLS = "streaming_fills"
    MARKET_SEARCH = "market_search"
    BATCH_ORDERS = "batch_orders"


@dataclass
class NormalizedOrder:
    """Venue-agnostic order request. Strategies create these."""
    market_id: str
    side: OrderSide
    order_type: OrderType
    size: Decimal
    price: Decimal | None = None
    client_order_id: str | None = None
    time_in_force_seconds: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class NormalizedOrderResult:
    """Venue-agnostic result returned after order submission."""
    venue_order_id: str
    client_order_id: str | None
    status: OrderStatus
    filled_size: Decimal
    filled_avg_price: Decimal | None
    remaining_size: Decimal
    fees_paid: Decimal
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class NormalizedPosition:
    """Current open position in a market."""
    market_id: str
    side: PositionSide
    size: Decimal
    avg_entry_price: Decimal
    venue: str
    current_price: Decimal | None = None
    unrealized_pnl: Decimal | None = None


@dataclass
class NormalizedBalance:
    """Account balance snapshot from a venue."""
    venue: str
    available_cash: Decimal
    total_equity: Decimal
    reserved_margin: Decimal
    currency: str = "USDC"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class NormalizedFillEvent:
    """Streamed fill event from a venue WebSocket."""
    venue: str
    venue_order_id: str
    market_id: str
    side: OrderSide
    filled_size: Decimal
    filled_price: Decimal
    fill_timestamp: float
    is_final: bool
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class MarketInfo:
    """Normalized market metadata from a venue."""
    venue: str
    market_id: str
    title: str
    description: str
    category: str
    yes_price: Decimal | None
    no_price: Decimal | None
    volume_24h: Decimal
    open_interest: Decimal
    closes_at: float | None
    is_active: bool
    min_order_size: Decimal
    tick_size: Decimal
    raw: dict[str, Any] = field(default_factory=dict)
