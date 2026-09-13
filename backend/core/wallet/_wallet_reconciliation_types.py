"""Wallet reconciliation result types (leaf — no intra-package imports)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class PositionComparison:
    """Result of comparing blockchain vs DB position."""

    market_id: str
    db_status: str  # "open" | "closed" | "missing"
    blockchain_status: str
    db_size: float
    blockchain_size: float
    discrepancy: bool


@dataclass
class OrphanedPosition:
    """Position on blockchain but missing from DB."""

    market_id: str
    blockchain_size: float
    blockchain_entry_price: float
    clob_order_id: Optional[str] = None
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class SyncResult:
    """Reconciliation cycle result."""

    imported_count: int = 0
    updated_count: int = 0
    closed_count: int = 0
    errors: list[str] = field(default_factory=list)
    last_sync_at: Optional[datetime] = None


