"""Copy Trader Strategy — Mirror top Polymarket traders' positions.

Identifies profitable traders via leaderboard API and mirrors their
positions in real-time. Uses position sizing based on trader confidence
and our bankroll.

Data sources:
- Polymarket leaderboard API (/v1/leaderboard)
- Polymarket positions API (/positions?user=wallet)
- Polymarket CLOB for order execution
"""

import asyncio
from datetime import datetime, timezone
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


class CopyTraderStrategy(BaseStrategy):
    name = "copy_trader"
    description = "Mirror top Polymarket traders' positions in real-time"
    category = "momentum"

    default_params = {
        "min_trader_pnl": 10000,  # Only copy traders with >$10k PnL
        "min_trader_win_rate": 0.55,  # Only copy traders with >55% WR
        "max_traders_to_copy": 5,  # Copy top 5 traders
        "position_size_pct": 0.10,  # 10% of bankroll per position
        "max_concurrent_positions": 10,
        "check_interval_minutes": 30,  # Check traders every 30 min
        "min_position_size_usd": 5.0,
    }

    def __init__(self):
        super().__init__()
        self._last_check = None
        self._tracked_traders = {}  # wallet -> trader info
        self._our_positions = {}  # market_id -> position info

    async def market_filter(self, markets: List[MarketInfo]) -> List[MarketInfo]:
        """Pass-through: copy_trader doesn't filter markets."""
        return markets

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        result = CycleResult(decisions_recorded=0, trades_attempted=0, trades_placed=0)
        params = {**self.default_params, **(ctx.params or {})}

        try:
            # Get leaderboard data
            leaderboard = await self._get_leaderboard(params)
            if not leaderboard:
                logger.warning(f"[{self.name}] No leaderboard data")
                return result

            # Filter for profitable traders
            good_traders = self._filter_traders(leaderboard, params)
            if not good_traders:
                logger.info(f"[{self.name}] No traders meet criteria")
                return result

            # Get positions for top traders
            for trader in good_traders[:params["max_traders_to_copy"]]:
                positions = await self._get_trader_positions(trader["wallet"])
                if not positions:
                    continue

                # Find new positions we should copy
                new_positions = self._find_new_positions(positions, trader)
                for pos in new_positions:
                    decision = self._create_decision(pos, trader, params)
                    if decision:
                        result.decisions_recorded += 1
                        result.trades_attempted += 1
                        result.decisions.append(decision)

            return result

        except Exception as e:
            logger.error(f"[{self.name}] Cycle error: {e}")
            result.errors.append(str(e))
            return result

    async def _get_leaderboard(self, params: dict) -> List[Dict]:
        """Get Polymarket leaderboard data."""
        try:
            client = get_shared_client()
            resp = await client.get(
                "https://data-api.polymarket.com/v1/leaderboard",
                params={
                    "timePeriod": "MONTH",
                    "limit": 50,
                    "orderBy": "PNL",
                },
            )
            if resp.status_code == 200:
                return resp.json()
            return []
        except Exception as e:
            logger.warning(f"[{self.name}] Leaderboard fetch failed: {e}")
            return []

    def _filter_traders(self, leaderboard: List[Dict], params: dict) -> List[Dict]:
        """Filter traders based on PnL and win rate criteria."""
        min_pnl = params["min_trader_pnl"]
        min_wr = params["min_trader_win_rate"]

        good_traders = []
        for trader in leaderboard:
            pnl = trader.get("pnl", 0)
            win_rate = trader.get("winRate", 0)
            trades = trader.get("numTrades", 0)

            if pnl >= min_pnl and win_rate >= min_wr and trades >= 50:
                good_traders.append({
                    "wallet": trader.get("proxyWallet"),
                    "name": trader.get("userName", "?"),
                    "pnl": pnl,
                    "win_rate": win_rate,
                    "trades": trades,
                })

        return sorted(good_traders, key=lambda x: x["pnl"], reverse=True)

    async def _get_trader_positions(self, wallet: str) -> List[Dict]:
        """Get current positions for a trader."""
        try:
            client = get_shared_client()
            resp = await client.get(
                "https://data-api.polymarket.com/positions",
                params={"user": wallet, "limit": 20},
            )
            if resp.status_code == 200:
                return resp.json()
            return []
        except Exception as e:
            logger.warning(f"[{self.name}] Positions fetch failed for {wallet[:10]}: {e}")
            return []

    def _find_new_positions(self, positions: List[Dict], trader: Dict) -> List[Dict]:
        """Find positions we should copy (not already copying)."""
        new_positions = []
        for pos in positions:
            market_id = pos.get("asset")  # token_id
            size = pos.get("size", 0)
            cur_price = pos.get("curPrice", 0)

            # Skip tiny positions
            if size * cur_price < 100:  # <$100 position
                continue

            # Skip if we already have this position
            if market_id in self._our_positions:
                continue

            new_positions.append({
                "market_id": market_id,
                "size": size,
                "price": cur_price,
                "title": pos.get("title", "?"),
                "outcome": pos.get("outcome", "?"),
                "trader_wallet": trader["wallet"],
                "trader_name": trader["name"],
            })

        return new_positions

    def _create_decision(self, position: Dict, trader: Dict, params: dict) -> Optional[Dict]:
        """Create a trade decision for copying a position."""
        # Calculate position size based on our bankroll
        # This will be handled by the strategy executor
        return {
            "action": "buy",
            "market_ticker": position["market_id"],
            "direction": position.get("outcome", "YES"),
            "confidence": min(0.9, trader["win_rate"]),  # Cap at 90%
            "size": params["position_size_pct"],  # % of bankroll
            "reason": f"Copy {trader['name']} (PnL: ${trader['pnl']:.0f}, WR: {trader['win_rate']:.0%})",
            "metadata": {
                "trader_wallet": trader["wallet"],
                "trader_name": trader["name"],
                "trader_pnl": trader["pnl"],
                "trader_win_rate": trader["win_rate"],
                "original_size": position["size"],
                "original_price": position["price"],
            },
        }
