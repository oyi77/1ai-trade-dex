"""Unit and integration tests for safety-hardened LineMovementDetectorStrategy."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx
from datetime import datetime, timezone

from backend.strategies.line_movement_detector import (
    LineMovementDetectorStrategy,
    LineMovement,
)
from backend.strategies.base import StrategyContext, MarketInfo


class TestLineMovementDetectorHardened:
    """Validate safety bounds, kinetics, and debate gates in line_movement_detector."""

    def _create_mock_context(self):
        ctx = MagicMock(spec=StrategyContext)
        ctx.params = {}
        ctx.bankroll = 1000.0
        ctx.settings = MagicMock()
        ctx.settings.MAX_POSITION_FRACTION = 0.30
        ctx.settings.TELEGRAM_HIGH_CONFIDENCE_ALERTS = False
        return ctx

    @pytest.mark.asyncio
    @patch("backend.strategies.line_movement_detector.get_shared_client")
    async def test_volume_liquidity_thresholds(self, mock_get_shared_client):
        strategy = LineMovementDetectorStrategy()

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=MagicMock(status_code=200, json=MagicMock(return_value=[])))
        mock_get_shared_client.return_value = mock_client

        # Test 1: Volatility magnitude scale increases min_volume and min_liquidity
        strategy.default_params["min_volume_24h"] = 1000
        strategy.default_params["min_liquidity"] = 1000
        strategy.default_params["max_markets_per_cycle"] = 5
        strategy.default_params["web_search_enabled"] = False
        strategy.default_params["debate_enabled"] = False

        # Scenario A: Move is 10% (scaling_factor = 10.0 / 5.0 = 2.0x)
        # Dynamic threshold = 2000. Under this, volume = 1500 is skipped.
        mv = LineMovement(
            ticker="test-ticker",
            question="Will test happen?",
            current_price=0.5,
            price_1h_ago=0.45,
            price_change_pct=10.0,
            volume_24h=1500.0,
            condition_id="test-cond",
            token_id="test-token",
            liquidity=3000.0,
        )

        ctx = self._create_mock_context()
        result = await strategy._analyze_movement(mv, strategy.default_params, ctx)
        assert result is None

        # Scenario B: Move is 10% (scaling_factor = 2.0x -> dynamic liquidity threshold = 2000)
        # Liquidity = 1500 is skipped.
        mv_low_liq = LineMovement(
            ticker="test-ticker",
            question="Will test happen?",
            current_price=0.5,
            price_1h_ago=0.45,
            price_change_pct=10.0,
            volume_24h=3000.0,
            condition_id="test-cond",
            token_id="test-token",
            liquidity=1500.0,
        )
        result_low_liq = await strategy._analyze_movement(
            mv_low_liq, strategy.default_params, ctx
        )
        assert result_low_liq is None

    @pytest.mark.asyncio
    @patch("backend.strategies.line_movement_detector.get_shared_client")
    async def test_volatility_spread_rejection(self, mock_get_shared_client):
        strategy = LineMovementDetectorStrategy()
        strategy.default_params["min_volume_24h"] = 100
        strategy.default_params["min_liquidity"] = 100
        strategy.default_params["max_spread_pct"] = 0.05
        strategy.default_params["web_search_enabled"] = False
        strategy.default_params["debate_enabled"] = False

        mv = LineMovement(
            ticker="test-ticker",
            question="Will test happen?",
            current_price=0.5,
            price_1h_ago=0.47,
            price_change_pct=6.0,
            volume_24h=1000.0,
            condition_id="test-cond",
            token_id="test-token",
            liquidity=1000.0,
        )

        # Mock order book with wide spread: bid = 0.40, ask = 0.60 (mid = 0.50, spread = 0.20 -> 40%)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "bids": [{"price": "0.40", "size": "100"}],
            "asks": [{"price": "0.60", "size": "100"}],
        }

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_get_shared_client.return_value = mock_client

        ctx = self._create_mock_context()
        result = await strategy._analyze_movement(mv, strategy.default_params, ctx)
        # Spread is 40% > 5%, should reject (return None)
        assert result is None

    @pytest.mark.asyncio
    @patch("backend.strategies.line_movement_detector.get_shared_client")
    async def test_kinetics_flickering_rejection(self, mock_get_shared_client):
        strategy = LineMovementDetectorStrategy()
        strategy.default_params["min_volume_24h"] = 100
        strategy.default_params["min_liquidity"] = 100
        strategy.default_params["min_top_size"] = 5.0
        strategy.default_params["web_search_enabled"] = False
        strategy.default_params["debate_enabled"] = False

        mv = LineMovement(
            ticker="test-ticker",
            question="Will test happen?",
            current_price=0.5,
            price_1h_ago=0.47,
            price_change_pct=6.0,
            volume_24h=1000.0,
            condition_id="test-cond",
            token_id="test-token",
            liquidity=1000.0,
        )

        # Mock order book with unstable/tiny size: top bid size = 1.0 < 5.0
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "bids": [{"price": "0.49", "size": "1.0"}],
            "asks": [{"price": "0.51", "size": "10.0"}],
        }
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_get_shared_client.return_value = mock_client

        ctx = self._create_mock_context()
        result = await strategy._analyze_movement(mv, strategy.default_params, ctx)
        # Bid size is too small, should reject
        assert result is None

    @pytest.mark.asyncio
    @patch("backend.strategies.line_movement_detector.get_shared_client")
    async def test_kinetics_imbalance_rejection(self, mock_get_shared_client):
        strategy = LineMovementDetectorStrategy()
        strategy.default_params["min_volume_24h"] = 100
        strategy.default_params["min_liquidity"] = 100
        strategy.default_params["min_top_size"] = 1.0
        strategy.default_params["min_imbalance_ratio"] = -0.5
        strategy.default_params["web_search_enabled"] = False
        strategy.default_params["debate_enabled"] = False

        # Price change is positive (+6.0%) -> direction is "up"
        mv = LineMovement(
            ticker="test-ticker",
            question="Will test happen?",
            current_price=0.5,
            price_1h_ago=0.47,
            price_change_pct=6.0,
            volume_24h=1000.0,
            condition_id="test-cond",
            token_id="test-token",
            liquidity=1000.0,
        )

        # Bid depth = 10.0, Ask depth = 90.0
        # Imbalance = (10 - 90) / 100 = -0.80. Since direction is up, target_imbalance = -0.80 < -0.50 -> reject.
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "bids": [{"price": "0.49", "size": "10.0"}],
            "asks": [{"price": "0.51", "size": "90.0"}],
        }
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_get_shared_client.return_value = mock_client

        ctx = self._create_mock_context()
        result = await strategy._analyze_movement(mv, strategy.default_params, ctx)
        assert result is None

    @pytest.mark.asyncio
    @patch("backend.strategies.line_movement_detector.run_debate_with_routing")
    @patch("backend.strategies.line_movement_detector.get_shared_client")
    async def test_debate_gate_rejection(self, mock_get_shared_client, mock_debate):
        strategy = LineMovementDetectorStrategy()
        strategy.default_params["min_volume_24h"] = 100
        strategy.default_params["min_liquidity"] = 100
        strategy.default_params["min_top_size"] = 1.0
        strategy.default_params["min_imbalance_ratio"] = -0.9
        strategy.default_params["web_search_enabled"] = False
        strategy.default_params["debate_enabled"] = True

        mv = LineMovement(
            ticker="test-ticker",
            question="Will test happen?",
            current_price=0.5,
            price_1h_ago=0.47,
            price_change_pct=6.0,
            volume_24h=1000.0,
            condition_id="test-cond",
            token_id="test-token",
            liquidity=1000.0,
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "bids": [{"price": "0.49", "size": "10.0"}],
            "asks": [{"price": "0.51", "size": "10.0"}],
        }
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_get_shared_client.return_value = mock_client

        # Mock debate result rejecting the signal (confidence = 0.40 < 0.55)
        mock_debate_res = MagicMock()
        mock_debate_res.confidence = 0.40
        mock_debate.return_value = mock_debate_res

        ctx = self._create_mock_context()
        result = await strategy._analyze_movement(mv, strategy.default_params, ctx)
        assert result is None

    @pytest.mark.asyncio
    @patch("backend.strategies.line_movement_detector.run_debate_with_routing")
    @patch("backend.strategies.line_movement_detector.get_shared_client")
    async def test_successful_signal(self, mock_get_shared_client, mock_debate):
        strategy = LineMovementDetectorStrategy()
        strategy.default_params["min_volume_24h"] = 100
        strategy.default_params["min_liquidity"] = 100
        strategy.default_params["min_top_size"] = 1.0
        strategy.default_params["min_imbalance_ratio"] = -0.9
        strategy.default_params["web_search_enabled"] = False
        strategy.default_params["debate_enabled"] = True
        strategy.default_params["min_confidence_to_signal"] = 0.4

        mv = LineMovement(
            ticker="test-ticker",
            question="Will test happen?",
            current_price=0.5,
            price_1h_ago=0.47,
            price_change_pct=6.0,
            volume_24h=1000.0,
            condition_id="test-cond",
            token_id="test-token",
            liquidity=1000.0,
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "bids": [{"price": "0.49", "size": "10.0"}],
            "asks": [{"price": "0.51", "size": "10.0"}],
        }
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_get_shared_client.return_value = mock_client

        # Mock debate result accepting the signal (confidence = 0.80)
        mock_debate_res = MagicMock()
        mock_debate_res.confidence = 0.80
        mock_debate.return_value = mock_debate_res

        ctx = self._create_mock_context()
        result = await strategy._analyze_movement(mv, strategy.default_params, ctx)
        assert result is not None
        assert result["decision"] == "BUY"
        assert result["direction"] == "yes"
        assert result["confidence"] == 0.80
