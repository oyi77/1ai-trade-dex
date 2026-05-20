"""
Unified market view adapter for API responses.

This module provides a lightweight return-type adapter that normalizes
different market data models (BtcMarket, WeatherMarket, etc.) into a
common format for API consumers.

NOTE: This is NOT a base class or inheritance hierarchy. Each market
type remains independent with its own domain-specific fields. The
to_unified() method is a simple adapter that converts to a shared API
response format.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict


@dataclass
class UnifiedMarketView:
    """
    A normalized view of a market for API responses.

    This adapter provides a common interface for different market types
    without forcing them into a shared inheritance hierarchy. Each market
    type implements to_unified() to convert its domain model to this view.

    Fields:
        slug: Market identifier
        platform: Source platform (polymarket, kalshi, etc.)
        title: Human-readable market title
        yes_price: Price of YES/UP outcome (0-1)
        no_price: Price of NO/DOWN outcome (0-1)
        volume: Trading volume
        closes_at: When the market closes/resolves (datetime)
        extra: Type-specific data (city, threshold, window, etc.)
    """

    slug: str
    platform: str
    title: str
    yes_price: float
    no_price: float
    volume: float
    closes_at: datetime | None
    extra: Dict[str, Any]
