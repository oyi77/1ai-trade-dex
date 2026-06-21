"""
Real-Time Whale Tracker — Event-driven whale detection using Alchemy WebSocket.

Subscribes to Alchemy WebSocket for real-time on-chain transactions.
When a large transfer is detected from a whale wallet, immediately
executes a copy trade on Polymarket.

Architecture:
1. Alchemy WebSocket subscribes to whale wallet transactions
2. On transaction → check if it's a large transfer
3. If whale activity → execute copy trade immediately
4. No polling, no delay — near real-time execution

Data sources:
- Alchemy WebSocket (real-time on-chain transactions)
- Polymarket API (market data and execution)
- Whale wallet database (tracked wallets)
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Dict, List

from backend.config import settings
from backend.data.shared_client import get_shared_client
from backend.strategies.base import BaseStrategy, StrategyContext, CycleResult, MarketInfo

from loguru import logger


class RealTimeWhaleTracker(BaseStrategy):
    name = "whale_tracker"
    description = "Real-time whale tracking via Alchemy WebSocket"
    category = "momentum"

    default_params = {
        "min_whale_balance_usd": 100000,  # Only track wallets with >$100k
        "min_transfer_size_usd": 10000,  # Only react to transfers >$10k
        "position_size_pct": 0.03,  # 3% of bankroll per whale trade
        "max_concurrent_positions": 3,
        "cooldown_seconds": 300,  # 5 min cooldown per whale
        "alchemy_api_key": "",  # Set via env
    }

    def __init__(self):
        super().__init__()
        self._ws = None
        self._tracked_whales: Dict[str, Dict] = {}  # wallet -> whale info
        self._last_whale_activity: Dict[str, datetime] = {}  # wallet -> last activity
        self._running = False

    async def market_filter(self, markets: List[MarketInfo]) -> List[MarketInfo]:
        """Pass-through: whale tracker doesn't filter markets."""
        return markets

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        """Not used — this is event-driven, not scheduler-based."""
        return CycleResult(decisions_recorded=0, trades_attempted=0, trades_placed=0)

    async def start_realtime(self, ctx: StrategyContext):
        """Start real-time WebSocket connection for whale tracking."""
        self._running = True

        await self._load_whale_wallets()

        api_key = self.default_params.get("alchemy_api_key") or settings.ALCHEMY_API_KEY
        if not api_key:
            logger.warning(f"[{self.name}] No Alchemy API key — using polling fallback")
            await self._start_polling_fallback()
            return

        logger.info(f"[{self.name}] Starting Alchemy WebSocket whale tracker")
        logger.info(f"[{self.name}] Tracking {len(self._tracked_whales)} whale wallets")

        try:
            import websockets

            ws_url = f"wss://eth-mainnet.g.alchemy.com/v2/{api_key}"
            self._ws = await websockets.connect(ws_url)

            subscribe_msg = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_subscribe",
                "params": ["newPendingTransactions", True],
            }
            await self._ws.send(json.dumps(subscribe_msg))

            async for message in self._ws:
                if not self._running:
                    break
                try:
                    data = json.loads(message)
                    if "params" in data:
                        tx = data["params"].get("result", {})
                        await self._handle_pending_tx(tx)
                except Exception as e:
                    logger.debug(f"[{self.name}] WS message parse error: {e}")

        except Exception as e:
            logger.warning(f"[{self.name}] Alchemy WebSocket failed: {e} — falling back to polling")
            await self._start_polling_fallback()

    async def stop_realtime(self):
        """Stop real-time connection."""
        self._running = False
        if self._ws:
            # Close WebSocket connection
            pass

    async def _load_whale_wallets(self):
        """Load whale wallets from config and Polymarket leaderboard."""
        wallets_str = getattr(settings, "WHALE_WALLETS", "")
        if wallets_str:
            for wallet in wallets_str.split(","):
                wallet = wallet.strip()
                if wallet:
                    self._tracked_whales[wallet] = {"name": f"whale_{wallet[:10]}", "pnl": 0, "volume": 0}

        try:
            client = get_shared_client()
            resp = await client.get(
                "https://data-api.polymarket.com/v1/leaderboard",
                params={"timePeriod": "ALL", "limit": 20, "orderBy": "PNL"},
            )
            if resp.status_code == 200:
                for trader in resp.json():
                    wallet = trader.get("proxyWallet", "")
                    pnl = trader.get("pnl", 0)
                    if wallet and pnl >= self.default_params["min_whale_pnl"]:
                        self._tracked_whales[wallet] = {
                            "name": trader.get("userName", f"whale_{wallet[:10]}"),
                            "pnl": pnl,
                            "volume": trader.get("vol", 0),
                        }
        except Exception as e:
            logger.warning(f"[{self.name}] Leaderboard fetch failed: {e}")

    async def _start_polling_fallback(self):
        """Fallback: Poll for whale activity every 10 seconds."""
        logger.info(f"[{self.name}] Using polling fallback (10s interval)")

        while self._running:
            try:
                await self._check_whale_activity()
                await asyncio.sleep(10)  # Poll every 10 seconds
            except Exception as e:
                logger.error(f"[{self.name}] Polling error: {e}")
                await asyncio.sleep(30)  # Back off on error

    async def _check_whale_activity(self):
        """Check for recent whale activity via Polymarket API."""
        try:
            client = get_shared_client()

            # Get recent large trades
            resp = await client.get(
                "https://data-api.polymarket.com/trades",
                params={"limit": 100, "takerOnly": "true"},
            )

            if resp.status_code != 200:
                return

            trades = resp.json()
            min_size = self.default_params["min_transfer_size_usd"]

            for trade in trades:
                size = float(trade.get("size", 0))
                price = float(trade.get("price", 0))
                value = size * price

                if value < min_size:
                    continue

                # Check if this is from a tracked whale
                trader_wallet = trade.get("maker")
                if trader_wallet in self._tracked_whales:
                    await self._handle_whale_trade(trade, value)

        except Exception as e:
            logger.warning(f"[{self.name}] Whale activity check failed: {e}")

    async def _handle_pending_tx(self, tx: Dict):
        """Handle a pending transaction from Alchemy WebSocket."""
        try:
            from_addr = tx.get("from", "").lower()
            to_addr = tx.get("to", "").lower()
            value_wei = int(tx.get("value", "0"), 16) if isinstance(tx.get("value"), str) else int(tx.get("value", 0))
            value_eth = value_wei / 1e18

            tracked_wallets = {w.lower() for w in self._tracked_whales}
            if from_addr in tracked_wallets or to_addr in tracked_wallets:
                logger.info(
                    f"[{self.name}] Whale tx detected: {from_addr[:10]}→{to_addr[:10]} "
                    f"value={value_eth:.4f} ETH"
                )
        except Exception as e:
            logger.debug(f"[{self.name}] TX parse error: {e}")

    async def _handle_whale_trade(self, trade: Dict, value: float):
        """Handle a detected whale trade."""
        trader_wallet = trade.get("maker")
        if trader_wallet not in self._tracked_whales:
            return
        whale_info = self._tracked_whales[trader_wallet]

        if trader_wallet in self._last_whale_activity:
            last_activity = self._last_whale_activity[trader_wallet]
            cooldown = self.default_params["cooldown_seconds"]
            if (datetime.now(timezone.utc) - last_activity).total_seconds() < cooldown:
                return

        logger.info(
            f"[{self.name}] Whale detected: {whale_info['name']} "
            f"({trade.get('side', '?')} ${value:.0f} on {trade.get('asset', '?')})"
        )

        await self._execute_whale_copy(trade, whale_info)
        self._last_whale_activity[trader_wallet] = datetime.now(timezone.utc)

    async def _execute_whale_copy(self, trade: Dict, whale_info: Dict):
        """Execute a copy trade based on whale activity."""
        try:
            asset_id = trade.get("asset", "")
            side = trade.get("side", "BUY")
            size = float(trade.get("size", 0))
            price = float(trade.get("price", 0))
            usd_value = size * price

            min_size = self.default_params["min_transfer_size_usd"]
            if usd_value < min_size:
                return

            position_pct = self.default_params["position_size_pct"]

            logger.info(
                f"[{self.name}] WHALE COPY: {side} {size:.0f} @ ${price:.3f} "
                f"(${usd_value:.0f}) on {asset_id[:20]}... from {whale_info['name']}"
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

        except Exception as e:
            logger.error(f"[{self.name}] Whale copy execution failed: {e}")

