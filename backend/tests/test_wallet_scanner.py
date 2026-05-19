"""Tests for wallet_scanner module."""

from __future__ import annotations

import json
import time
from unittest.mock import patch, AsyncMock

import pytest

from backend.core.wallet_scanner import (
    TraderScore,
    _filter_and_sort,
    _load_scan_cache,
    _save_scan_cache,
    find_profitable_traders,
)


def _score(
    wallet: str = "0xaaaa",
    pnl: float = 100.0,
    win_rate: float = 0.6,
    total_trades: int = 60,
    volume: float = 5000.0,
    source_method: str = "scan",
) -> TraderScore:
    return TraderScore(
        wallet=wallet,
        pnl=pnl,
        win_rate=win_rate,
        total_trades=total_trades,
        volume=volume,
        source_method=source_method,
    )


def _pos(pnl: float, volume: float = 200.0) -> dict:
    return {"realizedPnl": pnl, "totalBought": volume}


# ---------------------------------------------------------------------------
# 1. Discovery: mock Gamma + Blockscout -> returns scored traders
# ---------------------------------------------------------------------------


class TestDiscovery:
    @pytest.mark.asyncio
    async def test_discovery_returns_scored_traders(self, tmp_path):
        """Mock both discovery methods and position fetching."""
        wallet = "0xabcdef1234567890abcdef1234567890abcdef12"
        positions = [_pos(10.0)] * 60  # 60 trades, volume=12000

        gamma_wallets = {wallet}
        whale_wallets = set()

        with (
            patch("backend.core.wallet_scanner._load_scan_cache", return_value=None),
            patch("backend.core.wallet_scanner._save_scan_cache"),
            patch(
                "backend.core.wallet_scanner._discover_from_gamma",
                new_callable=AsyncMock,
                return_value=gamma_wallets,
            ),
            patch(
                "backend.core.wallet_scanner._discover_whales",
                new_callable=AsyncMock,
                return_value=whale_wallets,
            ),
            patch(
                "backend.data.wallet_history.get_all_closed_positions",
                new_callable=AsyncMock,
                return_value=positions,
            ),
        ):
            result = await find_profitable_traders(
                min_volume=1000, min_trades=50, max_results=10
            )

        assert len(result) == 1
        assert result[0].wallet == wallet
        assert result[0].total_trades == 60
        assert result[0].volume == 12000.0
        assert result[0].pnl == 600.0
        assert result[0].win_rate == 1.0  # all positive


# ---------------------------------------------------------------------------
# 2. Deduplication: same wallet from multiple methods -> appears once
# ---------------------------------------------------------------------------


class TestDeduplication:
    @pytest.mark.asyncio
    async def test_same_wallet_deduped(self):
        wallet = "0xabcdef1234567890abcdef1234567890abcdef12"
        # Both methods return the same wallet (different case)
        gamma_wallets = {wallet.upper()}
        whale_wallets = {wallet.lower()}
        positions = [_pos(5.0)] * 60

        with (
            patch("backend.core.wallet_scanner._load_scan_cache", return_value=None),
            patch("backend.core.wallet_scanner._save_scan_cache"),
            patch(
                "backend.core.wallet_scanner._discover_from_gamma",
                new_callable=AsyncMock,
                return_value=gamma_wallets,
            ),
            patch(
                "backend.core.wallet_scanner._discover_whales",
                new_callable=AsyncMock,
                return_value=whale_wallets,
            ),
            patch(
                "backend.data.wallet_history.get_all_closed_positions",
                new_callable=AsyncMock,
                return_value=positions,
            ),
        ):
            result = await find_profitable_traders(
                min_volume=1000, min_trades=50
            )

        # Should be deduplicated to exactly 1 trader
        assert len(result) == 1


# ---------------------------------------------------------------------------
# 3. Filter by min_volume: traders below threshold excluded
# ---------------------------------------------------------------------------


class TestFilterVolume:
    def test_below_min_volume_excluded(self):
        traders = [
            _score(wallet="0x1", volume=500, total_trades=60),
            _score(wallet="0x2", volume=5000, total_trades=60),
            _score(wallet="0x3", volume=999, total_trades=60),
        ]
        result = _filter_and_sort(traders, min_vol=1000, min_trades=50, max_results=50, sort_by="pnl")
        assert len(result) == 1
        assert result[0].wallet == "0x2"


# ---------------------------------------------------------------------------
# 4. Sort by PnL: highest PnL first
# ---------------------------------------------------------------------------


