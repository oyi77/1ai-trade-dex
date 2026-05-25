"""Ostium activity source — SDK polling for trades and position changes."""

from __future__ import annotations
import asyncio

from backend.core.activity.models import ActivityEvent
from backend.core.activity.sources.base import BaseActivitySource
from loguru import logger


class OstiumActivitySource(BaseActivitySource):
    """Poll Ostium SDK for trade fills and position changes."""

    def __init__(self, wallet_address: str, ostium_client=None):
        super().__init__(wallet_address, "ostium")
        self._client = ostium_client
        self._seen_trades: set[str] = set()
        self._last_positions: list[dict] = []
        self._fills_interval = 10
        self._positions_interval = 15

    async def _run(self):
        if not self._client:
            logger.warning("[ostium] No client provided, skipping activity source")
            return
        try:
            self.create_subtask(self._fills_loop())
            self.create_subtask(self._positions_loop())
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("[ostium] Activity source error: {e}")

    async def _fills_loop(self):
        """Poll Ostium fills for recent trades."""
        while self._running:
            try:
                fills = await self._client.get_fills(wallet_address=self.wallet_address, limit=100)
                for fill in fills:
                    trade_id = fill.get("id", fill.get("tradeId", fill.get("hash", "")))
                    if trade_id in self._seen_trades:
                        continue
                    self._seen_trades.add(trade_id)

                    side = fill.get("direction", fill.get("side", "")).lower()
                    amount = float(fill.get("collateral", fill.get("size", 0)))
                    price = float(fill.get("entryPrice", fill.get("price", 0)))
                    fee = float(fill.get("fee", 0))
                    pnl = float(fill.get("pnl", 0)) if fill.get("pnl") else None
                    market = fill.get("pair", fill.get("market", fill.get("symbol", "")))
                    is_open = fill.get("status", "") != "closed"

                    event = ActivityEvent(
                        source="ostium",
                        event_type="trade_open" if is_open else "trade_closed",
                        wallet_address=self.wallet_address,
                        platform="ostium",
                        amount=amount,
                        token="USDC",
                        tx_hash=fill.get("txnHash", fill.get("tx_hash")),
                        order_id=trade_id,
                        side=side,
                        price=price,
                        fee=fee,
                        pnl=pnl,
                        market_ticker=market,
                        raw_data=fill,
                    )
                    await self._emit(event)
            except Exception as e:
                logger.warning("[ostium] Fills loop error: {e}")
            await asyncio.sleep(self._fills_interval)

    async def _positions_loop(self):
        """Poll positions for closed trade detection + balance delta for deposits/withdrawals."""
        last_balance = None
        while self._running:
            try:
                # Position diff detection
                current_positions = await self._client.get_positions(address=self.wallet_address)
                current_ids = {p.get("id", p.get("tradeId", "")): p for p in (current_positions or [])}
                last_ids = {p.get("id", p.get("tradeId", "")): p for p in self._last_positions}

                # Closed: in last but not current
                for tid, pos in last_ids.items():
                    if tid and tid not in current_ids:
                        await self._emit(ActivityEvent(
                            source="ostium",
                            event_type="trade_closed",
                            wallet_address=self.wallet_address,
                            platform="ostium",
                            amount=float(pos.get("collateral", pos.get("size", 0))),
                            token="USDC",
                            pnl=float(pos.get("pnl", 0)),
                            market_ticker=pos.get("pair", pos.get("market", "")),
                            raw_data=pos,
                        ))

                self._last_positions = current_positions or []

                # Balance delta
                balance_resp = await self._client.get_balance()
                current_balance = float(balance_resp.get("balance", balance_resp.get("value", 0)))
                if last_balance is not None:
                    result = self.detect_balance_delta(current_balance, last_balance)
                    if not result:
                        last_balance = current_balance
                        continue
                    await self._emit(ActivityEvent(
                        source="ostium",
                        event_type=result[0],
                        wallet_address=self.wallet_address,
                        platform="ostium",
                        amount=result[1],
                        token="USDC",
                    ))
                last_balance = current_balance

            except Exception as e:
                logger.warning("[ostium] Positions loop error: {e}")
            await asyncio.sleep(self._positions_interval)