"""SX.bet activity source — REST polling for fills and balance changes."""

from __future__ import annotations
import asyncio

from backend.core.activity.models import ActivityEvent
from backend.core.activity.sources.base import BaseActivitySource
from loguru import logger


class SXBetActivitySource(BaseActivitySource):
    """Poll SX.bet REST API for trade fills and balance changes."""

    def __init__(self, wallet_address: str, sxbet_client=None):
        super().__init__(wallet_address, "sxbet")
        self._client = sxbet_client
        self._seen_orders: set[str] = set()
        self._fills_interval = 10
        self._balance_interval = 15

    async def _run(self):
        if not self._client:
            logger.warning("[sxbet] No client provided, skipping activity source")
            return
        try:
            self.create_subtask(self._fills_loop())
            self.create_subtask(self._balance_loop())
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("[sxbet] Activity source error: {e}")

    async def _fills_loop(self):
        """Poll SX.bet trades endpoint for recent fills."""
        while self._running:
            try:
                fills = await self._client.get_fills(wallet_address=self.wallet_address, limit=100)
                for fill in fills:
                    order_id = fill.get("orderHash", fill.get("id", ""))
                    if order_id in self._seen_orders:
                        continue
                    self._seen_orders.add(order_id)

                    side = fill.get("side", fill.get("outcomeIndex", "")).lower()
                    amount = float(fill.get("stakeAmount", fill.get("fillAmount", 0)))
                    # SX.bet stakeAmount is in wei (6 decimals for USDC)
                    if amount > 1e6:
                        amount = amount / 1e6
                    price = float(fill.get("odds", fill.get("price", 0)))
                    fee = float(fill.get("fee", fill.get("bpFee", 0)))
                    market = fill.get("marketHash", fill.get("market", ""))
                    status = fill.get("status", "").lower()
                    is_open = status not in ("settled", "closed", "resolved")

                    event = ActivityEvent(
                        source="sxbet",
                        event_type="trade_open" if is_open else "trade_closed",
                        wallet_address=self.wallet_address,
                        platform="sxbet",
                        amount=amount,
                        token="USDC",
                        order_id=order_id,
                        side=side,
                        price=price,
                        fee=fee,
                        market_ticker=market,
                        raw_data=fill,
                    )
                    await self._emit(event)
            except Exception as e:
                logger.warning("[sxbet] Fills loop error: {e}")
            await asyncio.sleep(self._fills_interval)

    async def _balance_loop(self):
        """Poll balance for deposit/withdrawal detection."""
        last_balance = None
        while self._running:
            try:
                balance_resp = await self._client.get_balance(wallet_address=self.wallet_address)
                current_balance = float(balance_resp.get("balance", balance_resp.get("value", 0)))
                # SX.bet balance might be in wei
                if current_balance > 1e6:
                    current_balance = current_balance / 1e6

                if last_balance is not None:
                    result = self.detect_balance_delta(current_balance, last_balance)
                    if not result:
                        last_balance = current_balance
                        continue
                    await self._emit(ActivityEvent(
                        source="sxbet",
                        event_type=result[0],
                        wallet_address=self.wallet_address,
                        platform="sxbet",
                        amount=result[1],
                        token="USDC",
                    ))
                last_balance = current_balance
            except Exception as e:
                logger.warning("[sxbet] Balance loop error: {e}")
            await asyncio.sleep(self._balance_interval)