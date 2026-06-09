"""
Real-Time Copy Trader — Event-driven copy trading using Polymarket WebSocket.

Subscribes to Polymarket WebSocket for real-time trade events.
When a large trade is detected from a profitable trader, immediately
mirrors the position.

Architecture:
1. WebSocket subscribes to market trades
2. On trade event → check if trader is on leaderboard
3. If profitable trader → execute copy trade immediately
4. No polling, no delay — near real-time execution

Data sources:
- Polymarket WebSocket (real-time trades)
- Polymarket leaderboard API (trader performance)
- Polymarket CLOB (order execution)
"""

import asyncio
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set, Any

from backend.config import settings
from backend.data.polymarket_websocket import (
    PolymarketWebSocket,
    WebSocketConfig,
    ChannelType,
    EventType,
    TradeEvent,
)
from backend.data.shared_client import get_shared_client
from backend.strategies.base import BaseStrategy, StrategyContext, CycleResult, MarketInfo

from loguru import logger


class RealTimeCopyTrader(BaseStrategy):
    name = "copy_trader"
    description = "Real-time copy trading via Polymarket WebSocket"
    category = "momentum"

    default_params = {
        "min_trader_pnl": 10000,  # Only copy traders with >$10k PnL
        "min_trader_volume": 100000,  # Only copy traders with >$100k volume
        "max_traders_to_copy": 5,  # Copy top 5 traders
        "min_trade_size_usd": 1000,  # Only copy trades >$1k
        "position_size_pct": 0.05,  # 5% of bankroll per copy
        "cooldown_seconds": 60,  # Don't copy same trader within 60s
        "max_concurrent_positions": 5,
    }

    def __init__(self):
        super().__init__()
        self._ws: Optional[PolymarketWebSocket] = None
        self._leaderboard_cache: Dict[str, Dict] = {}  # wallet -> trader info
        self._last_leaderboard_update: Optional[datetime] = None
        self._copied_wallets: Dict[str, datetime] = {}  # wallet -> last copy time
        self._running = False

    async def market_filter(self, markets: List[MarketInfo]) -> List[MarketInfo]:
        """Pass-through: copy trader doesn't filter markets."""
        return markets

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        """Not used — this is event-driven, not scheduler-based."""
        return CycleResult(decisions_recorded=0, trades_attempted=0, trades_placed=0)

    async def start_realtime(self, ctx: StrategyContext):
        """Start real-time WebSocket connection for copy trading."""
        self._running = True

        # Update leaderboard cache
        await self._update_leaderboard()

        # Connect to Polymarket WebSocket with reconnection logic
        config = WebSocketConfig(
            channel=ChannelType.MARKET,
            asset_ids=[],  # Subscribe to all markets
        )

        self._ws = PolymarketWebSocket(config)

        # Register trade event handler
        self._ws.on_trade(self._on_trade)

        logger.info(f"[{self.name}] Starting real-time copy trader")
        logger.info(f"[{self.name}] Tracking {len(self._leaderboard_cache)} profitable traders")

        # Start WebSocket connection with reconnection retry
        max_retries = 3
        retry_delay = 5  # seconds
        for attempt in range(max_retries):
            try:
                await self._ws.connect()
                logger.info(f"[{self.name}] WebSocket connected successfully")
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(
                        f"[{self.name}] WebSocket connection failed (attempt {attempt + 1}/{max_retries}): {e} "
                        f"— retrying in {retry_delay}s"
                    )
                    await asyncio.sleep(retry_delay)
                else:
                    logger.error(f"[{self.name}] WebSocket connection failed after {max_retries} attempts: {e}")
                    self._running = False
                    raise

    async def stop_realtime(self):
        """Stop real-time connection."""
        self._running = False
        if self._ws:
            await self._ws.disconnect()

    async def _on_trade(self, event: TradeEvent):
        """Handle real-time trade events from WebSocket."""
        try:
            # Extract trader wallet from event (this depends on Polymarket WS format)
            # For now, we'll check against our leaderboard cache
            trader_wallet = self._extract_trader_wallet(event)

            if not trader_wallet:
                return

            # Check if this trader is on our leaderboard
            trader_info = self._leaderboard_cache.get(trader_wallet)
            if not trader_info:
                return

            # Check cooldown
            if trader_wallet in self._copied_wallets:
                last_copy = self._copied_wallets[trader_wallet]
                cooldown = self.default_params["cooldown_seconds"]
                if (datetime.now(timezone.utc) - last_copy).total_seconds() < cooldown:
                    return

            # Check trade size
            trade_size = float(event.size) * float(event.price)
            if trade_size < self.default_params["min_trade_size_usd"]:
                return

            # Execute copy trade
            logger.info(
                f"[{self.name}] Copying trade from {trader_info['name']} "
                f"(PnL: ${trader_info['pnl']:.0f}, Vol: ${trader_info['volume']:.0f})"
            )

            await self._execute_copy(event, trader_info)

            # Update cooldown
            self._copied_wallets[trader_wallet] = datetime.now(timezone.utc)

        except Exception as e:
            logger.error(f"[{self.name}] Trade event handler error: {e}")

    def _extract_trader_wallet(self, event: TradeEvent) -> Optional[str]:
        """Extract trader wallet from trade event.

        Polymarket WebSocket trade events don't directly expose the trader wallet.
        Instead, we check if the asset_id matches any tracked trader's known positions.
        """
        asset_id = getattr(event, "asset_id", None)
        if not asset_id:
            return None

        for wallet, info in self._leaderboard_cache.items():
            known_positions = info.get("positions", {})
            if asset_id in known_positions:
                return wallet
        return None

    async def _execute_copy(self, event: TradeEvent, trader_info: Dict):
        """Execute a copy trade via Polymarket CLOB or paper simulation."""
        try:
            asset_id = getattr(event, "asset_id", None)
            side = getattr(event, "side", "BUY")
            size = float(getattr(event, "size", 0))
            price = float(getattr(event, "price", 0))
            usd_value = size * price

            if usd_value < self.default_params["min_trade_size_usd"]:
                return

            position_pct = self.default_params["position_size_pct"]

            logger.info(
                f"[{self.name}] COPY TRADE: {side} {size:.0f} @ ${price:.3f} "
                f"(${usd_value:.0f}) on {asset_id[:20]}... from {trader_info['name']}"
            )

            from backend.data.polymarket_clob import PolymarketCLOB

            try:
                clob = PolymarketCLOB(settings, simulation=True)
                order_result = await clob.place_limit_order(
                    token_id=asset_id,
                    side=side,
                    price=price,
                    size=size * position_pct,
                )
                logger.info(f"[{self.name}] Order placed: {order_result}")
            except Exception as clob_err:
                logger.warning(f"[{self.name}] CLOB order failed (paper mode OK): {clob_err}")

            self._log_trade(asset_id, side, size, price, trader_info)

        except Exception as e:
            logger.error(f"[{self.name}] Copy execution failed: {e}")

    async def _update_leaderboard(self):
        """Update leaderboard cache from Polymarket API."""
        try:
            client = get_shared_client()
            # Add 10s timeout to prevent hanging on slow API
            resp = await asyncio.wait_for(
                client.get(
                    "https://data-api.polymarket.com/v1/leaderboard",
                    params={
                        "timePeriod": "MONTH",
                        "limit": 50,
                        "orderBy": "PNL",
                    },
                ),
                timeout=10.0,
            )

            if resp.status_code == 200:
                traders = resp.json()
                self._leaderboard_cache.clear()

                for trader in traders:
                    wallet = trader.get("proxyWallet")
                    pnl = trader.get("pnl", 0)
                    vol = trader.get("vol", 0)

                    if (pnl >= self.default_params["min_trader_pnl"] and
                        vol >= self.default_params["min_trader_volume"]):

                        self._leaderboard_cache[wallet] = {
                            "wallet": wallet,
                            "name": trader.get("userName", "?"),
                            "pnl": pnl,
                            "volume": vol,
                        }

                self._last_leaderboard_update = datetime.now(timezone.utc)
                logger.info(
                    f"[{self.name}] Updated leaderboard: {len(self._leaderboard_cache)} profitable traders"
                )

        except Exception as e:
            logger.warning(f"[{self.name}] Leaderboard update failed: {e}")
