"""Mock data source for sandbox testing."""
import random
import os
from backend.data.source_registry import source_registry
from dataclasses import dataclass
from typing import Any, Dict, List
from datetime import datetime, timezone

from backend.core.plugin_errors import DataSourceError
from backend.data.base_source import BaseDataSource, DataSourceManifest, DataType


@dataclass
class MockDataConfig:
    """Configuration for mock data generation."""
    volatility: float = 0.02
    trend: float = 0.0
    base_price: float = 0.5
    scenario: str = "default"
    seed: int = 42


@dataclass
class MockManifest(DataSourceManifest):
    pass




@source_registry.plugin
class MockDataSource(BaseDataSource):
    """In-memory mock data source for sandbox and testing.

    Data is seeded with a fixed random seed for reproducibility.
    is_live=False — this source is for testing only.
    """

    @classmethod
    def manifest(cls) -> DataSourceManifest:
        return MockManifest(
            name="mock",
            display_name="Mock Data Source",
            version="1.0.0",
            data_types=[
                DataType.ORDERBOOK,
                DataType.CANDLES,
                DataType.PRICE,
                DataType.MARKET_META,
                DataType.WEATHER,
                DataType.SENTIMENT,
                DataType.POSITIONS,
                DataType.LEADERBOARD,
            ],
            supports_streaming=True,
            supports_backfill=True,
            required_env_vars=[],
            rate_limit_per_minute=999,
            is_live=False,
            tags=["mock", "sandbox", "testing"],
        )

    def __init__(self):
        super().__init__()
        self._config = MockDataConfig()
        self._seed = int(os.environ.get("MOCK_DATA_SEED", "42"))
        self._rng = random.Random(self._seed)
        self._tick_count = 0
        self._price = self._config.base_price
        self._orderbook = self._generate_initial_orderbook()

    def _generate_initial_orderbook(self) -> Dict:
        """Generate initial orderbook around base price."""
        mid = self._config.base_price
        spread = self._config.volatility * 0.5
        return {
            "bids": [
                {"price": round(mid - spread * (1 + i * 0.1), 4),
                 "size": round(self._rng.uniform(10, 100), 2)}
                for i in range(10)
            ],
            "asks": [
                {"price": round(mid + spread * (1 + i * 0.1), 4),
                 "size": round(self._rng.uniform(10, 100), 2)}
                for i in range(10)
            ],
        }

    def _tick_price(self) -> float:
        """Simulate one price tick using geometric Brownian motion."""
        dt = 1.0 / 1000.0
        drift = self._config.trend * dt
        diffusion = self._config.volatility * (dt ** 0.5) * self._rng.gauss(0, 1)
        self._price *= (1 + drift + diffusion)
        self._price = max(0.01, min(0.99, self._price))
        self._tick_count += 1
        return self._price

    async def fetch(self, data_type: DataType, params: Dict[str, Any]) -> Any:
        if data_type == DataType.PRICE:
            return {
                "price": self._tick_price(),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "mock",
            }
        elif data_type == DataType.ORDERBOOK:
            self._tick_price()
            # Update orderbook with new prices
            mid = self._price
            spread = self._config.volatility * 0.5
            return {
                "bids": [
                    {"price": round(mid - spread * (1 + i * 0.1), 4),
                     "size": round(self._rng.uniform(10, 100), 2)}
                    for i in range(10)
                ],
                "asks": [
                    {"price": round(mid + spread * (1 + i * 0.1), 4),
                     "size": round(self._rng.uniform(10, 100), 2)}
                    for i in range(10)
                ],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        elif data_type == DataType.CANDLES:
            return self._generate_candles(params)
        elif data_type == DataType.MARKET_META:
            return self._generate_market_meta(params)
        elif data_type == DataType.WEATHER:
            return self._generate_weather(params)
        elif data_type == DataType.SENTIMENT:
            return self._generate_sentiment(params)
        elif data_type == DataType.POSITIONS:
            return []
        elif data_type == DataType.LEADERBOARD:
            return self._generate_leaderboard()
        else:
            raise DataSourceError(f"Unsupported data type: {data_type}")

    def _generate_candles(self, params: Dict) -> List[Dict]:
        """Generate mock candle data."""
        _ = params.get("resolution", "1m")
        count = params.get("count", 100)
        candles = []
        price = self._config.base_price
        for i in range(count):
            price *= (1 + self._rng.gauss(0, self._config.volatility))
            price = max(0.01, min(0.99, price))
            candles.append({
                "open": round(price, 4),
                "high": round(price * (1 + abs(self._rng.gauss(0, 0.005))), 4),
                "low": round(price * (1 - abs(self._rng.gauss(0, 0.005))), 4),
                "close": round(price, 4),
                "volume": round(self._rng.uniform(100, 10000), 2),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        return candles

    def _generate_market_meta(self, params: Dict) -> Dict:
        """Generate mock market metadata."""
        return {
            "market_id": params.get("market_id", "mock-market-001"),
            "title": params.get("title", "Mock Market"),
            "description": "Mock market for testing",
            "category": params.get("category", "test"),
            "volume_24h": round(self._rng.uniform(1000, 100000), 2),
            "is_active": True,
            "closes_at": None,
        }

    def _generate_weather(self, params: Dict) -> Dict:
        """Generate mock weather data."""
        return {
            "temperature": round(self._rng.uniform(-10, 40), 1),
            "humidity": round(self._rng.uniform(20, 90), 1),
            "wind_speed": round(self._rng.uniform(0, 30), 1),
            "condition": self._rng.choice(["sunny", "cloudy", "rainy", "snowy"]),
            "location": params.get("location", "mock-location"),
        }

    def _generate_sentiment(self, params: Dict) -> Dict:
        """Generate mock sentiment data."""
        return {
            "sentiment_score": round(self._rng.gauss(0, 0.3), 4),
            "bullish_prob": round(max(0, min(1, 0.5 + self._rng.gauss(0, 0.2))), 4),
            "source": "mock_sentiment",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _generate_leaderboard(self) -> List[Dict]:
        """Generate mock leaderboard."""
        return [
            {
                "rank": i + 1,
                "name": f"Trader_{i+1}",
                "pnl": round(self._rng.gauss(0, 1000), 2),
                "win_rate": round(max(0, min(1, self._rng.gauss(0.5, 0.15))), 4),
                "trades": self._rng.randint(10, 500),
            }
            for i in range(20)
        ]

    async def stream(self, data_type: DataType, params: Dict[str, Any]):
        """Stream mock data as an async generator."""
        import asyncio

        while True:
            if data_type == DataType.PRICE:
                yield {
                    "price": self._tick_price(),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "mock",
                }
            elif data_type == DataType.ORDERBOOK:
                yield await self.fetch(DataType.ORDERBOOK, params)
            else:
                raise NotImplementedError(f"Streaming not supported for {data_type}")
            await asyncio.sleep(0.1)  # 100ms tick rate

    async def backfill(self, data_type: DataType, params: Dict[str, Any],
                       since_ts: int, until_ts: int) -> List[Any]:
        """Generate deterministic historical data."""
        # Reset RNG for reproducibility
        self._rng = random.Random(self._seed)
        count = (until_ts - since_ts) // 60  # One per minute
        return [await self.fetch(data_type, params) for _ in range(count)]