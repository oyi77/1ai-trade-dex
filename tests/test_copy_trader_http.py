"""
HTTP-layer tests for LeaderboardScorer and CopyTrader lifecycle.
Uses AsyncMock to simulate httpx responses without network calls.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock


# ============================================================================
# LeaderboardScorer.fetch_and_score
# ============================================================================

class TestLeaderboardScorerHTTP:
    def _make_http(self, entries):
        mock_http = AsyncMock()
        resp = MagicMock()
        resp.json.return_value = entries
        resp.raise_for_status = MagicMock()
        mock_http.get = AsyncMock(return_value=resp)
        return mock_http

    @pytest.mark.asyncio
    async def test_fetch_returns_sorted_traders(self):
        from backend.modules.execution.copy_trader import LeaderboardScorer

        entries = [
            {"proxyWallet": "0xlow", "name": "Low", "profit": 1000, "pnlPercentage": 40, "tradesCount": 20, "marketsTraded": 5},
            {"proxyWallet": "0xhigh", "name": "High", "profit": 50000, "pnlPercentage": 70, "tradesCount": 200, "marketsTraded": 150},
        ]
        scorer = LeaderboardScorer(self._make_http(entries))
        traders = await scorer.fetch_and_score(top_n=50)

        assert len(traders) == 2
        # Higher profit/win_rate/diversity trader should rank first
        assert traders[0].wallet == "0xhigh"
        assert traders[0].score > traders[1].score

    @pytest.mark.asyncio
    async def test_fetch_empty_leaderboard_returns_empty(self):
        from backend.modules.execution.copy_trader import LeaderboardScorer
        scorer = LeaderboardScorer(self._make_http([]))
        traders = await scorer.fetch_and_score()
        assert traders == []

    @pytest.mark.asyncio
    async def test_fetch_http_error_returns_empty(self):
        from backend.modules.execution.copy_trader import LeaderboardScorer
        from unittest.mock import patch
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(side_effect=Exception("timeout"))
        scorer = LeaderboardScorer(mock_http)
        # Also patch the scraper fallback so both data sources fail
        with patch(
            "backend.data.polymarket_scraper.fetch_real_leaderboard",
            new_callable=AsyncMock,
            side_effect=Exception("scraper also failed"),
        ):
            traders = await scorer.fetch_and_score()
        assert traders == []

    @pytest.mark.asyncio
    async def test_win_rate_clamped_to_one(self):
        """pnlPercentage > 100 doesn't produce win_rate > 1.0."""
        from backend.modules.execution.copy_trader import LeaderboardScorer
        entries = [
            {"proxyWallet": "0xa", "name": "A", "profit": 5000,
             "pnlPercentage": 150, "tradesCount": 30, "marketsTraded": 20}
        ]
        scorer = LeaderboardScorer(self._make_http(entries))
        traders = await scorer.fetch_and_score()
        assert traders[0].win_rate <= 1.0

    @pytest.mark.asyncio
    async def test_top_n_limit_respected(self):
        from backend.modules.execution.copy_trader import LeaderboardScorer
        entries = [
            {"proxyWallet": f"0x{i}", "name": f"T{i}", "profit": i * 100,
             "pnlPercentage": 50, "tradesCount": 10, "marketsTraded": 5}
            for i in range(20)
        ]
        scorer = LeaderboardScorer(self._make_http(entries))
        traders = await scorer.fetch_and_score(top_n=5)
        assert len(traders) == 5


# ============================================================================
# CopyTrader.poll_once
# ============================================================================

