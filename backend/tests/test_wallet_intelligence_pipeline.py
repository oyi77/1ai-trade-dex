"""Tests for wallet_intelligence_pipeline module."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest

from backend.core.wallet_intelligence_pipeline import (
    PipelineResult,
    WalletCandidate,
    format_report,
    run_pipeline,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _trader(wallet: str = "0xaaaa", pnl: float = 100.0) -> object:
    """Build a minimal TraderScore-like object."""

    @dataclass
    class FakeTrader:
        wallet: str
        proxy: str = ""
        pnl: float = 0.0
        win_rate: float = 0.0
        total_trades: int = 0
        volume: float = 0.0
        sharpe: float = 0.0
        source_method: str = ""

    return FakeTrader(wallet=wallet, pnl=pnl, volume=5000, total_trades=60)


def _positions(n: int = 30) -> list[dict]:
    """Build n fake closed-position dicts."""
    return [
        {
            "realizedPnl": 5.0,
            "totalBought": 100.0,
            "title": "BTC up",
            "outcome": "Yes",
            "side": "BUY",
            "avgPrice": 0.55,
            "timestamp": 1700000000.0 + i * 3600,
            "slug": "",
            "eventSlug": "",
        }
        for i in range(n)
    ]


def _wallet_info(proxy: str = "0xbbbb"):
    """Build a minimal WalletInfo-like object."""

    @dataclass
    class FakeWalletInfo:
        eoa: str = ""
        proxy: str = ""
        username: str = ""
        method: str = ""
        is_proxy: bool = False
        has_traded: bool = False

    return FakeWalletInfo(proxy=proxy, method="test")


def _analysis(
    pnl: float = 500.0,
    win_rate: float = 0.6,
    positions: int = 100,
    sharpe: float = 1.5,
    rating: int = 7,
):
    """Build a minimal WalletAnalysis-like object."""

    @dataclass
    class FakeAnalysis:
        total_pnl: float = 0.0
        win_rate: float = 0.0
        total_positions: int = 0
        sharpe_ratio: float = 0.0
        copy_trade_rating: int = 0

    return FakeAnalysis(
        total_pnl=pnl,
        win_rate=win_rate,
        total_positions=positions,
        sharpe_ratio=sharpe,
        copy_trade_rating=rating,
    )


def _fingerprint(
    strategy_type: str = "SWING", confidence: float = 0.7, replicable: bool = True
):
    """Build a minimal StrategyFingerprint-like object."""

    @dataclass
    class FakeFP:
        strategy_type: str = "MIXED"
        confidence: float = 0.0
        is_replicable: bool = False

    return FakeFP(strategy_type=strategy_type, confidence=confidence, is_replicable=replicable)


def _replication(
    rules: int = 3,
    paper_pnl: float = 50.0,
    ready: bool = True,
):
    """Build a minimal ReplicatedStrategy-like object."""

    @dataclass
    class FakeReplication:
        rules: list = None
        paper_results: dict = None
        is_ready_for_live: bool = False

        def __post_init__(self):
            if self.rules is None:
                self.rules = [{}] * rules
            if self.paper_results is None:
                self.paper_results = {"pnl": paper_pnl}

    return FakeReplication(is_ready_for_live=ready)


# ---------------------------------------------------------------------------
# 1. Empty scan result -> returns empty pipeline result
# ---------------------------------------------------------------------------


class TestEmptyScan:
    @pytest.mark.asyncio
    async def test_no_traders_returns_empty_result(self):
        with patch(
            "backend.core.wallet_intelligence_pipeline.find_profitable_traders",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await run_pipeline()

        assert result.wallets_scanned == 0
        assert result.profitable_found == 0
        assert result.strategies_validated == 0
        assert result.top_wallets == []
        assert result.generated_strategies == []
        assert result.errors == []


# ---------------------------------------------------------------------------
# 2. Mock profitable wallet -> analyzed and fingerprinted
# ---------------------------------------------------------------------------


class TestProfitableWallet:
    @pytest.mark.asyncio
    async def test_profitable_wallet_passes_pipeline(self):
        trader = _trader()
        positions = _positions(30)

        with (
            patch(
                "backend.core.wallet_intelligence_pipeline.find_profitable_traders",
                new_callable=AsyncMock,
                return_value=[trader],
            ),
            patch(
                "backend.core.wallet_intelligence_pipeline.resolve_wallet",
                new_callable=AsyncMock,
                return_value=_wallet_info(),
            ),
            patch(
                "backend.core.wallet_intelligence_pipeline.analyze_wallet",
                new_callable=AsyncMock,
                return_value=_analysis(),
            ),
            patch(
                "backend.core.wallet_intelligence_pipeline.get_all_closed_positions",
                new_callable=AsyncMock,
                return_value=positions,
            ),
            patch(
                "backend.core.wallet_intelligence_pipeline.strategy_fingerprint",
                return_value=_fingerprint(),
            ),
            patch(
                "backend.core.wallet_intelligence_pipeline.replicate_strategy",
                new_callable=AsyncMock,
                return_value=_replication(),
            ),
        ):
            result = await run_pipeline(min_copy_rating=5)

        assert result.wallets_scanned == 1
        assert result.profitable_found == 1
        assert result.strategies_validated == 1
        assert len(result.top_wallets) == 1
        assert result.top_wallets[0].is_viable is True
        assert result.top_wallets[0].wallet == "0xaaaa"


# ---------------------------------------------------------------------------
# 3. Mock low-rating wallet -> filtered out
# ---------------------------------------------------------------------------


class TestLowRatingFiltered:
    @pytest.mark.asyncio
    async def test_low_copy_rating_filtered(self):
        trader = _trader()
        positions = _positions(30)

        with (
            patch(
                "backend.core.wallet_intelligence_pipeline.find_profitable_traders",
                new_callable=AsyncMock,
                return_value=[trader],
            ),
            patch(
                "backend.core.wallet_intelligence_pipeline.resolve_wallet",
                new_callable=AsyncMock,
                return_value=_wallet_info(),
            ),
            patch(
                "backend.core.wallet_intelligence_pipeline.analyze_wallet",
                new_callable=AsyncMock,
                return_value=_analysis(rating=2),
            ),
            patch(
                "backend.core.wallet_intelligence_pipeline.get_all_closed_positions",
                new_callable=AsyncMock,
                return_value=positions,
            ),
        ):
            result = await run_pipeline(min_copy_rating=5)

        assert result.wallets_scanned == 1
        assert result.profitable_found == 0
        assert result.top_wallets == []


# ---------------------------------------------------------------------------
# 4. Mock replication failure -> error recorded, continues
# ---------------------------------------------------------------------------


class TestReplicationFailure:
    @pytest.mark.asyncio
    async def test_replication_error_recordd_and_continues(self):
        good_trader = _trader(wallet="0xgood", pnl=200)
        bad_trader = _trader(wallet="0xbad", pnl=100)
        positions = _positions(30)

        # resolve_wallet returns different proxies per wallet
        async def mock_resolve(wallet):
            if wallet == "0xgood":
                return _wallet_info(proxy="0xgood_proxy")
            return _wallet_info(proxy="0xbad_proxy")

        # bad_trader's proxy raises during replicate_strategy
        async def mock_replicate(wallet, capital):
            if wallet == "0xbad_proxy":
                raise RuntimeError("API timeout")
            return _replication()

        with (
            patch(
                "backend.core.wallet_intelligence_pipeline.find_profitable_traders",
                new_callable=AsyncMock,
                return_value=[good_trader, bad_trader],
            ),
            patch(
                "backend.core.wallet_intelligence_pipeline.resolve_wallet",
                side_effect=mock_resolve,
            ),
            patch(
                "backend.core.wallet_intelligence_pipeline.analyze_wallet",
                new_callable=AsyncMock,
                return_value=_analysis(),
            ),
            patch(
                "backend.core.wallet_intelligence_pipeline.get_all_closed_positions",
                new_callable=AsyncMock,
                return_value=positions,
            ),
            patch(
                "backend.core.wallet_intelligence_pipeline.strategy_fingerprint",
                return_value=_fingerprint(),
            ),
            patch(
                "backend.core.wallet_intelligence_pipeline.replicate_strategy",
                side_effect=mock_replicate,
            ),
        ):
            result = await run_pipeline(min_copy_rating=5)

        # Good trader should succeed, bad trader should record error
        assert result.profitable_found == 1
        assert len(result.errors) == 1
        assert "0xbad" in result.errors[0]


# ---------------------------------------------------------------------------
# 5. Format report -> contains expected fields
# ---------------------------------------------------------------------------


class TestFormatReport:
    def test_report_contains_header_and_stats(self):
        result = PipelineResult(
            wallets_scanned=50,
            profitable_found=10,
            strategies_validated=3,
            top_wallets=[
                WalletCandidate(
                    wallet="0xabcdef1234567890",
                    pnl=1234.0,
                    win_rate=0.65,
                    total_trades=120,
                    sharpe=2.1,
                    strategy_type="SWING",
                    copy_rating=8,
                    is_viable=True,
                ),
            ],
        )

        report = format_report(result)

        assert "Wallets scanned: 50" in report
        assert "Profitable found: 10" in report
        assert "Strategies validated: 3" in report
        assert "Top Candidates:" in report
        assert "YES" in report
        assert "SWING" in report

    def test_report_with_errors(self):
        result = PipelineResult(
            wallets_scanned=5,
            errors=["Scan failed: timeout", "Analysis failed for 0xdead"],
        )

        report = format_report(result)

        assert "Errors: 2" in report
        assert "Scan failed: timeout" in report
        assert "Analysis failed for 0xdead" in report

    def test_report_empty_result(self):
        result = PipelineResult()
        report = format_report(result)

        assert "Wallets scanned: 0" in report
        assert "Profitable found: 0" in report
        assert "Top Candidates:" not in report
        assert "Errors:" not in report


# ---------------------------------------------------------------------------
# 6. Scan failure -> error recorded, early return
# ---------------------------------------------------------------------------


class TestScanFailure:
    @pytest.mark.asyncio
    async def test_scan_exception_returns_early(self):
        with patch(
            "backend.core.wallet_intelligence_pipeline.find_profitable_traders",
            new_callable=AsyncMock,
            side_effect=ConnectionError("API down"),
        ):
            result = await run_pipeline()

        assert result.wallets_scanned == 0
        assert len(result.errors) == 1
        assert "Scan failed" in result.errors[0]
        assert result.top_wallets == []


# ---------------------------------------------------------------------------
# 7. Too few positions -> filtered out
# ---------------------------------------------------------------------------


class TestInsufficientPositions:
    @pytest.mark.asyncio
    async def test_wallet_with_few_positions_filtered(self):
        trader = _trader()
        few_positions = _positions(5)  # Below minimum 20

        with (
            patch(
                "backend.core.wallet_intelligence_pipeline.find_profitable_traders",
                new_callable=AsyncMock,
                return_value=[trader],
            ),
            patch(
                "backend.core.wallet_intelligence_pipeline.resolve_wallet",
                new_callable=AsyncMock,
                return_value=_wallet_info(),
            ),
            patch(
                "backend.core.wallet_intelligence_pipeline.analyze_wallet",
                new_callable=AsyncMock,
                return_value=_analysis(),
            ),
            patch(
                "backend.core.wallet_intelligence_pipeline.get_all_closed_positions",
                new_callable=AsyncMock,
                return_value=few_positions,
            ),
        ):
            result = await run_pipeline(min_copy_rating=5)

        assert result.wallets_scanned == 1
        assert result.profitable_found == 0
