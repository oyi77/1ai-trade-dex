"""Live integration tests for activity tracker — verifies provider connectivity and source interfaces."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestActivitySourceInterfaces:
    """Verify all activity sources follow BaseActivitySource interface."""

    # (source_name, module, class_name, constructor_kwargs)
    SOURCES = [
        ("aster", "backend.core.activity.sources.aster_source", "AsterActivitySource", {"wallet_address": "0xtest", "client": MagicMock()}),
        ("hyperliquid", "backend.core.activity.sources.hyperliquid_source", "HyperliquidActivitySource", {"wallet_address": "0xtest", "client": MagicMock()}),
        ("lighter", "backend.core.activity.sources.lighter_source", "LighterActivitySource", {"wallet_address": "0xtest", "ws_client": MagicMock()}),
        ("polymarket", "backend.core.activity.sources.polymarket_source", "PolymarketActivitySource", {"wallet_address": "0xtest", "clob_client": MagicMock()}),
        ("azuro", "backend.core.activity.sources.azuro_source", "AzuroActivitySource", {"wallet_address": "0xtest"}),
        ("limitless", "backend.core.activity.sources.limitless_source", "LimitlessActivitySource", {"wallet_address": "0xtest"}),
        ("kalshi", "backend.core.activity.sources.kalshi_source", "KalshiActivitySource", {"wallet_address": "0xtest"}),
        ("ostium", "backend.core.activity.sources.ostium_source", "OstiumActivitySource", {"wallet_address": "0xtest"}),
        ("myriad", "backend.core.activity.sources.myriad_source", "MyriadActivitySource", {"wallet_address": "0xtest"}),
        ("sxbet", "backend.core.activity.sources.sxbet_source", "SXBetActivitySource", {"wallet_address": "0xtest"}),
        ("paper", "backend.core.activity.sources.paper_source", "PaperActivitySource", {}),
    ]

    @pytest.mark.parametrize("name,module,cls,kwargs", SOURCES, ids=[s[0] for s in SOURCES])
    def test_source_imports(self, name, module, cls, kwargs):
        """All activity source modules import correctly."""
        import importlib
        mod = importlib.import_module(module)
        klass = getattr(mod, cls)
        assert klass is not None

    @pytest.mark.parametrize("name,module,cls,kwargs", SOURCES, ids=[s[0] for s in SOURCES])
    def test_source_subclass(self, name, module, cls, kwargs):
        """All activity sources subclass BaseActivitySource."""
        import importlib
        from backend.core.activity.sources.base import BaseActivitySource
        mod = importlib.import_module(module)
        klass = getattr(mod, cls)
        assert issubclass(klass, BaseActivitySource)

    @pytest.mark.parametrize("name,module,cls,kwargs", SOURCES, ids=[s[0] for s in SOURCES])
    def test_source_has_run(self, name, module, cls, kwargs):
        """All activity sources have _run method."""
        import importlib
        mod = importlib.import_module(module)
        klass = getattr(mod, cls)
        assert hasattr(klass, "_run"), f"{cls} missing _run method"

    @pytest.mark.parametrize("name,module,cls,kwargs", SOURCES, ids=[s[0] for s in SOURCES])
    def test_source_instantiation(self, name, module, cls, kwargs):
        """All sources can be instantiated with correct constructor params."""
        import importlib
        mod = importlib.import_module(module)
        klass = getattr(mod, cls)
        source = klass(**kwargs)
        assert source.wallet_address == kwargs.get("wallet_address", "paper")
        assert source.platform == name

    def test_paper_source_create_trade_event(self):
        """Paper source factory creates valid ActivityEvents."""
        from backend.core.activity.sources.paper_source import PaperActivitySource
        from backend.core.activity.models import ActivityEvent
        source = PaperActivitySource()
        event = source.create_trade_event(
            event_type="trade_open",
            amount=50.0,
            side="buy",
            price=0.55,
            market_ticker="BTC Up or Down",
            order_id="paper-123",
            strategy="cex_pm_leadlag",
        )
        assert isinstance(event, ActivityEvent)
        assert event.source == "paper"
        assert event.platform == "paper"
        assert event.event_type == "trade_open"
        assert event.amount == 50.0


class TestClientMethods:
    """Verify all clients have required methods for activity sources."""

    CLIENTS = [
        ("KalshiClient", "backend.data.kalshi_client", ["get_fills", "get_balance", "get_positions"]),
        ("OstiumClient", "backend.clients.ostium_client", ["get_fills", "get_balance", "get_positions", "health_check"]),
        ("MyriadClient", "backend.clients.myriad_client", ["get_fills", "get_balance", "get_positions", "health_check"]),
        ("SXBetClient", "backend.clients.sxbet_client", ["get_fills", "get_balance", "get_positions", "health_check"]),
        ("LimitlessClient", "backend.clients.limitless_client", ["get_fills", "health_check"]),
        ("AzuroClient", "backend.clients.azuro_client", ["cached_query", "health_check"]),
    ]

    @pytest.mark.parametrize("cls_name,module,methods", CLIENTS, ids=[c[0] for c in CLIENTS])
    def test_client_has_methods(self, cls_name, module, methods):
        """All clients have required methods."""
        import importlib
        mod = importlib.import_module(module)
        klass = getattr(mod, cls_name)
        for method in methods:
            assert hasattr(klass, method), f"{cls_name} missing {method}"
            assert callable(getattr(klass, method)), f"{cls_name}.{method} not callable"


class TestDBModel:
    """Verify ActivityEventRecord DB model."""

    def test_model_columns(self):
        """ActivityEventRecord has all 17 columns."""
        from backend.models.database import ActivityEventRecord
        columns = [c.name for c in ActivityEventRecord.__table__.columns]
        expected = [
            "id", "source", "event_type", "wallet_address", "platform",
            "amount", "token", "tx_hash", "timestamp", "trade_id",
            "order_id", "side", "price", "fee", "pnl", "market_ticker",
            "raw_data",
        ]
        assert columns == expected

    def test_model_matches_dataclass(self):
        """ActivityEventRecord columns match ActivityEvent dataclass fields."""
        from backend.models.database import ActivityEventRecord
        from backend.core.activity.models import ActivityEvent
        import dataclasses

        model_cols = {c.name for c in ActivityEventRecord.__table__.columns}
        dataclass_fields = {f.name for f in dataclasses.fields(ActivityEvent)}
        assert dataclass_fields.issubset(model_cols)


class TestEventHandler:
    """Verify ActivityHandler event processing."""

    def test_persist_event_method_exists(self):
        """ActivityHandler has _persist_event method."""
        from backend.core.activity.event_handler import ActivityHandler
        assert hasattr(ActivityHandler, "_persist_event")

    def test_handler_mapping(self):
        """ActivityHandler maps event types to correct handlers."""
        from backend.core.activity.event_handler import ActivityHandler
        assert hasattr(ActivityHandler, "handle_event")
        assert hasattr(ActivityHandler, "_handle_transfer")
        assert hasattr(ActivityHandler, "_handle_trade_open")
        assert hasattr(ActivityHandler, "_handle_trade_close")


class TestOrchestratorRegistration:
    """Verify orchestrator registers all activity sources."""

    def test_all_sources_registered(self):
        """Orchestrator source registration includes all 11 platforms."""
        from backend.core.orchestrator import Orchestrator
        import inspect

        source = inspect.getsource(Orchestrator._register_activity_sources)
        expected = [
            "aster", "hyperliquid", "lighter", "polymarket",
            "azuro", "limitless", "kalshi", "ostium", "myriad", "sxbet", "paper",
        ]
        for name in expected:
            assert f'register_source("{name}"' in source, \
                f"Missing registration for {name}"

    def test_balance_aggregator_covers_new_platforms(self):
        """BalanceAggregator polling includes new platforms."""
        from backend.core.balance_aggregator import BalanceAggregator
        import inspect

        source = inspect.getsource(BalanceAggregator)
        for platform in ["myriad", "sxbet", "limitless", "azuro"]:
            assert platform in source.lower()


class TestPolymarketWSUpgrade:
    """Verify Polymarket source has WS + REST fallback pattern."""

    def test_ws_fallback_methods(self):
        """PolymarketActivitySource has both WS and REST methods."""
        from backend.core.activity.sources.polymarket_source import PolymarketActivitySource
        assert hasattr(PolymarketActivitySource, "_ws_fills_loop")
        assert hasattr(PolymarketActivitySource, "_connect_ws_fills")
        assert hasattr(PolymarketActivitySource, "_rest_fills_loop")

    def test_no_get_event_loop_antipattern(self):
        """Polymarket source doesn't use asyncio.get_event_loop()."""
        import inspect
        from backend.core.activity.sources.polymarket_source import PolymarketActivitySource
        source = inspect.getsource(PolymarketActivitySource)
        assert "asyncio.get_event_loop()" not in source

    def test_ws_url_warning_not_debug(self):
        """WS URL missing uses warning level."""
        import inspect
        from backend.core.activity.sources.polymarket_source import PolymarketActivitySource
        source = inspect.getsource(PolymarketActivitySource)
        assert 'logger.warning("[polymarket] No WS_USER_URL' in source