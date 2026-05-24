"""Activity event model for blockchain tracking."""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import uuid


@dataclass
class ActivityEvent:
    """Single activity event from any source."""

    source: str  # 'aster' | 'hyperliquid' | 'lighter' | 'polymarket' | 'polygon' | 'kalshi'
    event_type: str  # 'deposit' | 'withdrawal' | 'trade_open' | 'trade_closed' | 'buy' | 'sell' | 'redeem' | 'transfer'
    wallet_address: str
    platform: str  # venue name
    amount: float
    token: str  # 'USDC' | 'ETH' | 'MATIC' | etc.
    tx_hash: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw_data: Dict[str, Any] = field(default_factory=dict)
    trade_id: Optional[str] = None  # FK to Trade if matched
    order_id: Optional[str] = None  # exchange order ID
    side: Optional[str] = None  # 'buy' | 'sell' | None
    price: Optional[float] = None
    fee: Optional[float] = None
    pnl: Optional[float] = None  # realized PnL for trade_closed
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "event_type": self.event_type,
            "wallet_address": self.wallet_address,
            "platform": self.platform,
            "amount": self.amount,
            "token": self.token,
            "tx_hash": self.tx_hash,
            "timestamp": self.timestamp.isoformat(),
            "raw_data": self.raw_data,
            "trade_id": self.trade_id,
            "order_id": self.order_id,
            "side": self.side,
            "price": self.price,
            "fee": self.fee,
            "pnl": self.pnl,
        }


@dataclass
class ActivitySummary:
    """Aggregated activity stats."""
    total_deposits: float = 0.0
    total_withdrawals: float = 0.0
    total_trades_opened: int = 0
    total_trades_closed: int = 0
    total_volume: float = 0.0
    realized_pnl: float = 0.0
    events: list[ActivityEvent] = field(default_factory=list)
