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

        self._register_db_persistence()

        # Start WS feeds for venues that support it
        self._ws_tasks["aster"] = asyncio.create_task(self._ws_aster())
        self._ws_tasks["lighter"] = asyncio.create_task(self._ws_lighter())
        self._ws_tasks["hyperliquid"] = asyncio.create_task(self._ws_hyperliquid())

        # Start polling for venues without WS balance
        self._poll_task = asyncio.create_task(self._poll_loop())

        logger.info("BalanceAggregator started: 3 WS feeds + polling loop")

    def _register_db_persistence(self):
        """Register callback that persists balance snapshots to PlatformBalance table."""
        async def _persist(agg: AggregatedBalance):
            try:
                from backend.models.database import PlatformBalance
                from backend.db.utils import get_db_session
                from datetime import datetime, timezone

                with get_db_session() as db:
                    now = datetime.now(timezone.utc)
                    for venue_name, vb in agg.venues.items():
                        existing = (
                            db.query(PlatformBalance)
                            .filter_by(platform=venue_name, mode="live")
                            .first()
                        )
                        if existing:
                            existing.available_cash = vb.cash_balance
                            existing.locked_margin = max(0, vb.total_equity - vb.cash_balance)
                            existing.total_equity = vb.total_equity
                            existing.synced_at = now
                            existing.error = None
                        else:
                            db.add(PlatformBalance(
                                platform=venue_name,
                                mode="live",
                                available_cash=vb.cash_balance,
                                locked_margin=max(0, vb.total_equity - vb.cash_balance),
                                total_equity=vb.total_equity,
                                synced_at=now,
                            ))
                    db.commit()
            except Exception as e:
                logger.debug(f"BalanceAggregator DB persist error: {e}")

        self.on_balance_update(lambda agg: asyncio.ensure_future(_persist(agg)))

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
                    self._update(
                        "aster",
                        VenueBalance(
                            venue="aster",
                            cash_balance=float(bal.get("USDC", {}).get("free", 0)),
                            total_equity=float(bal.get("USDC", {}).get("total", 0)),
                            source="ws",
                        ),
                    )
                except Exception as e:
                    logger.warning(f"Aster WS balance error: {e}")
                    await asyncio.sleep(5)
                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Aster WS feed failed: {e}")

    async def _ws_lighter(self):
        """Lighter balance feed — REST polling fallback."""
        try:
            from backend.clients.lighter_client import LighterClient

            client = LighterClient()
            ws_connected = False

            # REST fallback
            if not ws_connected:
                while self._running:
                    try:
                        bal = await client.get_balance()
                        self._update(
                            "lighter",
                            VenueBalance(
                                venue="lighter",
                                cash_balance=float(bal.get("usdc", 0)),
                                total_equity=float(bal.get("total", 0)),
                                source="poll",
                            ),
                        )
                    except Exception as e:
                        if "couldn't get nonce" not in str(e):
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
                if hasattr(client, "subscribe_user_events") and callable(
                    client.subscribe_user_events
                ):
                    ws_connected = True
                    async for event in client.subscribe_user_events():
                        if not self._running:
                            break
                        if event.get("type") in ("userFills", "balanceUpdate"):
                            state = await client.get_balance()
                            margin = state.get("marginSummary", {})
                            self._update(
                                "hyperliquid",
                                VenueBalance(
                                    venue="hyperliquid",
                                    cash_balance=float(margin.get("totalRawUsd", 0)),
                                    total_equity=float(margin.get("accountValue", 0)),
                                    unrealized_pnl=float(margin.get("totalNtlPos", 0))
                                    - float(margin.get("accountValue", 0)),
                                    source="ws",
                                ),
                            )
            except Exception as e:
                logger.debug(f"Hyperliquid WS not available, using REST: {e}")
                ws_connected = False

            # REST fallback
            if not ws_connected:
                while self._running:
                    try:
                        state = await client.get_balance()
                        margin = state.get("marginSummary", {})
                        self._update(
                            "hyperliquid",
                            VenueBalance(
                                venue="hyperliquid",
                                cash_balance=float(margin.get("totalRawUsd", 0)),
                                total_equity=float(margin.get("accountValue", 0)),
                                unrealized_pnl=float(margin.get("totalNtlPos", 0))
                                - float(margin.get("accountValue", 0)),
                                source="poll",
                            ),
                        )
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
                    from backend.core.wallet.bankroll_reconciliation import (
                        fetch_pm_total_equity,
                    )

                    equity = await fetch_pm_total_equity()
                    cash_balance = 0.0
                    # Fetch CLOB-internal PUSD balance
                    try:
                        from backend.config import settings as _cfg

                        if _cfg.POLYMARKET_PRIVATE_KEY:
                            from backend.data.polymarket_clob import clob_from_settings

                            async with clob_from_settings(mode="live") as clob:
                                pusd = await clob.get_pusd_balance()
                                if pusd > 0:
                                    cash_balance = pusd
                    except Exception as pusd_err:
                        logger.debug(f"PUSD balance fetch error: {pusd_err}")
                    if equity is not None:
                        self._update(
                            "polymarket",
                            VenueBalance(
                                venue="polymarket",
                                cash_balance=cash_balance,
                                total_equity=float(equity),
                                source="poll",
                            ),
                        )
                except Exception as e:
                    logger.debug(f"Polymarket poll error: {e}")

                # Kalshi
                try:
                    from backend.markets.providers.kalshi_provider import KalshiProvider

                    provider = KalshiProvider()
                    bal = await provider.get_balance()
                    if bal:
                        self._update(
                            "kalshi",
                            VenueBalance(
                                venue="kalshi",
                                cash_balance=float(bal.get("cash", 0)),
                                total_equity=float(bal.get("equity", 0)),
                                source="poll",
                            ),
                        )
                except Exception as e:
                    logger.debug(f"Kalshi poll error: {e}")

                # Ostium
                try:
                    from backend.clients.ostium_client import OstiumClient

                    client = OstiumClient()
                    bal = await client.get_balance()
                    if bal:
                        self._update(
                            "ostium",
                            VenueBalance(
                                venue="ostium",
                                cash_balance=float(bal.get("usdc", 0)),
                                total_equity=float(bal.get("total", 0)),
                                source="poll",
                            ),
                        )
                except Exception as e:
                    logger.debug(f"Ostium poll error: {e}")

                # Myriad
                try:
                    from backend.clients.myriad_client import MyriadClient

                    client = MyriadClient()
                    bal = await client.get_balance()
                    if bal:
                        self._update(
                            "myriad",
                            VenueBalance(
                                venue="myriad",
                                cash_balance=float(bal),
                                total_equity=float(bal),
                                source="poll",
                            ),
                        )
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
                        self._update(
                            "sxbet",
                            VenueBalance(
                                venue="sxbet",
                                cash_balance=val,
                                total_equity=val,
                                source="poll",
                            ),
                        )
                except Exception as e:
                    logger.debug(f"SXBet poll error: {e}")
                try:
                    from backend.clients.azuro_client import AzuroClient

                    client = AzuroClient()
                    bal = await client.get_balance()
                    if bal:
                        val = float(bal.get("balance", 0))
                        self._update(
                            "bookmaker_xyz",
                            VenueBalance(
                                venue="bookmaker_xyz",
                                cash_balance=val,
                                total_equity=val,
                                source="poll",
                            ),
                        )
                        self._update(
                            "predict_fun",
                            VenueBalance(
                                venue="predict_fun",
                                cash_balance=val,
                                total_equity=val,
                                source="poll",
                            ),
                        )
                except Exception as e:
                    logger.debug(f"Azuro poll error: {e}")

            except Exception as e:
                logger.warning(f"Poll loop error: {e}")

            await asyncio.sleep(getattr(settings, "BALANCE_POLL_INTERVAL_SECONDS", 30))

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
