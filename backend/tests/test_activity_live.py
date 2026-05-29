"""Live integration tests — hit real provider APIs and verify activity/balance tracking works."""

import asyncio
import os
import sys
import pytest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


WALLET = _env("WALLET_ADDRESS") or _env("POLYMARKET_WALLET_ADDRESS")


# ── Structural tests (no network) ──

class TestBaseActivitySourceLifecycle:
    """Verify BaseActivitySource start/stop/subtask lifecycle."""

    @pytest.mark.asyncio
    async def test_subtask_cancellation_on_stop(self):
        from backend.core.activity.sources.base import BaseActivitySource

        events = []

        class DummySource(BaseActivitySource):
            async def _run(self):
                t = self.create_subtask(self._slow_loop())
                # Keep main task alive so subtask stays running
                try:
                    while self._running:
                        await asyncio.sleep(0.05)
                except asyncio.CancelledError:
                    pass

            async def _slow_loop(self):
                try:
                    while True:
                        await asyncio.sleep(10)
                except asyncio.CancelledError:
                    events.append("cancelled")
                    raise

        source = DummySource(WALLET or "0xtest", "dummy")
        await source.start()
        await asyncio.sleep(0.2)  # Let subtask start
        assert source._running is True
        assert len(source._subtasks) >= 1
        await source.stop()
        assert source._running is False
        assert "cancelled" in events

    def test_detect_balance_delta(self):
        from backend.core.activity.sources.base import BaseActivitySource

        class ConcreteSource(BaseActivitySource):
            async def _run(self):
                pass

        source = ConcreteSource("0xtest", "test")
        assert source.detect_balance_delta(100.0, 100.0) is None
        assert source.detect_balance_delta(100.005, 100.0) is None
        assert source.detect_balance_delta(150.0, 100.0) == ("deposit", 50.0)
        assert source.detect_balance_delta(80.0, 100.0) == ("withdrawal", 20.0)
        # threshold=0.3: 0.2 delta is below → None
        assert source.detect_balance_delta(100.2, 100.0, threshold=0.3) is None
        # threshold=0.3: 0.5 delta is above → deposit
        assert source.detect_balance_delta(100.5, 100.0, threshold=0.3) == ("deposit", 0.5)


class TestConstantsImport:
    """Verify slop cleanup — constants imported correctly."""

    def test_erc20_transfer_topic_importable(self):
        from backend.constants import ERC20_TRANSFER_TOPIC, BALANCE_DELTA_THRESHOLD
        assert ERC20_TRANSFER_TOPIC.startswith("0xddf252ad")
        assert BALANCE_DELTA_THRESHOLD == 0.01

    def test_polymarket_uses_shared_constants(self):
        from backend.core.activity.sources.polymarket_source import PolymarketActivitySource
        import inspect
        source = inspect.getsource(PolymarketActivitySource)
        assert "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174" not in source
        assert "USDC_E_ADDRESS" in source
        assert "ERC20_TRANSFER_TOPIC" in source
        assert "BALANCE_DELTA_THRESHOLD" in source

    def test_no_hardcoded_balance_threshold(self):
        import importlib
        import inspect
        sources = [
            "backend.core.activity.sources.aster_source",
            "backend.core.activity.sources.hyperliquid_source",
            "backend.core.activity.sources.lighter_source",
            "backend.core.activity.sources.polymarket_source",
            "backend.core.activity.sources.kalshi_source",
            "backend.core.activity.sources.ostium_source",
            "backend.core.activity.sources.myriad_source",
            "backend.core.activity.sources.sxbet_source",
        ]
        for mod_name in sources:
            mod = importlib.import_module(mod_name)
            source = inspect.getsource(mod)
            assert "> 0.01" not in source, f"{mod_name} still has hardcoded 0.01 threshold"

    def test_no_fire_and_forget_create_task_in_run(self):
        """Sources use self.create_subtask() in _run(), not bare asyncio.create_task()."""
        import importlib
        import inspect
        sources = [
            "backend.core.activity.sources.aster_source",
            "backend.core.activity.sources.hyperliquid_source",
            "backend.core.activity.sources.lighter_source",
            "backend.core.activity.sources.polymarket_source",
            "backend.core.activity.sources.kalshi_source",
            "backend.core.activity.sources.ostium_source",
            "backend.core.activity.sources.myriad_source",
            "backend.core.activity.sources.sxbet_source",
        ]
        for mod_name in sources:
            mod = importlib.import_module(mod_name)
            source_code = inspect.getsource(mod)
            # Only check _run method body for asyncio.create_task (WS callbacks are fine)
            in_run = False
            for line in source_code.split('\n'):
                stripped = line.strip()
                if 'async def _run' in stripped:
                    in_run = True
                elif stripped.startswith('async def ') and '_run' not in stripped:
                    in_run = False
                if in_run and 'asyncio.create_task' in stripped and '#' not in stripped:
                    pytest.fail(f"{mod_name} has asyncio.create_task in _run: {stripped}")


