"""Integration tests for /api/v1/dashboard, /api/v1/stats, and /api/v1/signals endpoints.

Uses the shared conftest.py fixtures (client, db) backed by in-memory SQLite.
External API calls (microstructure, BTC markets, signals) are mocked so tests
run fast and deterministically.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.api import dashboard as dashboard_api
from backend.models.database import BotState, Trade


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _mock_micro():
    micro = MagicMock()
    micro.rsi = 50.0
    micro.momentum_1m = 0.0
    micro.momentum_5m = 0.0
    micro.momentum_15m = 0.0
    micro.vwap_deviation = 0.0
    micro.sma_crossover = 0.0
    micro.volatility = 0.02
    micro.price = 65000.0
    micro.source = "binance"
    return micro


def _mock_btc_price():
    price = MagicMock()
    price.current_price = 65000.0
    price.change_24h = 1.5
    price.change_7d = 3.0
    price.market_cap = 1_200_000_000_000.0
    price.volume_24h = 40_000_000_000.0
    from datetime import datetime
    price.last_updated = datetime.now(timezone.utc)
    return price


# ---------------------------------------------------------------------------
# /api/v1/stats
# ---------------------------------------------------------------------------


class TestStatsEndpoint:
    def test_stats_returns_200(self, client):
        resp = client.get("/api/v1/stats")
        assert resp.status_code == 200

    def test_stats_has_expected_keys(self, client):
        resp = client.get("/api/v1/stats")
        data = resp.json()
        required_keys = {
            "bankroll",
            "available_balance",
            "total_balance",
            "total_trades",
            "winning_trades",
            "win_rate",
            "total_pnl",
            "realized_pnl",
            "is_running",
        }
        for key in required_keys:
            assert key in data, f"Missing key: {key}"

    def test_stats_bankroll_is_numeric(self, client):
        resp = client.get("/api/v1/stats")
        data = resp.json()
        assert isinstance(data["bankroll"], (int, float))
        assert data["bankroll"] >= 0

    def test_stats_total_trades_is_int(self, client):
        resp = client.get("/api/v1/stats")
        data = resp.json()
        assert isinstance(data["total_trades"], int)

    def test_stats_win_rate_in_range(self, client):
        resp = client.get("/api/v1/stats")
        data = resp.json()
        assert 0.0 <= data["win_rate"] <= 1.0

    def test_stats_has_paper_and_live_dicts(self, client):
        resp = client.get("/api/v1/stats")
        data = resp.json()
        assert "paper" in data
        assert "live" in data
        assert isinstance(data["paper"], dict)
        assert isinstance(data["live"], dict)

    def test_stats_exposes_explicit_balance_breakdown_fields(self, client):
        with patch(
            "backend.api.system.fetch_pm_profile_pnl",
            AsyncMock(return_value=25.740828),
        ):
            resp = client.get("/api/v1/stats")
            data = resp.json()

        assert isinstance(data["available_balance"], (int, float))
        assert isinstance(data["total_balance"], (int, float))
        assert isinstance(data["realized_pnl"], (int, float))
        assert isinstance(data["account_pnl"], (int, float))
        assert "available_balance" in data["paper"]
        assert "total_balance" in data["paper"]
        assert "realized_pnl" in data["paper"]
        assert "available_balance" in data["live"]
        assert "total_balance" in data["live"]
        assert "realized_pnl" in data["live"]
        assert "account_pnl" in data["live"]

    def test_stats_live_separates_profile_account_pnl_from_realized_ledger_pnl(self, client, db):
        live_state = db.query(BotState).filter_by(mode="live").first()
        db.info["allow_live_financial_update"] = True
        live_state.bankroll = 130.0
        live_state.total_pnl = 8.0
        db.commit()
        db.info.pop("allow_live_financial_update", None)

        db.add(
            Trade(
                market_ticker="LIVE-SETTLED-WIN",
                platform="polymarket",
                direction="up",
                entry_price=0.5,
                size=10.0,
                settled=True,
                result="win",
                pnl=5.0,
                trading_mode="live",
            )
        )
        db.commit()

        with patch(
            "backend.api.system.fetch_pm_profile_pnl",
            AsyncMock(return_value=25.740828),
        ):
            resp = client.get("/api/v1/stats?mode=live")

        data = resp.json()
        assert data["total_pnl"] == 25.740828
        assert data["account_pnl"] == 25.740828
        assert data["realized_pnl"] == 5.0
        assert data["live"]["account_pnl"] == 25.740828
        assert data["live"]["realized_pnl"] == 5.0

    def test_stats_floors_simulated_bankroll_without_hiding_negative_pnl(self, client, db):
        paper_state = db.query(BotState).filter_by(mode="paper").first()
        testnet_state = db.query(BotState).filter_by(mode="testnet").first()
        paper_state.bankroll = -12.34
        paper_state.paper_bankroll = -12.34
        testnet_state.bankroll = -74.49
        testnet_state.testnet_bankroll = -74.49
        db.add_all(
            [
                Trade(
                    market_ticker="PAPER-LOSS",
                    platform="polymarket",
                    direction="up",
                    entry_price=0.5,
                    size=25.0,
                    settled=True,
                    result="loss",
                    pnl=-112.34,
                    trading_mode="paper",
                ),
                Trade(
                    market_ticker="TESTNET-LOSS",
                    platform="polymarket",
                    direction="down",
                    entry_price=0.5,
                    size=25.0,
                    settled=True,
                    result="loss",
                    pnl=-174.49,
                    trading_mode="testnet",
                ),
            ]
        )
        db.commit()

        resp = client.get("/api/v1/stats")
        data = resp.json()

        assert data["paper_bankroll"] == 0.0
        assert data["paper"]["bankroll"] == 0.0
        assert data["paper_pnl"] == -112.34
        assert data["paper"]["pnl"] == -112.34
        assert data["testnet_bankroll"] == 0.0
        assert data["testnet"]["bankroll"] == 0.0
        assert data["testnet_pnl"] == -174.49
        assert data["testnet"]["pnl"] == -174.49

        paper_resp = client.get("/api/v1/stats?mode=paper")
        assert paper_resp.json()["bankroll"] == 0.0

        testnet_resp = client.get("/api/v1/stats?mode=testnet")
        assert testnet_resp.json()["bankroll"] == 0.0


# ---------------------------------------------------------------------------
# /api/v1/dashboard
# ---------------------------------------------------------------------------


class TestDashboardEndpoint:
    def _get_dashboard(self, client):
        """Call dashboard with mocked external services."""
        dashboard_api._dashboard_cache_value = None
        dashboard_api._dashboard_cache_expires_at = 0.0
        with patch(
            "backend.api.dashboard.compute_btc_microstructure",
            AsyncMock(return_value=_mock_micro()),
        ), patch(
            "backend.api.dashboard.fetch_crypto_price",
            AsyncMock(return_value=_mock_btc_price()),
        ), patch(
            "backend.api.dashboard.fetch_active_btc_markets",
            AsyncMock(return_value=[]),
        ), patch(
            "backend.api.dashboard.scan_for_signals",
            AsyncMock(return_value=[]),
        ), patch(
            "backend.api.dashboard.settings.WEATHER_ENABLED",
            False,
        ):
            return client.get("/api/v1/dashboard")

    def test_dashboard_returns_200(self, client):
        resp = self._get_dashboard(client)
        assert resp.status_code == 200

    def test_dashboard_returns_valid_structure(self, client):
        """Dashboard response must contain all top-level keys."""
        resp = self._get_dashboard(client)
        data = resp.json()
        required_keys = {
            "stats",
            "windows",
            "active_signals",
            "recent_trades",
            "equity_curve",
            "trading_mode",
        }
        for key in required_keys:
            assert key in data, f"Missing key in dashboard response: {key}"

    def test_dashboard_stats_is_dict(self, client):
        resp = self._get_dashboard(client)
        data = resp.json()
        assert isinstance(data["stats"], dict)

    def test_dashboard_recent_trades_is_list(self, client):
        resp = self._get_dashboard(client)
        data = resp.json()
        assert isinstance(data["recent_trades"], list)

    def test_dashboard_active_signals_is_list(self, client):
        resp = self._get_dashboard(client)
        data = resp.json()
        assert isinstance(data["active_signals"], list)

    def test_dashboard_windows_is_list(self, client):
        resp = self._get_dashboard(client)
        data = resp.json()
        assert isinstance(data["windows"], list)

    def test_dashboard_equity_curve_is_list(self, client):
        resp = self._get_dashboard(client)
        data = resp.json()
        assert isinstance(data["equity_curve"], list)

    def test_dashboard_trading_mode_is_string(self, client):
        resp = self._get_dashboard(client)
        data = resp.json()
        assert isinstance(data["trading_mode"], str)
        assert data["trading_mode"] in ("paper", "testnet", "live")

    def test_dashboard_stats_has_bankroll(self, client):
        resp = self._get_dashboard(client)
        data = resp.json()
        assert "bankroll" in data["stats"]
        assert isinstance(data["stats"]["bankroll"], (int, float))

    def test_dashboard_weather_signals_is_list(self, client):
        resp = self._get_dashboard(client)
        data = resp.json()
        assert isinstance(data.get("weather_signals", []), list)

    def test_dashboard_exposes_top_winning_trades_outside_recent_slice(self, client, db):
        now = datetime.now(timezone.utc)
        winning_trade = Trade(
            market_ticker="LIVE-WINNER-OLD",
            platform="polymarket",
            direction="up",
            entry_price=0.35,
            size=100.0,
            timestamp=now - timedelta(days=5),
            settled=True,
            result="win",
            pnl=25.0,
            trading_mode="live",
        )
        db.add(winning_trade)
        for idx in range(55):
            db.add(
                Trade(
                    market_ticker=f"RECENT-PENDING-{idx}",
                    platform="polymarket",
                    direction="down",
                    entry_price=0.5,
                    size=1.0,
                    timestamp=now - timedelta(minutes=idx),
                    settled=False,
                    result="pending",
                    pnl=None,
                    trading_mode="paper",
                )
            )
        db.commit()

        resp = self._get_dashboard(client)
        data = resp.json()

        assert all(t["market_ticker"] != "LIVE-WINNER-OLD" for t in data["recent_trades"])
        assert data["top_winning_trades"][0]["market_ticker"] == "LIVE-WINNER-OLD"
        assert data["top_winning_trades"][0]["pnl"] == 25.0

    def test_dashboard_live_equity_curve_ends_at_reconciled_state(self, client, db):
        now = datetime.now(timezone.utc)
        live_state = db.query(BotState).filter_by(mode="live").first()
        db.info["allow_live_financial_update"] = True
        live_state.bankroll = 170.0
        live_state.total_pnl = 70.0
        db.add_all(
            [
                Trade(
                    market_ticker="LIVE-WIN-1",
                    platform="polymarket",
                    direction="up",
                    entry_price=0.45,
                    size=10.0,
                    timestamp=now - timedelta(days=3),
                    settled=True,
                    result="win",
                    pnl=5.0,
                    trading_mode="live",
                    settlement_source="market_resolution",
                ),
                Trade(
                    market_ticker="LIVE-LOSS-1",
                    platform="polymarket",
                    direction="down",
                    entry_price=0.55,
                    size=10.0,
                    timestamp=now - timedelta(days=2),
                    settled=True,
                    result="loss",
                    pnl=-3.0,
                    trading_mode="live",
                    settlement_source="market_resolution",
                ),
                Trade(
                    market_ticker="LIVE-BACKFILL-LOSS",
                    platform="polymarket",
                    direction="up",
                    entry_price=1.0,
                    size=999.0,
                    timestamp=now - timedelta(days=1),
                    settled=True,
                    result="loss",
                    pnl=-999.0,
                    trading_mode="live",
                    settlement_source="backfill_conservative_loss",
                ),
            ]
        )
        db.commit()
        db.info.pop("allow_live_financial_update", None)

        resp = self._get_dashboard(client)
        data = resp.json()

        assert len(data["equity_curve"]) >= 3
        assert data["equity_curve"][-1]["pnl"] == 70.0
        assert data["equity_curve"][-1]["bankroll"] == 170.0
        assert all(point["pnl"] > -100 for point in data["equity_curve"][:-1])

    @pytest.mark.asyncio
    async def test_dashboard_cache_coalesces_concurrent_builds(self, db):
        build_count = 0

        async def fake_build(_db):
            nonlocal build_count
            build_count += 1
            await asyncio.sleep(0.01)
            return dashboard_api.DashboardData(
                stats=dashboard_api.BotStats(
                    bankroll=100.0,
                    available_balance=100.0,
                    total_balance=100.0,
                    total_trades=0,
                    winning_trades=0,
                    win_rate=0.0,
                    total_pnl=0.0,
                    is_running=True,
                    last_run=None,
                ),
                btc_price=None,
                windows=[],
                active_signals=[],
                recent_trades=[],
                equity_curve=[],
                trading_mode="paper",
            )

        dashboard_api._dashboard_cache_value = None
        dashboard_api._dashboard_cache_expires_at = 0.0

        with patch.object(dashboard_api, "_build_dashboard_data", side_effect=fake_build), patch.object(
            dashboard_api, "_dashboard_cache_ttl_seconds", return_value=2.0
        ):
            payloads = await asyncio.gather(
                *(dashboard_api._get_cached_dashboard_data(db) for _ in range(5))
            )

        assert build_count == 1
        assert all(payload is payloads[0] for payload in payloads)

        dashboard_api._dashboard_cache_value = None
        dashboard_api._dashboard_cache_expires_at = 0.0

    @pytest.mark.asyncio
    async def test_dashboard_cache_refreshes_after_ttl(self, db):
        build_count = 0

        async def fake_build(_db):
            nonlocal build_count
            build_count += 1
            return dashboard_api.DashboardData(
                stats=dashboard_api.BotStats(
                    bankroll=100.0 + build_count,
                    available_balance=100.0,
                    total_balance=100.0,
                    total_trades=0,
                    winning_trades=0,
                    win_rate=0.0,
                    total_pnl=0.0,
                    is_running=True,
                    last_run=None,
                ),
                btc_price=None,
                windows=[],
                active_signals=[],
                recent_trades=[],
                equity_curve=[],
                trading_mode="paper",
            )

        dashboard_api._dashboard_cache_value = None
        dashboard_api._dashboard_cache_expires_at = 0.0

        with patch.object(dashboard_api, "_build_dashboard_data", side_effect=fake_build), patch.object(
            dashboard_api, "_dashboard_cache_ttl_seconds", return_value=0.01
        ):
            first = await dashboard_api._get_cached_dashboard_data(db)
            second = await dashboard_api._get_cached_dashboard_data(db)
            await asyncio.sleep(0.02)
            third = await dashboard_api._get_cached_dashboard_data(db)

        assert build_count == 2
        assert second is first
        assert third is not first

        dashboard_api._dashboard_cache_value = None
        dashboard_api._dashboard_cache_expires_at = 0.0


# ---------------------------------------------------------------------------
# /api/v1/signals — via trading router
# ---------------------------------------------------------------------------


class TestSignalsEndpoint:
    def test_signals_endpoint_returns_200(self, client):
        with patch(
            "backend.core.signals.compute_btc_microstructure",
            AsyncMock(return_value=_mock_micro()),
        ), patch(
            "backend.core.signals.fetch_active_btc_markets",
            AsyncMock(return_value=[]),
        ):
            resp = client.get("/api/v1/signals")
        assert resp.status_code == 200

    def test_signals_returns_list(self, client):
        with patch(
            "backend.core.signals.compute_btc_microstructure",
            AsyncMock(return_value=_mock_micro()),
        ), patch(
            "backend.core.signals.fetch_active_btc_markets",
            AsyncMock(return_value=[]),
        ):
            resp = client.get("/api/v1/signals")
        data = resp.json()
        assert isinstance(data, list)

    def test_signals_empty_when_no_markets(self, client):
        """With no BTC markets available, signals list is empty."""
        with patch(
            "backend.core.signals.fetch_active_btc_markets",
            AsyncMock(return_value=[]),
        ), patch(
            "backend.core.signals.compute_btc_microstructure",
            AsyncMock(return_value=_mock_micro()),
        ):
            resp = client.get("/api/v1/signals")
        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# /api/v1/health — smoke test (already covered in test_api_health.py)
# ---------------------------------------------------------------------------


class TestHealthSmoke:
    def test_health_ok(self, client):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("healthy", "unhealthy")
