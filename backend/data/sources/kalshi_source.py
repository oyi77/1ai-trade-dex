"""Kalshi data source plugin for the plugin system."""
import os
from dataclasses import dataclass
from backend.data.source_registry import source_registry
from typing import Any, Dict, List

from backend.core.plugin_errors import DataSourceError
from backend.data.base_source import BaseDataSource, DataSourceManifest, DataType

try:
    from backend.data.kalshi_client import KalshiClient
    HAS_KALSHI = True
except ImportError:
    HAS_KALSHI = False


@dataclass
class KalshiManifest(DataSourceManifest):
    pass




@source_registry.plugin
class KalshiSource(BaseDataSource):
    """Kalshi REST data source plugin."""

    @classmethod
    def manifest(cls) -> DataSourceManifest:
        return KalshiManifest(
            name="kalshi",
            display_name="Kalshi",
            version="1.0.0",
            data_types=[
                DataType.PRICE,
                DataType.MARKET_META,
                DataType.POSITIONS,
            ],
            supports_streaming=False,
            supports_backfill=True,
            required_env_vars=["KALSHI_API_KEY", "KALSHI_API_SECRET"],
            rate_limit_per_minute=60,
            is_live=True,
            tags=["primary", "prediction_market"],
        )

    def __init__(self):
        super().__init__()
        if not HAS_KALSHI:
            raise ImportError("Kalshi client not installed")
        api_key = os.environ.get("KALSHI_API_KEY", "")
        api_secret = os.environ.get("KALSHI_API_SECRET", "")
        self._client = KalshiClient(api_key=api_key, api_secret=api_secret)

    async def fetch(self, data_type: DataType, params: Dict[str, Any]) -> Any:
        market_id = params.get("market_id")

        if data_type == DataType.PRICE:
            return await self._client.get_price(market_id)
        elif data_type == DataType.MARKET_META:
            return await self._client.get_market(market_id)
        elif data_type == DataType.POSITIONS:
            return await self._client.get_positions()
        else:
            raise DataSourceError(f"Unsupported data type: {data_type}")

    async def backfill(self, data_type: DataType, params: Dict[str, Any],
                       since_ts: int, until_ts: int) -> List[Any]:
        market_id = params.get("market_id")
        return await self._client.get_historical(market_id, since_ts, until_ts)
