"""Unified real-time balance aggregator across all trading venues.
Combines WebSocket feeds (Aster, Lighter, Hyperliquid) with polling (Polymarket, Kalshi, Ostium).
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Callable
from loguru import logger


@dataclass
class VenueBalance:
    """Balance snapshot for a single venue."""
    venue: str
    cash_balance: float = 0.0
    positions_value: float = 0.0
    total_equity: float = 0.0
    unrealized_pnl: float = 0.0
    last_updated: float = 0.0
    source: str = "poll"  # "ws" or "poll"


@dataclass
class AggregatedBalance:
    """Aggregated balance across all venues."""
    venues: Dict[str, VenueBalance] = field(default_factory=dict)
    total_equity: float = 0.0
    total_cash: float = 0.0
    total_positions: float = 0.0
    total_pnl: float = 0.0


class BalanceAggregator:
    """Aggregates real-time balance from all trading venues."""

    def __init__(self):
        self._balances: Dict[str, VenueBalance] = {}
        self._ws_tasks: Dict[str, asyncio.Task] = {}
        self._poll_task: Optional[asyncio.Task] = None
        self._callbacks: list[Callable] = []
        self._running = False

    def on_balance_update(self, callback: Callable):
        """Register callback for balance updates."""
        self._callbacks.append(callback)

    async def start(self):
        """Start all balance feeds."""
        if self._running:
            return
        self._running = True

        # Start WS feeds for venues that support it
        self._ws_tasks["aster"] = asyncio.create_task(self._ws_aster())
        self._ws_tasks["lighter"] = asyncio.create_task(self._ws_lighter())
        self._ws_tasks["hyperliquid"] = asyncio.create_task(self._ws_hyperliquid())

        # Start polling for venues without WS balance
        self._poll_task = asyncio.create_task(self._poll_loop())

        logger.info("BalanceAggregator started: 3 WS feeds + polling loop")

    async def stop(self):
        """Stop all feeds."""
        self._running = False
        for task in self._ws_tasks.values():
            task.cancel()
        if self._poll_task:
            self._poll_task.cancel()

    async def _ws_aster(self):
        """Aster WS balance feed."""
        try:
            from backend.clients.aster_client import AsterClient
            client = AsterClient()
            while self._running:
                try:
                    bal = await client.watch_balance()
                    self._update("aster", VenueBalance(
                        venue="aster",
                        cash_balance=float(bal.get("USDC", {}).get("free", 0)),
                        total_equity=float(bal.get("USDC", {}).get("total", 0)),
                        source="ws",
                    ))
                except Exception as e:
                    logger.warning(f"Aster WS balance error: {e}")
                    await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Aster WS feed failed: {e}")

    async def _ws_lighter(self):
        """Lighter balance feed — WS via watch_account() with REST fallback."""
        try:
            from backend.clients.lighter_client import LighterClient
            client = LighterClient()
            # Try WS first, fall back to REST polling
            ws_connected = False
            try:
                if hasattr(client, 'watch_account') and callable(client.watch_account):
                    ws_connected = True
                    while self._running:
                        try:
                            async for account_update in client.watch_account():
                                if not self._running:
                                    break
                                bal = account_update if isinstance(account_update, dict) else {}
                                self._update("lighter", VenueBalance(
                                    venue="lighter",
                                    cash_balance=float(bal.get("usdc", bal.get("balance", 0))),
                                    total_equity=float(bal.get("total", bal.get("equity", 0))),
                                    source="ws",
                                ))
                        except Exception as e:
                            logger.warning(f"Lighter WS error, falling back to REST: {e}")
                            ws_connected = False
                            break
            except Exception as e:
                logger.debug(f"Lighter WS not available, using REST: {e}")
                ws_connected = False

            # REST fallback
            if not ws_connected:
                while self._running:
                    try:
                        bal = await client.get_balance()
                        self._update("lighter", VenueBalance(
                            venue="lighter",
                            cash_balance=float(bal.get("usdc", 0)),
                            total_equity=float(bal.get("total", 0)),
                            source="poll",
                        ))
                    except Exception as e:
                        logger.warning(f"Lighter REST balance error: {e}")
                    await asyncio.sleep(15)
        except Exception as e:
            logger.error(f"Lighter feed failed: {e}")

    async def _ws_hyperliquid(self):
        """Hyperliquid balance feed — SDK WS subscription with REST fallback."""
        try:
            from backend.clients.hyperliquid_client import HyperliquidClient
            client = HyperliquidClient()
            # Try SDK WS for real-time balance updates
            ws_connected = False
            try:
                if hasattr(client, 'subscribe_user_events') and callable(client.subscribe_user_events):
                    ws_connected = True
                    async for event in client.subscribe_user_events():
                        if not self._running:
                            break
                        if event.get("type") in ("userFills", "balanceUpdate"):
                            state = await client.get_balance()
                            margin = state.get("marginSummary", {})
                            self._update("hyperliquid", VenueBalance(
                                venue="hyperliquid",
                                cash_balance=float(margin.get("totalRawUsd", 0)),
                                total_equity=float(margin.get("accountValue", 0)),
                                unrealized_pnl=float(margin.get("totalNtlPos", 0)) - float(margin.get("accountValue", 0)),
                                source="ws",
                            ))
            except Exception as e:
                logger.debug(f"Hyperliquid WS not available, using REST: {e}")
                ws_connected = False

            # REST fallback
            if not ws_connected:
                while self._running:
                    try:
                        state = await client.get_balance()
                        margin = state.get("marginSummary", {})
                        self._update("hyperliquid", VenueBalance(
                            venue="hyperliquid",
                            cash_balance=float(margin.get("totalRawUsd", 0)),
                            total_equity=float(margin.get("accountValue", 0)),
                            unrealized_pnl=float(margin.get("totalNtlPos", 0)) - float(margin.get("accountValue", 0)),
                            source="poll",
                        ))
                    except Exception as e:
                        logger.warning(f"Hyperliquid REST balance error: {e}")
                    await asyncio.sleep(10)
        except Exception as e:
            logger.error(f"Hyperliquid feed failed: {e}")

    async def _poll_loop(self):
        """Poll venues without WS balance support."""
        while self._running:
            try:
                # Polymarket
                try:
                    from backend.core.wallet.bankroll_reconciliation import fetch_pm_total_equity
                    equity = await fetch_pm_total_equity()
                    if equity is not None:
                        self._update("polymarket", VenueBalance(
                            venue="polymarket",
                            total_equity=float(equity),
                            source="poll",
                        ))
                except Exception as e:
                    logger.debug(f"Polymarket poll error: {e}")

                # Kalshi
                try:
                    from backend.markets.providers.kalshi_provider import KalshiProvider
                    provider = KalshiProvider()
                    bal = await provider.get_balance()
                    if bal:
                        self._update("kalshi", VenueBalance(
                            venue="kalshi",
                            cash_balance=float(bal.get("cash", 0)),
                            total_equity=float(bal.get("equity", 0)),
                            source="poll",
                        ))
                except Exception as e:
                    logger.debug(f"Kalshi poll error: {e}")

                # Ostium
                try:
                    from backend.clients.ostium_client import OstiumClient
                    client = OstiumClient()
                    bal = await client.get_balance()
                    if bal:
                        self._update("ostium", VenueBalance(
                            venue="ostium",
                            cash_balance=float(bal.get("usdc", 0)),
                            total_equity=float(bal.get("total", 0)),
                            source="poll",
                        ))
                except Exception as e:
                    logger.debug(f"Ostium poll error: {e}")

                # Myriad
                try:
                    from backend.clients.myriad_client import MyriadClient
                    client = MyriadClient()
                    bal = await client.get_balance()
                    if bal:
                        self._update("myriad", VenueBalance(
                            venue="myriad",
                            cash_balance=float(bal),
                            total_equity=float(bal),
                            source="poll",
                        ))
                except Exception as e:
                    logger.debug(f"Myriad poll error: {e}")

                # SXBet
                try:
                    from backend.clients.sxbet_client import SXBetClient
                    client = SXBetClient()
                    bal = await client.get_balance()
                    if bal:
                        val = float(bal.get("balance", bal.get("value", 0)))
                        if val > 1e6:
                            val = val / 1e6  # Wei to USDC
                        self._update("sxbet", VenueBalance(
                            venue="sxbet",
                            cash_balance=val,
                            total_equity=val,
                            source="poll",
                        ))
                except Exception as e:
                    logger.debug(f"SXBet poll error: {e}")

                # Limitless
                try:
                    from backend.clients.limitless_client import LimitlessClient
                    client = LimitlessClient()
                    bal = await client.get_balance()
                    if bal:
                        self._update("limitless", VenueBalance(
                            venue="limitless",
                            cash_balance=float(bal.get("balance", bal.get("value", 0))),
                            total_equity=float(bal.get("balance", bal.get("value", 0))),
                            source="poll",
                        ))
                except Exception as e:
                    logger.debug(f"Limitless poll error: {e}")

                # Azuro
                try:
                    from backend.clients.azuro_client import AzuroClient
                    client = AzuroClient()
                    bal = await client.get_balance()
                    if bal:
                        self._update("azuro", VenueBalance(
                            venue="azuro",
                            cash_balance=float(bal.get("balance", bal.get("value", 0))),
                            total_equity=float(bal.get("balance", bal.get("value", 0))),
                            source="poll",
                        ))
                except Exception as e:
                    logger.debug(f"Azuro poll error: {e}")

            except Exception as e:
                logger.warning(f"Poll loop error: {e}")

            await asyncio.sleep(30)  # Poll every 30s

    def _update(self, venue: str, balance: VenueBalance):
        """Update balance and notify callbacks."""
        balance.last_updated = time.time()
        self._balances[venue] = balance
        self._notify()

    def _notify(self):
        """Notify all callbacks with aggregated balance."""
        agg = self.get_aggregated()
        for cb in self._callbacks:
            try:
                cb(agg)
            except Exception as e:
                logger.warning(f"Balance callback error: {e}")

    def get_aggregated(self) -> AggregatedBalance:
        """Get aggregated balance across all venues."""
        agg = AggregatedBalance(venues=dict(self._balances))
        for v in self._balances.values():
            agg.total_equity += v.total_equity
            agg.total_cash += v.cash_balance
            agg.total_positions += v.positions_value
            agg.total_pnl += v.unrealized_pnl
        return agg

    def get_venue_balance(self, venue: str) -> Optional[VenueBalance]:
        """Get balance for a specific venue."""
        return self._balances.get(venue)
