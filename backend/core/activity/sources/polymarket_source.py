"""Polymarket activity source — CLOB fills (REST) + Polygon on-chain transfers."""

from __future__ import annotations
import asyncio

from backend.core.activity.models import ActivityEvent
from backend.core.activity.sources.base import BaseActivitySource
from loguru import logger


class PolymarketActivitySource(BaseActivitySource):
    """Real-time activity from Polymarket CLOB (REST polling) + Polygon on-chain."""

    def __init__(self, wallet_address: str, clob_client, web3_client=None):
        super().__init__(wallet_address, "polymarket")
        self._clob = clob_client
        self._w3 = web3_client
        self._seen_orders: set[str] = set()
        self._last_transfer_block: int = 0

    async def _run(self):
        try:
            # CLOB fills polling
            asyncio.create_task(self._fills_loop())
            # Polygon transfer events (deposits/withdrawals)
            if self._w3:
                asyncio.create_task(self._transfer_loop())
            else:
                asyncio.create_task(self._clob_balance_loop())

            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[polymarket] Activity source error: {e}")

    async def _fills_loop(self):
        """Poll CLOB /fills endpoint every 5s."""
        while self._running:
            try:
                fills = await self._clob.get_fills(self.wallet_address)
                for fill in fills:
                    order_id = fill.get("orderID", fill.get("id", ""))
                    if order_id in self._seen_orders:
                        continue
                    self._seen_orders.add(order_id)

                    event = ActivityEvent(
                        source="polymarket",
                        event_type="trade_open",
                        wallet_address=self.wallet_address,
                        platform="polymarket",
                        amount=float(fill.get("size", fill.get("amount", 0))),
                        token="USDC",
                        order_id=order_id,
                        side=fill.get("side", "").lower(),
                        price=float(fill.get("price", 0)),
                        fee=float(fill.get("fee", 0)),
                        raw_data=fill,
                    )
                    await self._emit(event)
            except Exception as e:
                logger.warning(f"[polymarket] Fills loop error: {e}")
            await asyncio.sleep(5)

    async def _transfer_loop(self):
        """Poll Polygon Transfer events for deposit/withdrawal."""
        USDC_CONTRACT = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
        TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952cb7f3a755fcd14e56f2e2f31e32f"

        last_block = self._last_transfer_block or await self._w3.eth.block_number
        while self._running:
            try:
                current = await self._w3.eth.block_number
                logs = await self._w3.eth.get_logs({
                    "address": USDC_CONTRACT,
                    "topics": [TRANSFER_TOPIC],
                    "fromBlock": last_block,
                    "toBlock": current,
                    "arguments": {"to": self.wallet_address},
                })
                for log in logs:
                    if log.transactionHash.hex() in self._seen_orders:
                        continue
                    self._seen_orders.add(log.transactionHash.hex())

                    event = ActivityEvent(
                        source="polymarket",
                        event_type="deposit",
                        wallet_address=self.wallet_address,
                        platform="polymarket",
                        amount=float(log.data) / 1e6,  # USDC 6 decimals
                        token="USDC",
                        tx_hash=log.transactionHash.hex(),
                        raw_data={"blockNumber": log.blockNumber, "log": str(log)},
                    )
                    await self._emit(event)
                last_block = current + 1
            except Exception as e:
                logger.warning(f"[polymarket] Transfer loop error: {e}")
            await asyncio.sleep(3)

    async def _clob_balance_loop(self):
        """Fallback: poll CLOB balance endpoint for changes."""
        last = None
        while self._running:
            try:
                bal = await self._clob.get_balance(self.wallet_address)
                if last is not None and abs(float(bal) - float(last)) > 0.01:
                    delta = float(bal) - float(last)
                    await self._emit(ActivityEvent(
                        source="polymarket",
                        event_type="deposit" if delta > 0 else "withdrawal",
                        wallet_address=self.wallet_address,
                        platform="polymarket",
                        amount=abs(delta),
                        token="USDC",
                    ))
                last = bal
            except Exception as e:
                logger.warning(f"[polymarket] Balance loop error: {e}")
            await asyncio.sleep(10)