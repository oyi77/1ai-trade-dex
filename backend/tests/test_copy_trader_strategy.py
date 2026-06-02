"""Tests for the CopyTraderStrategy."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.strategies.copy_trader_strategy import (
    CopySignal,
    CopyTraderStrategy,
    PositionCopier,
    TradeDetector,
    WalletSelector,
    ProfitableWallet,
    _compute_copy_score,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_ctx(mode: str = "paper", bankroll: float = 100.0) -> MagicMock:
    ctx = MagicMock()
    ctx.db = MagicMock()
    ctx.clob = None
    ctx.settings = MagicMock()
    ctx.logger = MagicMock()
    ctx.params = {}
    ctx.mode = mode
    ctx.bankroll = bankroll
    ctx.providers = {}
    ctx.market_registry = None
    ctx.get_market_provider.return_value = None
    return ctx


def _make_wallet(
    addr: str = "0xabc123",
    pnl: float = 500.0,
    win_rate: float = 0.60,
    trades: int = 150,
    sharpe: float = 1.5,
) -> ProfitableWallet:
    return ProfitableWallet(
        address=addr,
        total_pnl=pnl,
        win_rate=win_rate,
        total_trades=trades,
        sharpe_ratio=sharpe,
        copy_score=_compute_copy_score(pnl, win_rate, trades, sharpe),
    )


def _make_activity_event(
    wallet: str = "0xabc123",
    side: str = "BUY",
    price: float = 0.65,
    size: float = 50.0,
    condition_id: str = "cond_001",
    tx_hash: str = "tx_001",
) -> dict:
    return {
        "transactionHash": tx_hash,
        "side": side,
        "price": price,
        "size": size,
        "conditionId": condition_id,
        "outcomeIndex": 0,
        "title": "Test Market",
        "timestamp": "2026-05-30T12:00:00Z",
    }


# ---------------------------------------------------------------------------
# _compute_copy_score
# ---------------------------------------------------------------------------


class TestComputeCopyScore:
    def test_high_quality_wallet(self):
        score = _compute_copy_score(pnl=1000, win_rate=0.65, trades=200, sharpe=2.0)
        assert score > 50

    def test_zero_pnl(self):
        score = _compute_copy_score(pnl=0, win_rate=0.50, trades=50, sharpe=0)
        assert score <= 25  # only trades/sharpe contribute

    def test_losing_wallet(self):
        score = _compute_copy_score(pnl=-500, win_rate=0.40, trades=100, sharpe=-0.5)
        assert score <= 0

    def test_floor_at_zero(self):
        score = _compute_copy_score(pnl=-9999, win_rate=0.10, trades=1, sharpe=-5)
        assert score >= 0


# ---------------------------------------------------------------------------
# WalletSelector
# ---------------------------------------------------------------------------


class TestWalletSelector:
    @pytest.mark.asyncio
    async def test_select_returns_cached(self):
        selector = WalletSelector("https://data-api.polymarket.com")
        selector._cache = [_make_wallet()]
        selector._cache_ts = 9999999999.0  # far future = never expire

        result = await selector.select()
        assert len(result) == 1
        assert result[0].address == "0xabc123"

    @pytest.mark.asyncio
    async def test_select_uses_scanner(self):
        selector = WalletSelector("https://data-api.polymarket.com")
        mock_trader = MagicMock()
        mock_trader.wallet = "0xdef456"
        mock_trader.proxy = None
        mock_trader.pnl = 800.0
        mock_trader.win_rate = 0.62
        mock_trader.total_trades = 200
        mock_trader.sharpe = 1.8

        with patch(
            "backend.core.wallet_scanner.find_profitable_traders",
            new_callable=AsyncMock,
            return_value=[mock_trader],
        ):
            result = await selector.select(min_trades=100, min_win_rate=0.55)

        assert len(result) == 1
        assert result[0].win_rate == 0.62

    @pytest.mark.asyncio
    async def test_select_filters_losers(self):
        selector = WalletSelector("https://data-api.polymarket.com")
        loser = MagicMock()
        loser.wallet = "0xbad"
        loser.proxy = None
        loser.pnl = -100.0
        loser.win_rate = 0.30
        loser.total_trades = 50
        loser.sharpe = -0.5

        with patch(
            "backend.core.wallet_scanner.find_profitable_traders",
            new_callable=AsyncMock,
            return_value=[loser],
        ):
            result = await selector.select()

        assert len(result) == 0


# ---------------------------------------------------------------------------
# TradeDetector
# ---------------------------------------------------------------------------


class TestTradeDetector:
    @pytest.mark.asyncio
    async def test_detect_returns_buys(self):
        detector = TradeDetector("https://data-api.polymarket.com")
        wallet = _make_wallet()
        events = [
            _make_activity_event(side="BUY"),
            _make_activity_event(side="SELL", tx_hash="tx_002"),
        ]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = events

        # Patch _fetch_new_trades directly — avoids httpx context manager complexity
        detector._fetch_new_trades = AsyncMock(return_value=events)
        signals = await detector.detect([wallet])

        assert len(signals) == 1
        assert signals[0].side == "BUY"

    @pytest.mark.asyncio
    async def test_fetch_skips_seen(self):
        """_fetch_new_trades filters out already-seen trade IDs."""
        detector = TradeDetector("https://data-api.polymarket.com")
        detector._seen["0xabc123"] = {"tx_001"}  # already seen

        events = [_make_activity_event(tx_hash="tx_001")]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = events

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await detector._fetch_new_trades("0xabc123", 300)

        assert len(result) == 0


# ---------------------------------------------------------------------------
# PositionCopier
# ---------------------------------------------------------------------------


class TestPositionCopier:
    def test_should_copy_first_time(self):
        copier = PositionCopier(max_copy_pct=0.05)
        signal = CopySignal(
            wallet="0xabc",
            condition_id="cond1",
            outcome="YES",
            side="BUY",
            price=0.65,
            size=50,
        )
        assert copier.should_copy(signal) is True

    def test_should_not_copy_duplicate(self):
        copier = PositionCopier(max_copy_pct=0.05)
        signal = CopySignal(
            wallet="0xabc",
            condition_id="cond1",
            outcome="YES",
            side="BUY",
            price=0.65,
            size=50,
        )
        copier.should_copy(signal)  # first time
        assert copier.should_copy(signal) is False  # duplicate

    def test_compute_size_caps_at_max_pct(self):
        copier = PositionCopier(max_copy_pct=0.05)
        signal = CopySignal(
            wallet="0xabc",
            condition_id="cond1",
            outcome="YES",
            side="BUY",
            price=0.65,
            size=50,
        )
        size = copier.compute_size(signal, bankroll=100.0)
        assert size == 5.0  # 5% of 100

    def test_compute_size_returns_zero_below_minimum(self):
        copier = PositionCopier(max_copy_pct=0.05)
        signal = CopySignal(
            wallet="0xabc",
            condition_id="cond1",
            outcome="YES",
            side="BUY",
            price=0.65,
            size=50,
        )
        size = copier.compute_size(signal, bankroll=10.0)  # 5% = $0.50 < $1 min
        assert size == 0.0

    def test_compute_size_zero_bankroll(self):
        copier = PositionCopier()
        signal = CopySignal(
            wallet="0xabc",
            condition_id="cond1",
            outcome="YES",
            side="BUY",
            price=0.65,
            size=50,
        )
        assert copier.compute_size(signal, bankroll=0) == 0.0


# ---------------------------------------------------------------------------
# CopyTraderStrategy.run_cycle
# ---------------------------------------------------------------------------


class TestCopyTraderStrategy:
    @pytest.mark.asyncio
    async def test_strategy_name_and_category(self):
        strategy = CopyTraderStrategy()
        assert strategy.name == "copy_trader"
        assert strategy.category == "copy"

    @pytest.mark.asyncio
    async def test_paper_mode_no_wallets(self):
        strategy = CopyTraderStrategy()
        ctx = _mock_ctx(mode="paper", bankroll=100)

        with patch.object(
            WalletSelector, "select", new_callable=AsyncMock, return_value=[]
        ):
            result = await strategy.run_cycle(ctx)

        assert result.decisions_recorded == 0
        assert result.trades_placed == 0

    @pytest.mark.asyncio
    async def test_paper_mode_copies_signal(self):
        strategy = CopyTraderStrategy()
        ctx = _mock_ctx(mode="paper", bankroll=100)

        wallet = _make_wallet()
        signal = CopySignal(
            wallet="0xabc123",
            condition_id="cond_test",
            outcome="YES",
            side="BUY",
            price=0.65,
            size=50,
            title="Test Market",
        )

        with (
            patch.object(
                WalletSelector, "select", new_callable=AsyncMock, return_value=[wallet]
            ),
            patch.object(
                TradeDetector, "detect", new_callable=AsyncMock, return_value=[signal]
            ),
        ):
            result = await strategy.run_cycle(ctx)

        assert result.decisions_recorded == 1
        assert result.trades_placed == 1
        assert result.trades_attempted == 1

    @pytest.mark.asyncio
    async def test_duplicate_signal_skipped(self):
        strategy = CopyTraderStrategy()
        ctx = _mock_ctx(mode="paper", bankroll=200)

        wallet = _make_wallet()
        signal = CopySignal(
            wallet="0xabc123",
            condition_id="cond_dup",
            outcome="YES",
            side="BUY",
            price=0.65,
            size=50,
        )

        with (
            patch.object(
                WalletSelector, "select", new_callable=AsyncMock, return_value=[wallet]
            ),
            patch.object(
                TradeDetector,
                "detect",
                new_callable=AsyncMock,
                return_value=[signal, signal],
            ),
        ):
            result = await strategy.run_cycle(ctx)

        # Second identical signal should be skipped
        assert result.decisions_recorded == 1

    @pytest.mark.asyncio
    async def test_default_params(self):
        strategy = CopyTraderStrategy()
        assert strategy.default_params["min_trades"] == 100
        assert strategy.default_params["min_win_rate"] == 0.55
        assert strategy.default_params["max_copy_pct"] == 0.05

    @pytest.mark.asyncio
    async def test_registry_auto_register(self):
        """Verify strategy auto-registers in registry."""
        from backend.strategies.registry import STRATEGY_REGISTRY

        assert "copy_trader" in STRATEGY_REGISTRY
        assert STRATEGY_REGISTRY["copy_trader"] is CopyTraderStrategy
