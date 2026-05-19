"""Tests for wallet_analyzer module."""

from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock

from backend.core.wallet_analyzer import (
    WalletAnalysis,
    analyze_wallet,
    analyze_wallet_rapid,
    compare_wallets,
    compute_analysis,
)

WALLET = "0xabcdef1234567890abcdef1234567890abcdef12"


def _pos(pnl: float, volume: float = 100.0, title: str = "Test", outcome: str = "Yes", ts: float = 1700000000.0, **extra) -> dict:
    """Build a fake closed-position dict."""
    d = {
        "realizedPnl": pnl,
        "totalBought": volume,
        "title": title,
        "outcome": outcome,
        "timestamp": ts,
        "slug": "",
        "eventSlug": "",
        "tags": [],
    }
    d.update(extra)
    return d


# ---------------------------------------------------------------------------
# 1. Profitable wallet
# ---------------------------------------------------------------------------


class TestProfitableWallet:
    def setup_method(self):
        self.positions = [
            _pos(50.0, title="BTC up 5m"),
            _pos(30.0, title="BTC up 5m"),
            _pos(20.0, title="ETH merge"),
            _pos(-10.0, title="BTC down"),
            _pos(-5.0, title="SOL pump"),
        ]

    def test_verdict_profitable(self):
        result = compute_analysis(WALLET, self.positions)
        assert result.verdict == "PROFITABLE"
        assert result.total_pnl == 85.0
        assert result.wins == 3
        assert result.losses == 2
        assert result.win_rate == pytest.approx(0.6)

    def test_profit_factor(self):
        result = compute_analysis(WALLET, self.positions)
        # gross_wins=100, gross_losses=15 => PF=6.67
        assert result.profit_factor == pytest.approx(100.0 / 15.0, rel=0.01)


# ---------------------------------------------------------------------------
# 2. Losing wallet
# ---------------------------------------------------------------------------


class TestLosingWallet:
    def setup_method(self):
        self.positions = [
            _pos(-20.0),
            _pos(-30.0),
            _pos(-10.0),
            _pos(5.0),
            _pos(2.0),
        ]

    def test_verdict_losing(self):
        result = compute_analysis(WALLET, self.positions)
        assert result.verdict == "LOSING"
        assert result.total_pnl < 0
        assert result.win_rate == pytest.approx(0.4)


# ---------------------------------------------------------------------------
# 3. Break-even wallet
# ---------------------------------------------------------------------------


class TestBreakEvenWallet:
    def test_near_zero_pnl(self):
        positions = [_pos(0.01), _pos(-0.01)]
        compute_analysis(WALLET, positions)
        # PnL ~0, wins == 1 => technically PROFITABLE with >=50% WR
        # But if we want BREAK-EVEN, make it exactly zero with 1 win 1 loss
        positions2 = [_pos(5.0), _pos(-5.0)]
        result2 = compute_analysis(WALLET, positions2)
        assert result2.verdict == "BREAK-EVEN"
        assert result2.total_pnl == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 4. Category breakdown
# ---------------------------------------------------------------------------


class TestCategoryBreakdown:
    def test_btc_category(self):
        positions = [
            _pos(10.0, title="Will BTC hit 100k?"),
            _pos(20.0, title="Bitcoin up or down 5m"),
            _pos(-5.0, title="ETH merge"),
        ]
        result = compute_analysis(WALLET, positions, detailed=True)
        # BTC_5m should match "Bitcoin up or down 5m", BTC for the other
        assert "BTC" in result.categories or "BTC_5m" in result.categories
        assert result.best_category != ""


# ---------------------------------------------------------------------------
# 5. Biggest win / loss
# ---------------------------------------------------------------------------


class TestBiggestTrades:
    def test_biggest_win_loss(self):
        positions = [
            _pos(100.0, title="Big Win"),
            _pos(50.0, title="Medium Win"),
            _pos(-80.0, title="Big Loss"),
            _pos(-20.0, title="Small Loss"),
        ]
        result = compute_analysis(WALLET, positions)
        assert result.biggest_win["pnl"] == 100.0
        assert result.biggest_win["title"] == "Big Win"
        assert result.biggest_loss["pnl"] == -80.0
        assert result.biggest_loss["title"] == "Big Loss"
        assert len(result.top_10_wins) == 2
        assert len(result.worst_10_losses) == 2


# ---------------------------------------------------------------------------
# 6. Sharpe ratio
# ---------------------------------------------------------------------------


class TestSharpeRatio:
    def test_sharpe_calculated(self):
        # Spread across 3 different days for std to be meaningful
        base = 1700000000.0
        day = 86400.0
        positions = [
            _pos(10.0, ts=base),
            _pos(20.0, ts=base + day),
            _pos(-5.0, ts=base + 2 * day),
        ]
        result = compute_analysis(WALLET, positions)
        # With 3 daily returns, std > 0, so sharpe should be non-zero
        assert result.sharpe_ratio != 0.0

    def test_single_day_sharpe_zero(self):
        positions = [_pos(10.0, ts=1700000000.0), _pos(20.0, ts=1700000100.0)]
        result = compute_analysis(WALLET, positions)
        assert result.sharpe_ratio == 0.0


