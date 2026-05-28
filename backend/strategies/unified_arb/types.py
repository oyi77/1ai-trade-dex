"""Unified Arb Strategy — shared types and provider ABCs."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

__all__ = [
    "ArbProvider",
    "PMProvider",
    "DEXProvider",
    "PMMarket",
    "SpotMarket",
    "OrderResult",
    "FeeSchedule",
    "ArbOpportunity",
    "ArbKind",
]


class ArbKind(str, Enum):
    CROSS_PLATFORM = "cross_platform"  # PM: same market on 2 venues
    CROSS_DEX = "cross_dex"  # DEX: same asset on 2 exchanges
    YES_NO_SUM = "yes_no_sum"  # PM: YES + NO < 1.0
    COMPLEMENTARY = "complementary"  # PM: complementary outcomes


@dataclass
class FeeSchedule:
    taker_fee_pct: float = 0.0
    maker_fee_pct: float = 0.0
    slippage_bps: float = 0.0


@dataclass
class OrderResult:
    order_id: str = ""
    status: str = "pending"  # "filled", "pending", "failed", "cancelled"
    fill_price: float = 0.0
    error: str = ""


@dataclass
class PMMarket:
    """Binary prediction market (Polymarket, Kalshi, etc.)."""

    event_id: str = ""
    question: str = ""
    slug: str = ""
    platform: str = ""
    yes_price: float = 0.0
    no_price: float = 0.0
    token_id_yes: str = ""
    token_id_no: str = ""
    condition_id: str = ""
    fee_pct: float = 0.0
    liquidity: float = 0.0
    volume: float = 0.0
    end_date: str = ""
    category: str = ""


@dataclass
class SpotMarket:
    """DEX perpetual/spot quote (Hyperliquid, Ostium, etc.)."""

    exchange: str = ""
    base: str = ""
    quote: str = "USD"
    bid: float = 0.0
    ask: float = 0.0
    mid: float = 0.0
    fee_pct: float = 0.0


@dataclass
class ArbOpportunity:
    """A detected arbitrage opportunity."""

    kind: ArbKind = ArbKind.CROSS_PLATFORM
    platform_a: str = ""
    platform_b: str = ""
    price_a: float = 0.0
    price_b: float = 0.0
    token_id_a: str = ""
    token_id_b: str = ""
    net_profit: float = 0.0
    gross_profit: float = 0.0
    fees: float = 0.0
    event_id: str = ""
    question: str = ""
    size_usd: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)


class ArbProvider(ABC):
    """Base class for all arb providers."""

    @property
    @abstractmethod
    def venue_name(self) -> str: ...

    @abstractmethod
    async def fetch_markets(self, limit: int = 500) -> List[Union[PMMarket, SpotMarket]]: ...

    @abstractmethod
    def get_fee_schedule(self) -> FeeSchedule: ...

    async def health_check(self) -> bool:
        return True


class PMProvider(ArbProvider):
    """Binary market provider with order execution."""

    @abstractmethod
    async def place_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
        idempotency_key: str = "",
    ) -> OrderResult: ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool: ...


class DEXProvider(ArbProvider):
    """DEX provider — detection only. Execution deferred to follow-up."""

    pass
