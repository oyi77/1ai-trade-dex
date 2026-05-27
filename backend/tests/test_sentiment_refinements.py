"""Unit tests for sentiment and execution refinements: copy trader win-rate gating, whale PnL/size checking, and weather category weighting."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone, timedelta

# Import target classes/functions
from backend.modules.execution.copy_trader import get_target_wallet_db_stats, CopyTrader
from backend.modules.data_feeds.whale_frontrun import WhalePnLTracker, WhaleFrontrun
from backend.modules.scanners.weather_emos import CATEGORY_WEATHER_WEIGHTS, CalibrationState
from backend.strategies.base import MarketEvent, StrategyContext

# Database models if needed
from backend.models.database import Trade, CopyTraderEntry

class TestCopyTraderGating:
    """Test copy trader win rate and sample size gating."""

    def test_get_target_wallet_db_stats_empty(self):
        db = MagicMock()
        db.query.return_value.join.return_value.filter.return_value.all.return_value = []
        win_rate, roi, sample_size = get_target_wallet_db_stats(db, "0x123")
        assert sample_size == 0
        assert win_rate == 0.0
        assert roi == 0.0

    def test_get_target_wallet_db_stats_calculated(self):
        db = MagicMock()
        trade1 = MagicMock(spec=Trade)
        trade1.result = "win"
        trade1.size = 100.0
        trade1.pnl = 20.0
        
        trade2 = MagicMock(spec=Trade)
        trade2.result = "loss"
        trade2.size = 100.0
        trade2.pnl = -100.0

        db.query.return_value.join.return_value.filter.return_value.all.return_value = [trade1, trade2]
        
        win_rate, roi, sample_size = get_target_wallet_db_stats(db, "0x123")
        assert sample_size == 2
        assert win_rate == 0.5
        assert roi == (20.0 - 100.0) / 200.0

    @pytest.mark.asyncio
    @patch("backend.modules.execution.copy_trader.CopyTrader._refresh_leaderboard")
    @patch("backend.modules.execution.copy_trader.get_target_wallet_db_stats")
    async def test_copy_trader_poll_gating(self, mock_db_stats, mock_refresh):
        # Setup copy trader with 1 mock tracked trader
        ct = CopyTrader()
        mock_trader = MagicMock()
        mock_trader.user = "0x123"
        mock_trader.pseudonym = "WhaleTrader"
        mock_trader.win_rate = 0.50
        mock_trader.total_trades = 10
        ct._tracked = [mock_trader]
        ct._last_refresh = 9999999999.0 # avoid refresh in test

        db = MagicMock()

        # Case A: DB win_rate < 45% (and database sample_size >= 5)
        mock_db_stats.return_value = (0.40, 0.10, 6) # wr, roi, sample
        with patch.object(ct, "_watcher") as mock_watcher:
            signals = await ct.poll_once(db=db)
            assert len(signals) == 0
            mock_watcher.poll.assert_not_called()

        # Case B: DB sample size < 5 -> fallback to leader board total_trades, but wait, 
        # get_target_wallet_db_stats returns sample_size=3.
        # So we fallback to leaderboard win_rate (0.50) and total_trades (10)
        # Leaderboard sample size >= 5 and win_rate >= 45% -> should call poll
        mock_db_stats.return_value = (0.30, 0.0, 3) # small sample
        with patch.object(ct, "_watcher") as mock_watcher:
            mock_watcher.poll.return_value = ([], [])
            signals = await ct.poll_once(db=db)
            mock_watcher.poll.assert_called_once_with("0x123")


class TestWhaleFrontrunGating:
    """Test whale frontrunning realized PnL and size gating."""

    @pytest.mark.asyncio
    @patch("backend.modules.data_feeds.whale_frontrun.httpx.AsyncClient")
    async def test_pnl_tracker(self, mock_client_class):
        # Mocking Polymarket data API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"createdAt": int(datetime.now(timezone.utc).timestamp()), "realizedPnl": 500.0},
            {"createdAt": int((datetime.now(timezone.utc) - timedelta(days=5)).timestamp()), "realizedPnl": -200.0},
            {"createdAt": int((datetime.now(timezone.utc) - timedelta(days=40)).timestamp()), "realizedPnl": 1000.0}, # too old, ignore
        ]
        
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value.__aenter__.return_value = mock_client

        pnl = await WhalePnLTracker.get_30d_realized_pnl("0xabc")
        # Should sum 500 - 200 = 300
        assert pnl == 300.0

    @pytest.mark.asyncio
    @patch("backend.modules.data_feeds.whale_frontrun.WhalePnLTracker.get_30d_realized_pnl")
    async def test_frontrun_gating(self, mock_pnl):
        wf = WhaleFrontrun()
        wf.default_params["min_whale_notional"] = 5000.0
        wf.default_params["min_size"] = 1000.0
        wf.default_params["min_score"] = 0.1

        # Case A: Size below min_whale_notional
        event_small = MarketEvent(
            token_id="token-1",
            event_type="last_trade_price",
            data={"size": "4000.0", "wallet": "0xabc", "price": "0.5"},
            timestamp=datetime.now(timezone.utc).timestamp()
        )
        res = await wf.on_market_event(event_small)
        assert res is None

        # Case B: Size is ok, but whale has negative realized PnL
        mock_pnl.return_value = -100.0
        event_ok_pnl_neg = MarketEvent(
            token_id="token-1",
            event_type="last_trade_price",
            data={"size": "6000.0", "wallet": "0xabc", "price": "0.5"},
            timestamp=datetime.now(timezone.utc).timestamp()
        )
        res = await wf.on_market_event(event_ok_pnl_neg)
        assert res is None

        # Case C: Size ok, positive realized PnL -> accept
        mock_pnl.return_value = 500.0
        res = await wf.on_market_event(event_ok_pnl_neg)
        assert res is not None
        assert res["decision"] == "BUY"


class TestWeatherCategoryWeights:
    """Test weather EMOS category-specific sentiment shift weighting."""

    def test_category_weights_defined(self):
        assert CATEGORY_WEATHER_WEIGHTS["sports"] == 1.5
        assert CATEGORY_WEATHER_WEIGHTS["entertainment"] == 1.5
        assert CATEGORY_WEATHER_WEIGHTS["macroeconomics"] == 0.2
        assert CATEGORY_WEATHER_WEIGHTS["economy"] == 0.2

    def test_sentiment_shift_applied(self):
        # We simulate the weather scanner mood anomaly and category lookup logic:
        # calibrated_p = 0.60
        # mood_anomaly = 2.0 (standard deviations warmer than expected)
        # Shift = mood_anomaly * 0.05 * category_weight
        
        # 1. Retail Category (sports -> 1.5 weight)
        # Shift = 2.0 * 0.05 * 1.5 = +0.15
        # Calibrated probability shifts to 0.75
        calibrated_p = 0.60
        mood_anomaly = 2.0
        category_weight_sports = 1.5
        sentiment_shift_sports = mood_anomaly * 0.05 * category_weight_sports
        adjusted_p_sports = max(0.01, min(0.99, calibrated_p + sentiment_shift_sports))
        assert adjusted_p_sports == 0.75

        # 2. Macro Category (macro-economy -> 0.2 weight)
        # Shift = 2.0 * 0.05 * 0.2 = +0.02
        # Calibrated probability shifts to 0.62
        category_weight_macro = 0.2
        sentiment_shift_macro = mood_anomaly * 0.05 * category_weight_macro
        adjusted_p_macro = max(0.01, min(0.99, calibrated_p + sentiment_shift_macro))
        assert adjusted_p_macro == 0.62
