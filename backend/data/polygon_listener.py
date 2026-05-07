"""Polygon blockchain WebSocket listener for Polymarket whale trades."""
import asyncio
import json
import logging
from typing import Optional, Callable, Awaitable
from datetime import datetime, timezone

from backend.config import settings
from backend.models.database import SessionLocal, WhaleTransaction

logger = logging.getLogger("trading_bot.polygon_listener")


class PolygonListener:
    def __init__(self, ws_url: Optional[str] = None, contract: Optional[str] = None,
                 min_usd: Optional[float] = None,
                 on_whale: Optional[Callable[[dict], Awaitable[None]]] = None):
        self.ws_url = ws_url or settings.POLYGON_WS_URL
        self.contract = (contract or settings.CONDITIONAL_TOKENS_ADDRESS).lower()
        self.min_usd = min_usd if min_usd is not None else settings.MIN_WHALE_TRADE_USD
        self.on_whale = on_whale
        self._running = False
        self._ws = None

    async def start(self) -> None:
        import websockets
        self._running = True
        MAX_RETRIES = 10
        INITIAL_DELAY = 1.0
        BACKOFF_MULTIPLIER = 2.0
        MAX_DELAY = 60.0
        while self._running:
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    async with websockets.connect(self.ws_url) as ws:
                        self._ws = ws
                        sub = {
                            "jsonrpc": "2.0", "id": 1, "method": "eth_subscribe",
                            "params": ["logs", {"address": self.contract}],
                        }
                        await ws.send(json.dumps(sub))
                        async for msg in ws:
                            await self._handle_message(msg)
                    break
                except Exception as e:
                    if not self._running:
                        break
                    delay = min(INITIAL_DELAY * (BACKOFF_MULTIPLIER ** (attempt-1)), MAX_DELAY)
                    logger.warning(
                        "polygon ws error (attempt %d/%d), reconnecting in %.0fs: %s",
                        attempt, MAX_RETRIES, delay, e
                    )
                    await asyncio.sleep(delay)
            else:
                logger.critical(
                    "Polygon ws repeated failure after %d attempts; giving up until manual restart.",
                    MAX_RETRIES
                )
                raise

    async def _handle_message(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
            params = msg.get("params", {})
            result = params.get("result", {}) if isinstance(params, dict) else {}
            if not isinstance(result, dict):
                return
            tx_hash = result.get("transactionHash")
            block = int(result.get("blockNumber", "0x0"), 16) if result.get("blockNumber") else None
            topics = result.get("topics", [])
            size_usd = self._estimate_usd(result.get("data", "0x0"))
            if size_usd < self.min_usd:
                return
            wallet = self._extract_wallet(topics)
            position_id = self._extract_position(topics)
            await self._persist(tx_hash, wallet, position_id, size_usd, block)
            payload = {
                "tx_hash": tx_hash, "wallet": wallet,
                "market_id": position_id, "size_usd": size_usd, "block": block,
            }
            if self.on_whale:
                await self.on_whale(payload)
            # Broadcast to /ws/whales subscribers
            try:
                from backend.api.ws_manager import broadcast_whale_tick
                await broadcast_whale_tick(payload)
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"polygon msg parse failed: {e}")

    def _estimate_usd(self, data_hex: str) -> float:
        try:
            raw = int(data_hex, 16) if data_hex else 0
            return raw / 1e6  # USDC has 6 decimals
        except Exception:
            return 0.0

    def _extract_wallet(self, topics: list) -> Optional[str]:
        if len(topics) >= 2:
            return "0x" + topics[1][-40:]
        return None

    def _extract_position(self, topics: list) -> Optional[str]:
        if len(topics) >= 4:
            return topics[3]
        return None

    async def _persist(self, tx_hash, wallet, position_id, size_usd, block) -> None:
        def _save():
            db = SessionLocal()
            try:
                existing = db.query(WhaleTransaction).filter(WhaleTransaction.tx_hash == tx_hash).first()
                if existing:
                    return
                row = WhaleTransaction(
                    tx_hash=tx_hash or f"unknown_{datetime.now(timezone.utc).timestamp()}",
                    wallet=wallet or "unknown",
                    market_id=position_id, side="buy",
                    size_usd=size_usd, block_number=block,
                )
                db.add(row)
                db.commit()
            finally:
                db.close()
        await asyncio.get_event_loop().run_in_executor(None, _save)

    def stop(self) -> None:
        self._running = False
