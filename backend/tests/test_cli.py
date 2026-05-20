"""Tests for backend.cli — argparse routing and output formatting."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from backend.cli import build_parser

# ---------------------------------------------------------------------------
# Helpers -- use SimpleNamespace so __dict__ is JSON-serializable
# ---------------------------------------------------------------------------


def _make_analysis(**overrides):
    """Create a JSON-safe WalletAnalysis-like object."""
    defaults = dict(
        wallet="0xabc",
        total_positions=42,
        total_volume=5000.0,
        total_pnl=1234.56,
        win_rate=62.5,
        wins=26,
        losses=16,
        avg_win=100.0,
        avg_loss=-50.0,
        profit_factor=2.1,
        expected_value=0.15,
        sharpe_ratio=1.8,
        max_drawdown=-300.0,
        recovery_factor=4.1,
        verdict="PROFITABLE",
        copy_trade_rating=7,
        red_flags=["low_sample"],
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_trader(**overrides):
    """Create a JSON-safe TraderScore-like object."""
    defaults = dict(
        wallet="0xabc",
        proxy="0xdef",
        pnl=500.0,
        win_rate=0.65,
        total_trades=120,
        volume=25000.0,
        sharpe=1.5,
        source_method="gamma",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_fingerprint(**overrides):
    defaults = dict(
        strategy_type="SWING",
        confidence=0.75,
        primary_category="BTC",
        primary_category_share=0.4,
        copy_trade_suitability=8,
        is_replicable=True,
        replication_difficulty="MEDIUM",
        red_flags=[],
        green_flags=["consistent_win"],
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_replication(**overrides):
    defaults = dict(
        source_wallet="0xabc",
        confidence_score=0.8,
        is_ready_for_live=False,
        rules=[{"action": "BUY"}, {"action": "SELL"}],
        paper_results={"pnl": 150.0, "win_rate": 60.0},
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_wallet_info(**overrides):
    defaults = dict(
        eoa="0xeoa",
        proxy="0xproxy",
        username="testuser",
        method="blockscout",
        is_proxy=False,
        has_traded=True,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAnalyzeCommand:
    """Test analyze subcommand routing."""

    @pytest.mark.asyncio
    @patch("backend.cli.analyze_wallet_rapid", new_callable=AsyncMock)
    @patch("backend.cli.analyze_wallet", new_callable=AsyncMock)
    @patch("backend.cli.resolve_wallet", new_callable=AsyncMock)
    async def test_analyze_full(self, mock_resolve, mock_analyze, mock_rapid, capsys):
        mock_resolve.return_value = _make_wallet_info(proxy="0xproxy")
        mock_analyze.return_value = _make_analysis()

        parser = build_parser()
        args = parser.parse_args(["analyze", "0xabc"])
        # inject --json
        args.json = False

        from backend.cli import cmd_analyze

        await cmd_analyze(args)

        mock_resolve.assert_awaited_once_with("0xabc")
        mock_analyze.assert_awaited_once_with("0xproxy")
        mock_rapid.assert_not_awaited()

        captured = capsys.readouterr()
        assert "Wallet Analysis" in captured.out
        assert "0xabc" in captured.out

    @pytest.mark.asyncio
    @patch("backend.cli.analyze_wallet_rapid", new_callable=AsyncMock)
    @patch("backend.cli.resolve_wallet", new_callable=AsyncMock)
    async def test_analyze_rapid(self, mock_resolve, mock_rapid, capsys):
        mock_resolve.return_value = _make_wallet_info(proxy="0xproxy")
        mock_rapid.return_value = _make_analysis()

        parser = build_parser()
        args = parser.parse_args(["analyze", "--rapid", "0xabc"])
        args.json = False

        from backend.cli import cmd_analyze

        await cmd_analyze(args)

        mock_rapid.assert_awaited_once_with("0xproxy")


class TestResolveCommand:
    """Test resolve subcommand."""

    @pytest.mark.asyncio
    @patch("backend.cli.resolve_wallet", new_callable=AsyncMock)
    async def test_resolve_output(self, mock_resolve, capsys):
        mock_resolve.return_value = _make_wallet_info()

        parser = build_parser()
        args = parser.parse_args(["resolve", "testuser"])
        args.json = False

        from backend.cli import cmd_resolve

        await cmd_resolve(args)

        mock_resolve.assert_awaited_once_with("testuser")
        captured = capsys.readouterr()
        assert "0xeoa" in captured.out
        assert "0xproxy" in captured.out
        assert "testuser" in captured.out


class TestProxyCommand:
    """Test proxy subcommand."""

    @pytest.mark.asyncio
    @patch("backend.cli.find_proxy_wallet", new_callable=AsyncMock)
    async def test_proxy_found(self, mock_find, capsys):
        mock_find.return_value = "0xproxyresult"

        parser = build_parser()
        args = parser.parse_args(["proxy", "0xeoa"])
        args.json = False

        from backend.cli import cmd_proxy

        await cmd_proxy(args)

        mock_find.assert_awaited_once_with("0xeoa")
        captured = capsys.readouterr()
        assert "0xproxyresult" in captured.out

    @pytest.mark.asyncio
    @patch("backend.cli.find_proxy_wallet", new_callable=AsyncMock)
    async def test_proxy_not_found(self, mock_find, capsys):
        mock_find.return_value = None

        parser = build_parser()
        args = parser.parse_args(["proxy", "0xeoa"])
        args.json = False

        from backend.cli import cmd_proxy

        await cmd_proxy(args)

        captured = capsys.readouterr()
        assert "No proxy wallet found" in captured.out


class TestScanCommand:
    """Test scan subcommand."""

    @pytest.mark.asyncio
    @patch("backend.cli.find_profitable_traders", new_callable=AsyncMock)
    async def test_scan_routing(self, mock_scan):
        mock_scan.return_value = []

        parser = build_parser()
        args = parser.parse_args(
            ["scan", "--min-volume", "5000", "--sort-by", "sharpe", "--limit", "10"]
        )
        args.json = False

        from backend.cli import cmd_scan

        await cmd_scan(args)

        mock_scan.assert_awaited_once_with(
            min_volume=5000.0,
            min_trades=50,
            max_results=10,
            sort_by="sharpe",
        )


class TestJsonFlag:
    """Test --json output format."""

    @pytest.mark.asyncio
    @patch("backend.cli.resolve_wallet", new_callable=AsyncMock)
    async def test_json_output_resolve(self, mock_resolve, capsys):
        mock_resolve.return_value = _make_wallet_info()

        parser = build_parser()
        args = parser.parse_args(["--json", "resolve", "testuser"])
        args.json = True

        from backend.cli import cmd_resolve

        await cmd_resolve(args)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["eoa"] == "0xeoa"
        assert data["proxy"] == "0xproxy"

    @pytest.mark.asyncio
    @patch("backend.cli.analyze_wallet", new_callable=AsyncMock)
    @patch("backend.cli.resolve_wallet", new_callable=AsyncMock)
    async def test_json_output_analyze(self, mock_resolve, mock_analyze, capsys):
        mock_resolve.return_value = _make_wallet_info(proxy="0xproxy")
        mock_analyze.return_value = _make_analysis()

        parser = build_parser()
        args = parser.parse_args(["--json", "analyze", "0xabc"])
        args.json = True

        from backend.cli import cmd_analyze

        await cmd_analyze(args)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["wallet"] == "0xabc"
        assert data["verdict"] == "PROFITABLE"


class TestNoCommand:
    """Test help output when no command given."""

    def test_no_command_prints_help(self, capsys):
        parser = build_parser()
        args = parser.parse_args([])
        # Simulate main() behavior
        assert args.command is None
        parser.print_help()
        captured = capsys.readouterr()
        assert "Polymarket Intelligence CLI" in captured.out
