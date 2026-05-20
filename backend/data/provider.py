# backend/data/provider.py
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import List


@dataclass
class MarketEntry:
    ticker: str
    question: str
    market_id: str
    platform: str
    current_price: float
    volume_24h: float
    liquidity: float
    created_at: str


@dataclass
class PositionEntry:
    market_id: str
    side: str
    size: float
    entry_price: float
    current_price: float
    unrealized_pnl: float


@dataclass
class BalanceInfo:
    available: float
    locked: float
    total: float


class DataProvider(ABC):
    """Abstract data provider interface.

    .. deprecated::
        This provider system is deprecated. Use `backend.markets.base_provider.BaseMarketProvider`
        and its implementations in `backend/markets/providers/` instead. This module will be
        removed in a future version.
    """

    @property
    @abstractmethod
    def platform_name(self) -> str:
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        pass

    @abstractmethod
    async def get_markets(
        self, category: str = None, limit: int = 100
    ) -> "List[MarketEntry]":
        pass

    @abstractmethod
    async def get_orderbook(self, market_id: str) -> dict:
        pass

    @abstractmethod
    async def get_positions(self) -> "List[PositionEntry]":
        pass

    @abstractmethod
    async def get_balance(self) -> BalanceInfo:
        pass

    @abstractmethod
    async def place_order(
        self, market_id: str, side: str, size: float, price: float, **kwargs
    ) -> dict:
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        pass
