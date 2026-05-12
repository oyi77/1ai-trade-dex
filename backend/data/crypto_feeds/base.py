"""Base classes for crypto exchange feed plugins."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ExchangeFeedManifest:
    name: str
    display_name: str
    version: str
    base_url: str
    supported_pairs: List[str]
    rate_limit_per_minute: int
    required_env_vars: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)


class BaseExchangeFeed(ABC):
    @classmethod
    @abstractmethod
    def manifest(cls) -> ExchangeFeedManifest:
        ...

    @abstractmethod
    async def get_btc_price(self) -> float:
        ...

    @abstractmethod
    async def get_klines(self, symbol: str, interval: str, limit: int) -> Optional[List]:
        ...

    async def health_check(self) -> bool:
        try:
            price = await self.get_btc_price()
            return price > 0
        except Exception:
            return False

    async def teardown(self) -> None:
        pass
