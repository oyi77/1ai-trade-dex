"""Polymarket activity source — WebSocket fills + REST fallback + Polygon on-chain transfers."""

from __future__ import annotations
import asyncio

from backend.core.activity.models import ActivityEvent
from backend.core.activity.sources.base import BaseActivitySource
from backend.constants import USDC_E_ADDRESS, ERC20_TRANSFER_TOPIC, BALANCE_DELTA_THRESHOLD
from loguru import logger


class PolymarketActivitySource(BaseActivitySource):
    """Real-time activity from Polymarket CLOB (WebSocket + REST fallback) + Polygon on-chain."""

    def __init__(self, wallet_address: str, clob_client, web3_client=None):
        super().__init__(wallet_address, "polymarket")
        self._clob = clob_client
        self._w3 = web3_client
        self._seen_orders: set[str] = set()
        self._last_transfer_block: int = 0
        self._ws_connected = False

    async def _run(self):
        try:
            # Enter the CLOB HTTP context so _http is initialised
            async with self._clob:
                # Try WS first, fall back to REST polling
                self.create_subtask(self._ws_fills_loop())
                # Polygon transfer events (deposits/withdrawals)
                if self._w3:
                    self.create_subtask(self._transfer_loop())
                else:
                    self.create_subtask(self._clob_balance_loop())

                while self._running:
                    await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[polymarket] Activity source error: {e}")

    async def _ws_fills_loop(self):
        """Try WebSocket fills subscription; fall back to REST polling on failure."""
        while self._running:
            try:
                await self._connect_ws_fills()
            except Exception as e:
                logger.warning(f"[polymarket] WS fills error, falling back to REST: {e}")
                self._ws_connected = False
            # If WS fails, run REST fallback for a while before retrying
            if not self._ws_connected and self._running:
                await self._rest_fills_loop(timeout=60)

    async def _connect_ws_fills(self):
        """Connect to Polymarket WebSocket USER channel for real-time fills."""
        from backend.data.polymarket_websocket import PolymarketWebSocket, ChannelType, EventType
        from backend.config import settings

        ws_url = settings.POLYMARKET_WS_USER_URL
        if not ws_url:
            logger.warning("[polymarket] No WS_USER_URL configured, using REST fills")
            return

        ws = PolymarketWebSocket(ws_config={"url": ws_url, "channel": ChannelType.USER})

        def on_user_trade(data: dict):
            """Callback for WS trade fill events."""
            try:
                order_id = data.get("orderID", data.get("id", ""))
                if not order_id or order_id in self._seen_orders:
                    return
                self._seen_orders.add(order_id)

                side = data.get("side", "").lower()
                amount = float(data.get("size", data.get("amount", 0)))
                price = float(data.get("price", 0))
                fee = float(data.get("fee", 0))
                market_ticker = data.get("market", data.get("asset_id", ""))

                event = ActivityEvent(
                    source="polymarket",
                    event_type="trade_open",
                    wallet_address=self.wallet_address,
                    platform="polymarket",
                    amount=amount,
                    token="USDC",
                    order_id=order_id,
                    side=side,
                    price=price,
                    fee=fee,
                    market_ticker=market_ticker,
                    raw_data=data,
                )
                # Schedule emit in the running event loop (safe pattern)
                try:
                    asyncio.get_running_loop().create_task(self._emit(event))
                except RuntimeError:
                    asyncio.ensure_future(self._emit(event))
            except Exception as e:
                logger.warning(f"[polymarket] WS trade callback error: {e}")

        def on_user_order(data: dict):
            """Callback for WS order status updates (fills, cancellations)."""
            try:
                status = data.get("status", "").lower()
                if status in ("matched", "filled", "live_matched"):
                    on_user_trade(data)
            except Exception as e:
                logger.warning(f"[polymarket] WS order callback error: {e}")

        ws.on(EventType.USER_TRADE, on_user_trade)
        ws.on(EventType.USER_ORDER, on_user_order)

        await ws.connect()
        self._ws_connected = True
        logger.info("[polymarket] WS fills connected")

        # Keep connection alive until disconnected or cancelled
        while self._running and ws.is_connected():
            await asyncio.sleep(1)

        self._ws_connected = False
        logger.warning("[polymarket] WS fills disconnected, will retry")

    async def _rest_fills_loop(self, timeout: int = 60):
        """REST fallback: poll CLOB /fills endpoint. Runs for `timeout` seconds."""
        deadline = asyncio.get_running_loop().time() + timeout
        while self._running and asyncio.get_running_loop().time() < deadline:
            try:
                fills = await self._clob.get_trader_trades(self.wallet_address)
                raw = fills if isinstance(fills, list) else (fills or {}).get("data", [])
                for fill in (raw or []):
                    if not fill or not isinstance(fill, dict):
                        continue
                    order_id = fill.get("orderID", fill.get("id", ""))
                    if order_id in self._seen_orders:
                        continue
                    self._seen_orders.add(order_id)

                    event = ActivityEvent(
                        source="polymarket",
                        event_type="trade_open",
                        wallet_address=self.wallet_address,
                        platform="polymarket",
                        amount=float(fill.get("size", fill.get("amount", 0)) or 0),
                        token="USDC",
                        order_id=order_id,
                        side=(fill.get("side") or "").lower(),
                        price=float(fill.get("price", 0) or 0),
                        fee=float(fill.get("fee", 0) or 0),
                        raw_data=fill,
                    )
                    await self._emit(event)
            except Exception as e:
                logger.warning(f"[polymarket] REST fills loop error: {e}")
            await asyncio.sleep(5)

    async def _transfer_loop(self):
        """Poll Polygon Transfer events for deposit/withdrawal."""
        USDC_CONTRACT = USDC_E_ADDRESS
        TRANSFER_TOPIC = ERC20_TRANSFER_TOPIC
        WALLET_LOWER = self.wallet_address.lower()

        last_block = self._last_transfer_block or await self._w3.eth.block_number
        while self._running:
            try:
                current = await self._w3.eth.block_number
                logs = await self._w3.eth.get_logs({
                    "address": USDC_CONTRACT,
                    "topics": [TRANSFER_TOPIC],
                    "fromBlock": last_block,
                    "toBlock": current,
                })
                for log in logs:
                    tx_hash = log.transactionHash.hex()
                    if tx_hash in self._seen_orders:
                        continue
                    self._seen_orders.add(tx_hash)

                    to_addr = log.topics[2].hex()[-40:].lower()
                    from_addr = log.topics[1].hex()[-40:].lower()
                    is_deposit = (to_addr == WALLET_LOWER)
                    event_type = "deposit" if is_deposit else "withdrawal"
                    amount = abs(int(log.data, 16)) / 1e6

                    if amount < BALANCE_DELTA_THRESHOLD:
                        continue

                    event = ActivityEvent(
                        source="polymarket",
                        event_type=event_type,
                        wallet_address=self.wallet_address,
                        platform="polymarket",
                        amount=amount,
                        token="USDC",
                        tx_hash=tx_hash,
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
                bal = await self._clob.get_wallet_balance()
                balance = float(bal.get("usdc_balance", 0))
                if last is not None:
                    result = self.detect_balance_delta(balance, last)
                    if result:
                        event_type, amount = result
                        await self._emit(ActivityEvent(
                            source="polymarket",
                            event_type=event_type,
                            wallet_address=self.wallet_address,
                            platform="polymarket",
                            amount=amount,
                            token="USDC",
                        ))
                last = balance
            except Exception as e:
                logger.warning(f"[polymarket] Balance loop error: {e}")
            await asyncio.sleep(10)