class TestSortPnL:
    def test_sorted_by_pnl_desc(self):
        traders = [
            _score(wallet="0x1", pnl=10.0),
            _score(wallet="0x2", pnl=100.0),
            _score(wallet="0x3", pnl=50.0),
        ]
        result = _filter_and_sort(traders, min_vol=0, min_trades=0, max_results=50, sort_by="pnl")
        assert [t.pnl for t in result] == [100.0, 50.0, 10.0]


# ---------------------------------------------------------------------------
# 5. Sort by win_rate: highest WR first
# ---------------------------------------------------------------------------


class TestSortWinRate:
    def test_sorted_by_win_rate_desc(self):
        traders = [
            _score(wallet="0x1", win_rate=0.4),
            _score(wallet="0x2", win_rate=0.9),
            _score(wallet="0x3", win_rate=0.6),
        ]
        result = _filter_and_sort(traders, min_vol=0, min_trades=0, max_results=50, sort_by="win_rate")
        assert [t.win_rate for t in result] == [0.9, 0.6, 0.4]


# ---------------------------------------------------------------------------
# 6. Cache: second call returns cached results
# ---------------------------------------------------------------------------


class TestCache:
    def test_save_and_load_cache(self, tmp_path):
        traders = [_score(wallet="0x1", pnl=42.0)]

        with patch("backend.core.wallet_scanner.CACHE_DIR", tmp_path):
            _save_scan_cache(traders)
            loaded = _load_scan_cache()

        assert loaded is not None
        assert len(loaded) == 1
        assert loaded[0].wallet == "0x1"
        assert loaded[0].pnl == 42.0

    def test_expired_cache_returns_none(self, tmp_path):
        cache_file = tmp_path / "scan_results.json"
        cache_file.write_text(json.dumps({
            "timestamp": time.time() - 7200,  # 2 hours ago
            "traders": [{"wallet": "0x1", "proxy": None, "pnl": 0, "win_rate": 0,
                         "total_trades": 0, "volume": 0, "sharpe": 0, "source_method": ""}],
        }))
        with patch("backend.core.wallet_scanner.CACHE_DIR", tmp_path):
            result = _load_scan_cache()
        assert result is None

    @pytest.mark.asyncio
    async def test_find_uses_cache(self):
        cached = [_score(wallet="0xcached", pnl=999.0)]

        with (
            patch(
                "backend.core.wallet_scanner._load_scan_cache",
                return_value=cached,
            ),
            patch(
                "backend.core.wallet_scanner._discover_from_gamma",
                new_callable=AsyncMock,
            ) as mock_gamma,
        ):
            result = await find_profitable_traders(
                min_volume=0, min_trades=0
            )

        # Should use cache and never call discovery
        mock_gamma.assert_not_called()
        assert len(result) == 1
        assert result[0].wallet == "0xcached"


# ---------------------------------------------------------------------------
# 7. Empty results: no traders found -> empty list
# ---------------------------------------------------------------------------


class TestEmptyResults:
    @pytest.mark.asyncio
    async def test_no_traders_returns_empty(self):
        with (
            patch("backend.core.wallet_scanner._load_scan_cache", return_value=None),
            patch("backend.core.wallet_scanner._save_scan_cache"),
            patch(
                "backend.core.wallet_scanner._discover_from_gamma",
                new_callable=AsyncMock,
                return_value=set(),
            ),
            patch(
                "backend.core.wallet_scanner._discover_whales",
                new_callable=AsyncMock,
                return_value=set(),
            ),
        ):
            result = await find_profitable_traders()

        assert result == []

    @pytest.mark.asyncio
    async def test_traders_below_threshold_filtered(self):
        wallet = "0xlowvolume"
        # Only 5 trades with small volume -- below min_trades=50
        positions = [_pos(1.0, volume=50.0)] * 5

        with (
            patch("backend.core.wallet_scanner._load_scan_cache", return_value=None),
            patch("backend.core.wallet_scanner._save_scan_cache"),
            patch(
                "backend.core.wallet_scanner._discover_from_gamma",
                new_callable=AsyncMock,
                return_value={wallet},
            ),
            patch(
                "backend.core.wallet_scanner._discover_whales",
                new_callable=AsyncMock,
                return_value=set(),
            ),
            patch(
                "backend.data.wallet_history.get_all_closed_positions",
                new_callable=AsyncMock,
                return_value=positions,
            ),
        ):
            result = await find_profitable_traders(min_volume=1000, min_trades=50)

        assert result == []
