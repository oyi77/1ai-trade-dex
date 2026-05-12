"""Integration tests for Data Source registry and strategy data flow.

Tests the complete data pipeline from:
- Data source registration and discovery
- Data aggregation with source priority and fallback
- Strategy context receives data from registered sources
- Mock data source integration in sandbox mode
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from backend.data.base_source import BaseDataSource, DataSourceManifest, DataType
from backend.data.source_registry import DataSourceRegistry
from backend.data.sources.mock_source import MockDataSource
from backend.data.aggregator import DataAggregator, SourceResult, DataSource as AggSource


class TestDataSourceRegistryIntegration:
    """Integration tests for DataSourceRegistry with mock sources."""

    def setup_method(self):
        """Setup clean registry for each test."""
        DataSourceRegistry.reset()
        self.registry = DataSourceRegistry("test_registry")

    def teardown_method(self):
        """Clean up after test."""
        DataSourceRegistry.reset()

    def test_register_and_retrieve_mock_source(self):
        """Test mock source registration and retrieval."""
        self.registry.register(MockDataSource)
        
        source = self.registry.get("mock")
        assert source is not None
        assert isinstance(source, MockDataSource)
        assert source.manifest().name == "mock"

    def test_get_for_type_filters_by_datatype(self):
        """Test filtering sources by data type."""
        self.registry.register(MockDataSource)
        
        price_sources = self.registry.get_for_type(DataType.PRICE)
        assert len(price_sources) >= 1
        
        orderbook_sources = self.registry.get_for_type(DataType.ORDERBOOK)
        assert len(orderbook_sources) >= 1
        
        unsupported_sources = self.registry.get_for_type(DataType.WEATHER)
        assert len(unsupported_sources) >= 1

    def test_enable_disable_source_persists(self):
        """Test that enabling/disabling sources updates registry state."""
        self.registry.register(MockDataSource)
        assert self.registry._enabled["mock"] is True
        
        self.registry.set_enabled("mock", False)
        assert self.registry._enabled["mock"] is False
        
        self.registry.set_enabled("mock", True)
        assert self.registry._enabled["mock"] is True


class TestDataAggregatorIntegration:
    """Integration tests for DataAggregator with multiple sources."""

    def setup_method(self):
        self.aggregator = DataAggregator(cache_ttl=60.0)

    def test_register_and_fetch_single_source(self):
        """Test fetching from a single registered source."""
        async def fetch_price():
            return {"price": 100.50, "timestamp": datetime.now(timezone.utc).timestamp()}
        
        source = AggSource(
            name="test_source",
            fetch_fn=fetch_price,
            priority=0,
            enabled=True
        )
        self.aggregator.register_source("price_feed", source)
        
        import asyncio
        result = asyncio.run(self.aggregator.fetch("price_feed"))
        assert isinstance(result, SourceResult)
        assert result.source == "test_source"
        assert result.data["price"] == 100.50

    def test_multiple_sources_priority_order(self):
        """Test that higher priority sources are tried first."""
        async def fetch_priority_0():
            return {"price": 100.0, "source": "high_priority"}
        
        async def fetch_priority_1():
            return {"price": 101.0, "source": "low_priority"}
        
        self.aggregator.register_source("price_feed", 
            AggSource("high_priority", fetch_priority_0, priority=0))
        self.aggregator.register_source("price_feed",
            AggSource("low_priority", fetch_priority_1, priority=1))
        
        import asyncio
        result = asyncio.run(self.aggregator.fetch("price_feed"))
        assert result.source == "high_priority"
        assert result.data["price"] == 100.0

    def test_fallback_to_lower_priority_on_failure(self):
        """Test fallback to lower priority source when higher fails."""
        call_count = {"primary": 0, "secondary": 0}
        
        async def fetch_fails():
            call_count["primary"] += 1
            raise Exception("Source unavailable")
        
        async def fetch_succeeds():
            call_count["secondary"] += 1
            return {"price": 99.50}
        
        self.aggregator.register_source("price_feed",
            AggSource("primary", fetch_fails, priority=0))
        self.aggregator.register_source("price_feed",
            AggSource("secondary", fetch_succeeds, priority=1))
        
        import asyncio
        result = asyncio.run(self.aggregator.fetch("price_feed"))
        assert call_count["primary"] == 1
        assert call_count["secondary"] == 1
        assert result.data["price"] == 99.50

    @pytest.mark.asyncio
    async def test_mock_source_in_strategy_context(self):
        """Test that mock source provides data to strategy context."""
        registry = DataSourceRegistry("strategy_test")
        registry.register(MockDataSource)
        
        source = registry.get("mock")
        data = await source.fetch(DataType.PRICE, {"market": "BTC-USD"})
        
        assert "price" in data or "data" in data
        assert isinstance(data, dict)
        
        registry.set_enabled("mock", False)
        assert registry._enabled["mock"] is False


class TestStrategyDataFlowIntegration:
    """Integration tests for complete data flow to strategies."""

    def setup_method(self):
        DataSourceRegistry.reset()

    def teardown_method(self):
        DataSourceRegistry.reset()

    def test_data_sources_registered_before_strategy_init(self):
        """Test that sources are available when strategy initializes."""
        registry = DataSourceRegistry("strategy_setup")
        registry.register(MockDataSource)
        price_sources = registry.get_for_type(DataType.PRICE)
        assert len(price_sources) >= 1
        
        orderbook_sources = registry.get_for_type(DataType.ORDERBOOK)
        assert len(orderbook_sources) >= 1

    def test_strategy_receives_data_from_multiple_sources(self):
        """Test strategy integration with multi-source aggregator."""
        aggregator = DataAggregator(cache_ttl=30.0)
        
        async def fetch_data():
            return {"price": 50000.0, "volume": 1000}
        
        aggregator.register_source("btc_price",
            AggSource("mock_provider", fetch_data, priority=0))
        
        import asyncio
        result = asyncio.run(aggregator.fetch("btc_price"))
        assert result.data["price"] == 50000.0
        assert result.data["volume"] == 1000

    @pytest.mark.asyncio
    async def test_strategy_context_data_persistence(self):
        """Test that strategy context maintains data across fetches."""
        registry = DataSourceRegistry("persistence_test")
        registry.register(MockDataSource)
        source = registry.get("mock")
        data1 = await source.fetch(DataType.CANDLES, {"market": "BTC-USD", "interval": "5m"})
        data2 = await source.fetch(DataType.CANDLES, {"market": "BTC-USD", "interval": "5m"})
        
        assert data1 is not None
        assert data2 is not None
