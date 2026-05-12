"""Polymarket data source plugin for the plugin system."""
import os
from dataclasses import dataclass
from backend.data.source_registry import source_registry
from typing import Any, Dict, List

from backend.core.plugin_errors import DataSourceError
from backend.data.base_source import BaseDataSource, DataSourceManifest, DataType

try:
    from backend.data.polymarket_clob import PolymarketCLOB
    HAS_POLYMARKET = True
except ImportError:
    HAS_POLYMARKET = False


@dataclass
class PolymarketManifest(DataSourceManifest):
    pass


# Register with the source registry


@source_registry.plugin
class PolymarketSource(BaseDataSource):
    """Polymarket CLOB data source plugin."""

    @classmethod
    def manifest(cls) -> DataSourceManifest:
        return PolymarketManifest(
            name="polymarket",
            display_name="Polymarket",
            version="1.0.0",
            data_types=[
                DataType.ORDERBOOK,
                DataType.CANDLES,
                DataType.PRICE,
                DataType.MARKET_META,
            ],
            supports_streaming=True,
            supports_backfill=True,
            required_env_vars=["POLYMARKET_API_KEY", "POLYMARKET_API_SECRET"],
            rate_limit_per_minute=60,
            is_live=True,
            tags=["primary", "prediction_market"],
        )

    def __init__(self):
        super().__init__()
        if not HAS_POLYMARKET:
            raise ImportError("py-clob-client not installed")
        api_key = os.environ.get("POLYMARKET_API_KEY", "")
        api_secret = os.environ.get("POLYMARKET_API_SECRET", "")
        self._client = PolymarketCLOB(api_key=api_key, api_secret=api_secret)

    async def fetch(self, data_type: DataType, params: Dict[str, Any]) -> Any:
        market_id = params.get("market_id")
        if not market_id:
            raise DataSourceError("market_id required for Polymarket fetch")

        if data_type == DataType.ORDERBOOK:
            return await self._client.get_orderbook(market_id)
        elif data_type == DataType.CANDLES:
            resolution = params.get("resolution", "1h")
            return await self._client.get_candles(market_id, resolution)
        elif data_type == DataType.PRICE:
            return await self._client.get_last_price(market_id)
        elif data_type == DataType.MARKET_META:
            return await self._client.get_market(market_id)
        else:
            raise DataSourceError(f"Unsupported data type: {data_type}")

    async def stream(self, data_type: DataType, params: Dict[str, Any]):
        if data_type == DataType.ORDERBOOK:
            async for update in self._client.stream_orderbook(params.get("market_id")):
                yield update
        else:
            raise NotImplementedError(f"Streaming not supported for {data_type}")

    async def backfill(self, data_type: DataType, params: Dict[str, Any],
                       since_ts: int, until_ts: int) -> List[Any]:
        market_id = params.get("market_id")
        resolution = params.get("resolution", "1h")
        return await self._client.get_candles(market_id, resolution, since_ts, until_ts)