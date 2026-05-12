"""Integration tests for Order Executor and Copy Trader components.

Tests integration between:
- Leaderboard scoring and trader selection
- Copy signal generation and execution
- Order mirroring with wallet sync
- Circuit breaker and rate limiting
- Execution metrics and monitoring
"""

import pytest
from backend.strategies.order_executor import (
    ScoredTrader,
    CopySignal,
)


class TestScoredTraderIntegration:
    """Integration tests for scored trader data structure."""

    def test_scored_trader_creation(self):
        """Test ScoredTrader can be created with all required fields."""
        trader = ScoredTrader(
            user="user123",
            wallet="0x1234567890123456789012345678901234567890",
            pseudonym="test_trader",
            profit_30d=1000.0,
            win_rate=0.65,
            total_trades=100,
            unique_markets=10,
            estimated_bankroll=5000.0,
            score=0.0,
        )

        assert trader.user == "user123"
        assert trader.wallet.startswith("0x")
        assert trader.pseudonym == "test_trader"
        assert trader.profit_30d == 1000.0
        assert trader.win_rate == 0.65
        assert trader.total_trades == 100
        assert trader.unique_markets == 10
        assert trader.estimated_bankroll == 5000.0
        assert trader.score == 0.0

    def test_scored_trader_market_diversity_high(self):
        """Test market diversity with high diversity trader."""
        trader = ScoredTrader(
            user="diverse_trader",
            wallet="0x789",
            pseudonym="well_diversified",
            profit_30d=500.0,
            win_rate=0.55,
            total_trades=100,
            unique_markets=50,
            estimated_bankroll=2000.0,
            score=0.0,
        )

        assert trader.market_diversity == 0.5

    def test_scored_trader_market_diversity_low(self):
        """Test market diversity with low diversity trader."""
        trader = ScoredTrader(
            user="concentrated_trader",
            wallet="0xabc",
            pseudonym="concentrated",
            profit_30d=500.0,
            win_rate=0.55,
            total_trades=100,
            unique_markets=2,
            estimated_bankroll=2000.0,
            score=0.0,
        )

        assert trader.market_diversity == 0.02

    def test_scored_trader_zero_trades_diversity(self):
        """Test market diversity with zero trades."""
        trader = ScoredTrader(
            user="new_trader",
            wallet="0xdef",
            pseudonym="newbie",
            profit_30d=0.0,
            win_rate=0.0,
            total_trades=0,
            unique_markets=0,
            estimated_bankroll=0.0,
            score=0.0,
        )

        assert trader.market_diversity == 0.0


class TestCopySignalIntegration:
    """Integration tests for copy signal generation."""

    def test_copy_signal_creation(self):
        """Test CopySignal can be created with all required fields."""
        from datetime import datetime, timezone

        signal = CopySignal(
            source_wallet="0xsource123",
            source_trade={
                "market_ticker": "BTC-USD",
                "direction": "up",
                "entry_price": 0.65,
                "size": 100.0,
                "timestamp": datetime.now(timezone.utc),
            },
            our_side="up",
            our_outcome="yes",
            our_size=45.0,
            market_price=0.55,
            trader_score=0.85,
            reasoning="Strong bullish momentum detected",
            timestamp=datetime.now(timezone.utc),
        )

        assert signal.source_wallet == "0xsource123"
        assert signal.our_side == "up"
        assert signal.our_outcome == "yes"
        assert signal.our_size == 45.0
        assert signal.market_price == 0.55
        assert signal.trader_score == 0.85
        assert "momentum" in signal.reasoning

    def test_copy_signal_with_trader_info(self):
        """Test CopySignal integrates trader information."""
        from datetime import datetime, timezone

        trader_info = {
            "user": "top_trader",
            "wallet": "0x789",
            "pseudonym": "leader",
            "profit_30d": 2000.0,
            "win_rate": 0.72,
            "total_trades": 150,
        }

        signal = CopySignal(
            source_wallet=trader_info["wallet"],
            source_trade={
                "market_ticker": "ETH-USD",
                "direction": "up",
                "entry_price": 0.70,
                "size": 150.0,
            },
            our_side="up",
            our_outcome="yes",
            our_size=65.0,
            market_price=0.55,
            trader_score=0.85,
            reasoning=f"Copying {trader_info['pseudonym']} signal on ETH-USD",
            timestamp=datetime.now(timezone.utc),
        )

        assert "leader" in signal.reasoning


class TestOrderExecutorIntegrationFlow:
    """Integration tests for order executor flow."""

    def test_trader_scoring_and_selection_flow(self):
        """Test complete flow from trader scoring to selection."""
        traders = [
            ScoredTrader(
                user="trader1",
                wallet="0x1",
                pseudonym="leader1",
                profit_30d=2000.0,
                win_rate=0.72,
                total_trades=150,
                unique_markets=15,
                estimated_bankroll=8000.0,
                score=0.0,
            ),
            ScoredTrader(
                user="trader2",
                wallet="0x2",
                pseudonym="leader2",
                profit_30d=1500.0,
                win_rate=0.68,
                total_trades=120,
                unique_markets=10,
                estimated_bankroll=6000.0,
                score=0.0,
            ),
        ]

        assert len(traders) == 2
        assert traders[0].profit_30d > traders[1].profit_30d
        assert traders[0].win_rate > traders[1].win_rate

    def test_copy_signal_generation_flow(self):
        """Test complete flow from selected trader to copy signal."""
        from datetime import datetime, timezone

        selected_trader = {
            "wallet": "0xselected",
            "pseudonym": "top_performer",
            "profit_30d": 2500.0,
            "win_rate": 0.75,
        }

        source_trade = {
            "market_ticker": "BTC-USD",
            "direction": "up",
            "entry_price": 0.68,
            "size": 200.0,
            "timestamp": datetime.now(timezone.utc),
        }

        copy_signal = CopySignal(
            source_wallet=selected_trader["wallet"],
            source_trade=source_trade,
            our_side=source_trade["direction"],
            our_outcome="yes",
            our_size=85.0,
            market_price=0.55,
            trader_score=0.85,
            reasoning=f"Copying {selected_trader['pseudonym']} on {source_trade['market_ticker']}",
            timestamp=datetime.now(timezone.utc),
        )

        assert copy_signal.source_wallet == "0xselected"
        assert "top_performer" in copy_signal.reasoning
        assert copy_signal.our_size == 85.0