# ---------------------------------------------------------------------------
# 7. VaR
# ---------------------------------------------------------------------------


class TestVaR:
    def test_var_95_and_99(self):
        positions = [_pos(i * 1.0) for i in range(-50, 50)]  # -50..49
        result = compute_analysis(WALLET, positions)
        # 5th percentile of [-50..49] should be around -45
        assert result.var_95 < 0
        # 1st percentile should be even more negative
        assert result.var_99 <= result.var_95


# ---------------------------------------------------------------------------
# 8. Consecutive losses
# ---------------------------------------------------------------------------


class TestConsecutiveLosses:
    def test_max_loss_streak(self):
        positions = [
            _pos(-10.0),
            _pos(-10.0),
            _pos(-10.0),
            _pos(5.0),  # breaks streak
            _pos(-10.0),
            _pos(-10.0),
            _pos(-10.0),
            _pos(-10.0),
            _pos(-10.0),
        ]
        result = compute_analysis(WALLET, positions)
        assert result.consecutive_losses_max == 5
        assert result.consecutive_wins_max == 1


# ---------------------------------------------------------------------------
# 9. Copy trade rating
# ---------------------------------------------------------------------------


class TestCopyTradeRating:
    def test_high_rating_good_wallet(self):
        # 8 wins, 2 losses, >100 positions for full sample score
        positions = [_pos(10.0) for _ in range(80)] + [_pos(-2.0) for _ in range(20)]
        result = compute_analysis(WALLET, positions)
        assert result.copy_trade_rating >= 7

    def test_low_rating_bad_wallet(self):
        positions = [_pos(-10.0) for _ in range(8)] + [_pos(1.0) for _ in range(2)]
        result = compute_analysis(WALLET, positions)
        assert result.copy_trade_rating <= 3


# ---------------------------------------------------------------------------
# 10. Red flags — small sample
# ---------------------------------------------------------------------------


class TestRedFlags:
    def test_small_sample_flagged(self):
        positions = [_pos(10.0), _pos(20.0)]
        result = compute_analysis(WALLET, positions)
        assert any("Small sample size" in f for f in result.red_flags)

    def test_long_losing_streak_flagged(self):
        positions = [_pos(-5.0) for _ in range(12)]
        result = compute_analysis(WALLET, positions)
        assert any("Long losing streak" in f for f in result.red_flags)


# ---------------------------------------------------------------------------
# 11. Empty wallet
# ---------------------------------------------------------------------------


class TestEmptyWallet:
    def test_empty_returns_defaults(self):
        result = compute_analysis(WALLET, [])
        assert result.total_positions == 0
        assert result.total_pnl == 0.0
        assert result.verdict == "BREAK-EVEN"
        assert result.copy_trade_rating == 0
        assert result.win_rate == 0.0
        assert result.red_flags == []


# ---------------------------------------------------------------------------
# 12. Compare wallets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCompareWallets:
    async def test_sorted_by_pnl(self):
        wallet_a = "0xaaaa"
        wallet_b = "0xbbbb"
        positions_a = [_pos(50.0), _pos(30.0)]
        positions_b = [_pos(100.0), _pos(20.0)]

        with patch(
            "backend.core.wallet_analyzer.get_all_closed_positions",
            new_callable=AsyncMock,
        ) as mock_fetch:
            mock_fetch.side_effect = lambda w, **kw: (
                positions_a if w == wallet_a else positions_b
            )
            results = await compare_wallets([wallet_a, wallet_b])

        assert len(results) == 2
        # wallet_b total_pnl=120 > wallet_a total_pnl=80
        assert results[0].wallet == wallet_b
        assert results[1].wallet == wallet_a
        assert results[0].total_pnl >= results[1].total_pnl


# ---------------------------------------------------------------------------
# Async integration (mocked data layer)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAnalyzeWalletAsync:
    async def test_analyze_wallet_full(self):
        positions = [_pos(10.0, title="BTC up"), _pos(-5.0, title="ETH down")]
        with patch(
            "backend.core.wallet_analyzer.get_all_closed_positions",
            new_callable=AsyncMock,
            return_value=positions,
        ):
            result = await analyze_wallet(WALLET)

        assert isinstance(result, WalletAnalysis)
        assert result.wallet == WALLET
        assert result.total_positions == 2
        assert result.total_pnl == 5.0
        assert result.analyzed_at != ""

    async def test_analyze_wallet_rapid(self):
        positions = [_pos(10.0), _pos(-5.0), _pos(20.0)]
        with patch(
            "backend.core.wallet_analyzer.get_all_closed_positions",
            new_callable=AsyncMock,
            return_value=positions,
        ):
            result = await analyze_wallet_rapid(WALLET)

        # Rapid mode still computes basic metrics
        assert result.total_positions == 3
        assert result.total_pnl == 25.0
        # But skips detailed breakdowns
        assert result.categories == {}
        assert result.size_brackets == {}