class TestSourceInstantiation:
    """All 11 sources instantiate and have required methods."""

    SOURCES = [
        ("aster", "backend.core.activity.sources.aster_source", "AsterActivitySource", {"wallet_address": WALLET or "0xtest", "client": MagicMock()}),
        ("hyperliquid", "backend.core.activity.sources.hyperliquid_source", "HyperliquidActivitySource", {"wallet_address": WALLET or "0xtest", "client": MagicMock()}),
        ("lighter", "backend.core.activity.sources.lighter_source", "LighterActivitySource", {"wallet_address": WALLET or "0xtest", "ws_client": MagicMock()}),
        ("polymarket", "backend.core.activity.sources.polymarket_source", "PolymarketActivitySource", {"wallet_address": WALLET or "0xtest", "clob_client": MagicMock()}),
        ("azuro", "backend.core.activity.sources.azuro_source", "AzuroActivitySource", {"wallet_address": WALLET or "0xtest"}),
        # ("limitless", "backend.core.activity.sources.limitless_source", "LimitlessActivitySource", {"wallet_address": WALLET or "0xtest"}),  # DISABLED
        ("kalshi", "backend.core.activity.sources.kalshi_source", "KalshiActivitySource", {"wallet_address": WALLET or "0xtest"}),
        ("ostium", "backend.core.activity.sources.ostium_source", "OstiumActivitySource", {"wallet_address": WALLET or "0xtest"}),
        ("myriad", "backend.core.activity.sources.myriad_source", "MyriadActivitySource", {"wallet_address": WALLET or "0xtest"}),
        ("sxbet", "backend.core.activity.sources.sxbet_source", "SXBetActivitySource", {"wallet_address": WALLET or "0xtest"}),
        ("paper", "backend.core.activity.sources.paper_source", "PaperActivitySource", {}),
    ]

    @pytest.mark.parametrize("name,module,cls,kwargs", SOURCES, ids=[s[0] for s in SOURCES])
    def test_source_instantiation_with_subtask_tracking(self, name, module, cls, kwargs):
        import importlib
        from backend.core.activity.sources.base import BaseActivitySource

        mod = importlib.import_module(module)
        klass = getattr(mod, cls)
        source = klass(**kwargs)
        assert isinstance(source, BaseActivitySource)
        assert hasattr(source, 'create_subtask')
        assert hasattr(source, 'detect_balance_delta')
        assert len(source._subtasks) == 0


# ── Live provider tests (require network + env) ──
# Marked with @pytest.mark.live so they can be skipped in CI

@pytest.mark.live
class TestPolymarketLive:
    @pytest.mark.asyncio
    async def test_polymarket_rest_fills(self):
        if not _env("POLYMARKET_WALLET_ADDRESS"):
            pytest.skip("No POLYMARKET_WALLET_ADDRESS")
        from backend.data.polymarket_clob import clob_from_settings
        async with clob_from_settings() as client:
            fills = await client.get_trader_trades(_env("POLYMARKET_WALLET_ADDRESS"))
        assert isinstance(fills, list)

    @pytest.mark.asyncio
    async def test_polymarket_balance(self):
        if not _env("POLYMARKET_WALLET_ADDRESS"):
            pytest.skip("No POLYMARKET_WALLET_ADDRESS")
        from backend.data.polymarket_clob import clob_from_settings
        async with clob_from_settings() as client:
            balance = await client.get_wallet_balance()
        assert float(balance.get("usdc_balance", 0)) >= 0


@pytest.mark.live
class TestHyperliquidLive:
    @pytest.mark.asyncio
    async def test_hyperliquid_fills(self):
        if not _env("HYPERLIQUID_WALLET_ADDRESS"):
            pytest.skip("No HYPERLIQUID_WALLET_ADDRESS")
        from backend.data.hyperliquid_client import HyperliquidClient
        client = HyperliquidClient()
        fills = await client.get_user_fills(_env("HYPERLIQUID_WALLET_ADDRESS"))
        assert isinstance(fills, list)


@pytest.mark.live
class TestKalshiLive:
    @pytest.mark.asyncio
    async def test_kalshi_fills(self):
        from backend.data.kalshi_client import KalshiClient
        client = KalshiClient()
        fills = await client.get_fills()
        assert isinstance(fills, list)


@pytest.mark.live
class TestOstiumLive:
    @pytest.mark.asyncio
    async def test_ostium_health(self):
        from backend.clients.ostium_client import OstiumClient
        client = OstiumClient()
        result = await client.health_check()
        assert isinstance(result, bool)


@pytest.mark.live
class TestMyriadLive:
    @pytest.mark.asyncio
    async def test_myriad_health(self):
        from backend.clients.myriad_client import MyriadClient
        client = MyriadClient()
        result = await client.health_check()
        assert isinstance(result, bool)


@pytest.mark.live
class TestSXBetLive:
    @pytest.mark.asyncio
    async def test_sxbet_health(self):
        from backend.clients.sxbet_client import SXBetClient
        client = SXBetClient()
        result = await client.health_check()
        assert isinstance(result, bool)