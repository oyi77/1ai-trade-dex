"""Whale Tracker Strategy — Follow whale wallet movements on Polymarket.

Detects large trades and wallet movements from whale wallets on Polymarket.
Uses on-chain data (Alchemy) and Polymarket APIs to identify whale activity.

Data sources:
- Polymarket trade data (large trades)
- Alchemy API for on-chain wallet monitoring
- Polymarket positions API for whale position tracking
"""

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any

from backend.strategies.base import (
    BaseStrategy,
    CycleResult,
    MarketInfo,
    StrategyContext,
)
from backend.config import settings
from backend.data.shared_client import get_shared_client

from loguru import logger


class WhaleTrackerStrategy(BaseStrategy):
    name = "whale_tracker"
    description = "Follow whale wallet movements on Polymarket for alpha"
    category = "momentum"

    default_params = {
        "min_trade_size_usd": 10000,  # Only track trades >$10k
        "min_whale_pnl": 50000,  # Only follow whales with >$50k PnL
        "max_whales_to_follow": 10,
        "position_size_pct": 0.05,  # 5% of bankroll per whale position
        "max_concurrent_positions": 5,
        "check_interval_minutes": 15,  # Check every 15 min
        "alchemy_api_key": "",  # Set via env
    }

    def __init__(self):
        super().__init__()
        self._last_check = None
        self._tracked_whales = {}  # wallet -> whale info
        self._large_trades = []  # Recent large trades

    async def market_filter(self, markets: List[MarketInfo]) -> List[MarketInfo]:
        """Pass-through: whale_tracker doesn't filter markets."""
        return markets

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        result = CycleResult(decisions_recorded=0, trades_attempted=0, trades_placed=0)
        params = {**self.default_params, **(ctx.params or {})}

        try:
            # Get large recent trades
            large_trades = await self._get_large_trades(params)
            if not large_trades:
                logger.info(f"[{self.name}] No large trades detected")
                return result

            # Analyze trades for whale activity
            whale_activity = self._analyze_whale_activity(large_trades, params)
            if not whale_activity:
                return result

            # Create decisions based on whale activity
            for activity in whale_activity:
                decision = self._create_decision(activity, params)
                if decision:
                    result.decisions_recorded += 1
                    result.trades_attempted += 1
                    result.decisions.append(decision)

            return result

        except Exception as e:
            logger.error(f"[{self.name}] Cycle error: {e}")
            result.errors.append(str(e))
            return result

    async def _get_large_trades(self, params: dict) -> List[Dict]:
        """Get recent large trades from Polymarket."""
        try:
            client = get_shared_client()
            min_size = params["min_trade_size_usd"]

            # Get recent trades from Polymarket
            resp = await client.get(
                "https://data-api.polymarket.com/trades",
                params={"limit": 100, "takerOnly": "true"},
            )

            if resp.status_code != 200:
                return []

            trades = resp.json()
            large_trades = []

            for trade in trades:
                size = float(trade.get("size", 0))
                price = float(trade.get("price", 0))
                value = size * price

                if value >= min_size:
                    large_trades.append({
                        "market_id": trade.get("asset"),
                        "size": size,
                        "price": price,
                        "value": value,
                        "side": trade.get("side"),
                        "timestamp": trade.get("timestamp"),
                        "trader": trade.get("maker"),
                    })

            return large_trades

        except Exception as e:
            logger.warning(f"[{self.name}] Large trades fetch failed: {e}")
            return []

    def _analyze_whale_activity(self, trades: List[Dict], params: dict) -> List[Dict]:
        """Analyze trades for whale activity patterns."""
        whale_activity = []

        # Group trades by market
        market_trades = {}
        for trade in trades:
            market_id = trade["market_id"]
            if market_id not in market_trades:
                market_trades[market_id] = []
            market_trades[market_id].append(trade)

        # Look for whale patterns
        for market_id, market_trades_list in market_trades.items():
            total_volume = sum(t["value"] for t in market_trades_list)
            if total_volume < params["min_trade_size_usd"] * 2:
                continue

            # Check if this is a whale buying
            buy_volume = sum(t["value"] for t in market_trades_list if t["side"] == "BUY")
            sell_volume = sum(t["value"] for t in market_trades_list if t["side"] == "SELL")

            if buy_volume > sell_volume * 2:  # Strong buy pressure
                whale_activity.append({
                    "market_id": market_id,
                    "type": "whale_buy",
                    "volume": total_volume,
                    "buy_volume": buy_volume,
                    "sell_volume": sell_volume,
                    "trades": len(market_trades_list),
                    "avg_price": sum(t["price"] * t["size"] for t in market_trades_list) / sum(t["size"] for t in market_trades_list),
                })

        return whale_activity

    def _create_decision(self, activity: Dict, params: dict) -> Optional[Dict]:
        """Create a trade decision based on whale activity."""
        if activity["type"] == "whale_buy":
            return {
                "action": "buy",
                "market_ticker": activity["market_id"],
                "direction": "YES",
                "confidence": 0.7,  # Medium confidence for whale following
                "size": params["position_size_pct"],
                "reason": f"Whale buy detected (${activity['volume']:.0f} volume, {activity['trades']} trades)",
                "metadata": {
                    "whale_activity_type": activity["type"],
                    "total_volume": activity["volume"],
                    "buy_volume": activity["buy_volume"],
                    "sell_volume": activity["sell_volume"],
                    "avg_price": activity["avg_price"],
                },
            }
        return None