class TestCopyTraderPollOnce:
    """Test poll_once by injecting a pre-configured watcher and scorer."""

    @pytest.mark.asyncio
    async def test_poll_once_returns_signals_from_new_buys(self):
        from backend.modules.execution.copy_trader import (
            CopyTrader, ScoredTrader, WalletTrade
        )

        ct = CopyTrader(bankroll=1000.0, max_wallets=5, min_score=50.0)

        # Bypass start() by injecting mocks
        ct._running = True
        ct._last_refresh = asyncio.get_event_loop().time()

        trader = ScoredTrader(user="test_user", 
            wallet="0xtrader", pseudonym="Test",
            profit_30d=10000, win_rate=0.65, total_trades=100,
            unique_markets=60, estimated_bankroll=20000.0, score=80.0,
        )
        ct._tracked = [trader]

        mock_watcher = AsyncMock()
        mock_trade = WalletTrade(user="test_user", 
            wallet="0xtrader", condition_id="cond1", outcome="YES",
            side="BUY", price=0.55, size=500.0, timestamp="2026-01-01T00:00:00Z",
        )
        mock_watcher.poll = AsyncMock(return_value=([mock_trade], []))
        ct._watcher = mock_watcher

        signals = await ct.poll_once()

        assert len(signals) == 1
        assert signals[0].our_side == "YES"
        assert signals[0].our_outcome == "YES"
        # 500/20000 * 1000 = 25.0, capped at 5% of 1000 = 50.0 → 25.0
        assert abs(signals[0].our_size - 25.0) < 0.01

    @pytest.mark.asyncio
    async def test_poll_once_returns_exit_signal(self):
        from backend.modules.execution.copy_trader import (
            CopyTrader, ScoredTrader, WalletTrade
        )

        ct = CopyTrader(bankroll=1000.0)
        ct._running = True
        ct._last_refresh = asyncio.get_event_loop().time()

        trader = ScoredTrader(user="test_user", 
            wallet="0xtrader", pseudonym="T",
            profit_30d=5000, win_rate=0.6, total_trades=50,
            unique_markets=30, estimated_bankroll=10000.0, score=70.0,
        )
        ct._tracked = [trader]

        sell_trade = WalletTrade(user="test_user", 
            wallet="0xtrader", condition_id="cond2", outcome="YES",
            side="SELL", price=0.80, size=300.0, timestamp="t",
        )
        mock_watcher = AsyncMock()
        mock_watcher.poll = AsyncMock(return_value=([], [sell_trade]))
        ct._watcher = mock_watcher

        signals = await ct.poll_once()

        assert len(signals) == 1
        assert signals[0].our_side == "SELL"

    @pytest.mark.asyncio
    async def test_poll_once_skips_trader_on_exception(self):
        """A failing wallet poll doesn't crash the whole cycle."""
        from backend.modules.execution.copy_trader import CopyTrader, ScoredTrader

        ct = CopyTrader(bankroll=500.0)
        ct._running = True
        ct._last_refresh = asyncio.get_event_loop().time()

        trader = ScoredTrader(user="test_user", 
            wallet="0xbad", pseudonym="Bad",
            profit_30d=1000, win_rate=0.5, total_trades=20,
            unique_markets=10, estimated_bankroll=5000.0, score=65.0,
        )
        ct._tracked = [trader]

        mock_watcher = AsyncMock()
        mock_watcher.poll = AsyncMock(side_effect=Exception("network error"))
        ct._watcher = mock_watcher

        signals = await ct.poll_once()
        assert signals == []  # Gracefully returns empty

    @pytest.mark.asyncio
    async def test_poll_once_triggers_leaderboard_refresh_after_6h(self):
        """poll_once calls _refresh_leaderboard when >6h since last refresh."""
        from backend.modules.execution.copy_trader import CopyTrader

        ct = CopyTrader(bankroll=1000.0)
        ct._running = True
        ct._last_refresh = -float("inf")  # force stale (always > 6h ago)
        ct._tracked = []

        refresh_called = []

        async def mock_refresh():
            refresh_called.append(True)

        ct._refresh_leaderboard = mock_refresh
        ct._watcher = AsyncMock()
        ct._watcher.poll = AsyncMock(return_value=([], []))

        await ct.poll_once()
        assert len(refresh_called) == 1


# ============================================================================
# CopyTrader._mirror_buy edge cases
# ============================================================================

class TestMirrorBuyEdgeCases:
    def _make_trader(self, bankroll=10000.0, score=75.0):
        from backend.modules.execution.copy_trader import ScoredTrader
        return ScoredTrader(user="test_user", 
            wallet="0xtest", pseudonym="T",
            profit_30d=5000, win_rate=0.6, total_trades=30,
            unique_markets=20, estimated_bankroll=bankroll, score=score,
        )

    def _make_trade(self, size=200.0):
        from backend.modules.execution.copy_trader import WalletTrade
        return WalletTrade(user="test_user", 
            wallet="0xtest", condition_id="cond", outcome="YES",
            side="BUY", price=0.45, size=size, timestamp="t",
        )

    def test_zero_bankroll_returns_none(self):
        from backend.modules.execution.copy_trader import CopyTrader
        ct = CopyTrader(bankroll=500.0)
        trader = self._make_trader(bankroll=0.0)
        assert ct._mirror_buy(trader, self._make_trade()) is None

    def test_tiny_trade_below_minimum_returns_none(self):
        from backend.modules.execution.copy_trader import CopyTrader
        ct = CopyTrader(bankroll=100.0)
        # 0.1 / 10000 * 100 = 0.001 → below $1 min
        assert ct._mirror_buy(self._make_trader(), self._make_trade(size=0.1)) is None

    def test_reasoning_contains_trader_name(self):
        from backend.modules.execution.copy_trader import CopyTrader
        ct = CopyTrader(bankroll=1000.0)
        signal = ct._mirror_buy(self._make_trader(), self._make_trade(200.0))
        assert "T" in signal.reasoning
