"""Data source abstract base class and manifest for the plugin system."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncGenerator, List


class DataType(str, Enum):
    ORDERBOOK = "orderbook"
    CANDLES = "candles"
    PRICE = "price"
    MARKET_META = "market_meta"
    WEATHER = "weather"
    SENTIMENT = "sentiment"
    POSITIONS = "positions"
    LEADERBOARD = "leaderboard"


@dataclass
class DataSourceManifest:
    """Declarative metadata for a data source plugin."""
    name: str
    display_name: str
    version: str
    data_types: List[DataType]
    supports_streaming: bool = False
    supports_backfill: bool = False
    required_env_vars: List[str] = field(default_factory=list)
    rate_limit_per_minute: int = 60
    is_live: bool = True
    tags: List[str] = field(default_factory=list)


class BaseDataSource(ABC):
    """Every data source plugin must subclass this."""

    @classmethod
    @abstractmethod
    def manifest(cls) -> DataSourceManifest:
        ...

    @abstractmethod
    async def fetch(self, data_type: DataType, params: dict[str, Any]) -> Any:
        """Fetch a single snapshot of data. Raise DataSourceError on failure."""
        ...

    async def stream(
        self, data_type: DataType, params: dict[str, Any]
    ) -> AsyncGenerator[Any, None]:
        """Optional: yield live updates."""
        raise NotImplementedError(f"{self.__class__.__name__} does not support streaming")

    async def backfill(
        self, data_type: DataType, params: dict[str, Any], since_ts: int, until_ts: int
    ) -> list[Any]:
        """Optional: fetch historical data for backtesting."""
        raise NotImplementedError

    async def health_check(self) -> bool:
        """Lightweight liveness probe."""
        try:
            await self.fetch(self.manifest().data_types[0], {})
            return True
        except Exception:
            return False

    async def teardown(self) -> None:
        """Close connections cleanly on detach."""
        pass
