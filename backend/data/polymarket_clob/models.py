"""CLOB data models."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class OrderResult:
    """Result of placing an order."""
    success: bool
    order_id: Optional[str] = None
    error: Optional[str] = None
    fill_price: Optional[float] = None
    fill_size: Optional[float] = None
    idempotency_key: Optional[str] = None
    maker_filled: bool = False


@dataclass
class OrderBook:
    """Order book snapshot."""
    token_id: str
    bids: list[dict] = field(default_factory=list)  # [{price, size}]
    asks: list[dict] = field(default_factory=list)
    mid_price: float = 0.5

    @property
    def best_ask(self) -> Optional[float]:
        return float(self.asks[0]["price"]) if self.asks else None

    @property
    def best_bid(self) -> Optional[float]:
        return float(self.bids[0]["price"]) if self.bids else None

    @property
    def spread(self) -> float:
        if self.best_ask and self.best_bid:
            return self.best_ask - self.best_bid
        return 1.0


@dataclass
class TradeRecord:
    """Trade record from Polymarket Data API."""
    id: str
    user: str
    asset_id: str
    outcome: str  # "YES" | "NO"
    shares: float
    price: float
    spent: float
    timestamp: int
    transaction_hash: Optional[str] = None
    block_number: Optional[int] = None

    @property
    def created_at(self) -> datetime:
        """Convert timestamp to datetime."""
        return datetime.fromtimestamp(self.timestamp, tz=timezone.utc)
