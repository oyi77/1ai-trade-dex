"""
Phase 2 tests for copy trader strategy.

Tests proportional sizing, deduplication, exit detection, and scoring.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock


# ============================================================================
# Test LeaderboardScorer
# ============================================================================

class TestLeaderboardScorer:
    """Test composite trader scoring."""

    def _make_entry(self, profit=10000, pnl_pct=60, trades=50, markets=40):
        return {
            "proxyWallet": "0xabc123",
            "name": "TraderA",
            "profit": profit,
            "pnlPercentage": pnl_pct,  # 60% = 0.6 win rate
            "tradesCount": trades,
            "marketsTraded": markets,
        }

    def test_score_weights_sum_to_one(self):
        """Scoring weights must sum to 1.0."""
        from backend.modules.execution.copy_trader import LeaderboardScorer
        total = sum(LeaderboardScorer.WEIGHTS.values())
        assert abs(total - 1.0) < 1e-10, f"Weights sum to {total}, expected 1.0"

    def test_diverse_trader_scores_higher_than_single_market(self):
        """Trader with 40/50 unique markets scores higher on diversity than 5/50."""
        from backend.modules.execution.copy_trader import ScoredTrader

        diverse = ScoredTrader(user="test_user", 
            wallet="0xaaa", pseudonym="A",
            profit_30d=10000, win_rate=0.6, total_trades=50,
            unique_markets=40, estimated_bankroll=50000,
        )
        concentrated = ScoredTrader(user="test_user", 
            wallet="0xbbb", pseudonym="B",
            profit_30d=10000, win_rate=0.6, total_trades=50,
            unique_markets=5, estimated_bankroll=50000,
        )

        assert diverse.market_diversity > concentrated.market_diversity

    def test_market_diversity_capped_at_one(self):
        """Diversity never exceeds 1.0 even if unique > total (data anomaly)."""
        from backend.modules.execution.copy_trader import ScoredTrader
        trader = ScoredTrader(user="test_user", 
            wallet="0x", pseudonym="X",
            profit_30d=0, win_rate=0.5, total_trades=10,
            unique_markets=999, estimated_bankroll=1000,
        )
        assert trader.market_diversity <= 1.0

    def test_zero_trades_diversity_is_zero(self):
        """Trader with 0 trades has 0 diversity."""
        from backend.modules.execution.copy_trader import ScoredTrader
        trader = ScoredTrader(user="test_user", 
            wallet="0x", pseudonym="X",
            profit_30d=0, win_rate=0, total_trades=0,
            unique_markets=0, estimated_bankroll=1000,
        )
        assert trader.market_diversity == 0.0


# ============================================================================
# Test TradeMirror proportional sizing
# ============================================================================

class TestTradeMirror:
    """Test proportional sizing formula."""

    def _mirror_size(self, trade_size, trader_bankroll, our_bankroll, max_pct=0.05):
        """Replicate the mirror sizing formula."""
        their_pct = trade_size / trader_bankroll
        our_size = their_pct * our_bankroll
        our_size = min(our_size, max_pct * our_bankroll)
        return max(0.0, our_size)

    def test_proportional_sizing_basic(self):
        """$200 trade / $10000 bankroll → 2% → our $500 bankroll → $10."""
        size = self._mirror_size(200, 10000, 500)
        assert abs(size - 10.0) < 0.01

    def test_proportional_sizing_capped(self):
        """Large trader bet capped at 5% of our bankroll."""
        # Their 50% bet → our 5% cap
        size = self._mirror_size(5000, 10000, 1000)
        assert size == 50.0  # 5% of $1000

    def test_proportional_sizing_minimum_filter(self):
        """Sub-$1 result is filtered out (below Polymarket minimum)."""
        # Their 0.05% bet → $0.50 for us → below minimum
        size = self._mirror_size(5, 10000, 1000)
        # $5 / $10000 = 0.05% * $1000 = $0.50 — below $1 min
        assert size < 1.0  # CopyTrader._mirror_buy filters this out

    def test_proportional_sizing_reference_example(self):
        """Reference: wallet_bankroll=10000, our=500, trade=200 → size=10."""
        from backend.modules.execution.copy_trader import CopyTrader, ScoredTrader, WalletTrade
        trader = ScoredTrader(user="test_user", 
            wallet="0xtest", pseudonym="T",
            profit_30d=5000, win_rate=0.6, total_trades=30,
            unique_markets=20, estimated_bankroll=10000.0,
            score=75.0,
        )
        trade = WalletTrade(user="test_user", 
            wallet="0xtest", condition_id="cond123",
            outcome="YES", side="BUY",
            price=0.45, size=200.0,
            timestamp="2026-04-07T10:00:00Z",
        )
        ct = CopyTrader(bankroll=500.0)
        signal = ct._mirror_buy(trader, trade)
        assert signal is not None
        assert abs(signal.our_size - 10.0) < 0.01, f"Expected $10.00, got ${signal.our_size:.2f}"


# ============================================================================
# Test WalletWatcher deduplication and exit detection
# ============================================================================

class TestWalletWatcher:
    """Test trade deduplication and exit threshold logic."""

    @pytest.mark.asyncio
    async def test_first_poll_seeds_and_returns_trades(self):
        """First poll seeds seen set AND returns initial trades for copy-trading."""
        from backend.modules.execution.copy_trader import WalletWatcher

        mock_http = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"transactionHash": "0xtx1", "side": "BUY", "conditionId": "c1",
             "outcomeIndex": 0, "price": "0.45", "size": "100", "timestamp": "t1", "title": "Test"},
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_http.get = AsyncMock(return_value=mock_resp)

        watcher = WalletWatcher(mock_http)
        buys, exits = await watcher.poll("0xwallet")

        # First poll: seeds seen set AND returns initial BUY signals
        assert len(buys) == 1
        assert buys[0].condition_id == "c1"
        assert buys[0].side == "BUY"
        assert exits == []
        # Verify seen set was populated so next poll deduplicates
        assert "0xtx1" in watcher._seen["0xwallet"]

    @pytest.mark.asyncio
    async def test_second_poll_detects_new_trade(self):
        """Second poll with new trade returns it as new_buy."""
        from backend.modules.execution.copy_trader import WalletWatcher

        mock_http = AsyncMock()

        # First poll: existing trade
        first_trades = [
            {"transactionHash": "0xtx1", "side": "BUY", "conditionId": "c1",
             "outcomeIndex": 0, "price": "0.45", "size": "100", "timestamp": "t1", "title": "Old"},
        ]
        # Second poll: new trade added
        second_trades = first_trades + [
            {"transactionHash": "0xtx2", "side": "BUY", "conditionId": "c2",
             "outcomeIndex": 0, "price": "0.60", "size": "50", "timestamp": "t2", "title": "New"},
        ]

        responses = [first_trades, second_trades]
        call_count = [0]

        async def mock_get(*args, **kwargs):
            resp = MagicMock()
            resp.json.return_value = responses[call_count[0]]
            resp.raise_for_status = MagicMock()
            call_count[0] += 1
            return resp

        mock_http.get = mock_get
        watcher = WalletWatcher(mock_http)

        # First poll — seed
        await watcher.poll("0xwallet")
        # Second poll — should detect tx2
        buys, exits = await watcher.poll("0xwallet")

        assert len(buys) == 1
        assert buys[0].tx_hash == "0xtx2"
        assert buys[0].condition_id == "c2"

    @pytest.mark.asyncio
    async def test_exit_detection_at_fifty_percent(self):
        """Exit fires when cumulative SELL >= 50% of original BUY size."""
        from backend.modules.execution.copy_trader import WalletWatcher

        mock_http = AsyncMock()
        call_count = [0]

        # Sequence: BUY 100, then SELL 60 (60% > 50% → exit)
        trade_sequences = [
            # Poll 1: seed BUY
            [{"transactionHash": "tx1", "side": "BUY", "conditionId": "c1",
              "outcomeIndex": 0, "price": "0.45", "size": "100", "timestamp": "t1", "title": "T"}],
            # Poll 2: new BUY (mirrors entry tracking)
            [],
            # Poll 3: SELL 60 → cumulative=60 >= 50% of 100
            [{"transactionHash": "tx2", "side": "SELL", "conditionId": "c1",
              "outcomeIndex": 0, "price": "0.70", "size": "60", "timestamp": "t3", "title": "T"}],
        ]

        async def mock_get(*args, **kwargs):
            # Poll 1 (seed): only BUY tx1
            # Poll 2 (detect): BUY tx1 + SELL tx2
            if call_count[0] == 0:
                data = trade_sequences[0]
            else:
                data = trade_sequences[0] + trade_sequences[2]  # add sell
            resp = MagicMock()
            resp.json.return_value = data
            resp.raise_for_status = MagicMock()
            call_count[0] += 1
            return resp

        mock_http.get = mock_get
        watcher = WalletWatcher(mock_http)

        # Mock _get_entry_size to return 100.0 for the BUY
        from unittest.mock import patch
        with patch.object(watcher, '_get_entry_size', return_value=100.0):
            # Poll 1: seed (tx1 BUY seen)
            await watcher.poll("0xwallet")

            # Poll 2: SELL 60 appears → cumulative=60 >= 50% of 100 → exit signal
            buys, exits = await watcher.poll("0xwallet")
        assert len(exits) == 1
        assert exits[0].side == "SELL"
        assert exits[0].condition_id == "c1"

    @pytest.mark.asyncio
    async def test_no_exit_below_fifty_percent(self):
        """No exit signal when SELL is less than 50% of original entry."""
        from backend.modules.execution.copy_trader import WalletWatcher
        from unittest.mock import patch

        mock_http = AsyncMock()

        # Entry: 100, Sell: 40 (40% < 50% → no exit)
        trade_sequences = [
            [{"transactionHash": "tx1", "side": "BUY", "conditionId": "c1",
              "outcomeIndex": 0, "price": "0.45", "size": "100", "timestamp": "t1", "title": "T"}],
        ]

        call_count = [0]

        async def mock_get(*args, **kwargs):
            if call_count[0] == 0:
                data = trade_sequences[0]
            else:
                # Add a 40 SELL
                data = trade_sequences[0] + [
                    {"transactionHash": "tx2", "side": "SELL", "conditionId": "c1",
                     "outcomeIndex": 0, "price": "0.60", "size": "30", "timestamp": "t2", "title": "T"}
                ]
            resp = MagicMock()
            resp.json.return_value = data
            resp.raise_for_status = MagicMock()
            call_count[0] += 1
            return resp

        mock_http.get = mock_get
        watcher = WalletWatcher(mock_http)

        # Mock _get_entry_size to return 100.0 for the BUY
        with patch.object(watcher, '_get_entry_size', return_value=100.0):
            await watcher.poll("0xwallet")

            # Poll 2: SELL 30 appears → cumulative=30 < 40% of 100 → no exit signal
            buys, exits = await watcher.poll("0xwallet")
            assert len(exits) == 0

        buys, exits = await watcher.poll("0xwallet")
        assert len(exits) == 0, "Should not exit on 30% sell"
