"""Binance WebSocket feed for real-time crypto klines. Replaces REST polling."""

import asyncio
import json
import logging
from typing import Callable, Optional

import websockets

logger = logging.getLogger(__name__)

BINANCE_WS_URL = "wss://stream.binance.com:9443/ws"

# Shared state: latest klines per symbol
_latest_klines: dict[str, dict] = {}
_subscribers: dict[str, list[Callable]] = {}


async def _connect_binance_ws(symbols: list[str], intervals: list[str] = None):
    """Connect to Binance WebSocket and stream kline data."""
    if intervals is None:
        intervals = ["1m"]

    # Build stream names: btcusdt@kline_1m, ethusdt@kline_1m, etc.
    streams = []
    for sym in symbols:
        for interval in intervals:
            streams.append(f"{sym.lower()}@kline_{interval}")

    url = f"{BINANCE_WS_URL}/{'/'.join(streams)}"

    while True:
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                logger.info(
                    f"[crypto_ws] Connected to Binance WS: {len(streams)} streams"
                )
                async for msg in ws:
                    try:
                        data = json.loads(msg)
                        if "k" in data:
                            kline = data["k"]
                            symbol = kline["s"].upper()
                            interval = kline["i"]

                            _latest_klines[symbol] = {
                                "open": float(kline["o"]),
                                "high": float(kline["h"]),
                                "low": float(kline["l"]),
                                "close": float(kline["c"]),
                                "volume": float(kline["v"]),
                                "timestamp": kline["t"],
                                "is_closed": kline["x"],
                                "interval": interval,
                                "source": "binance_ws",
                            }

                            # Notify subscribers
                            for callback in _subscribers.get(symbol, []):
                                try:
                                    await callback(_latest_klines[symbol])
                                except Exception as e:
                                    logger.warning(
                                        f"[crypto_ws] Subscriber error for {symbol}: {e}"
                                    )

                    except json.JSONDecodeError:
                        continue
                    except Exception as e:
                        logger.warning(f"[crypto_ws] Message parse error: {e}")

        except websockets.exceptions.ConnectionClosed:
            logger.warning("[crypto_ws] Connection closed, reconnecting in 5s...")
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"[crypto_ws] Connection error: {e}, reconnecting in 10s...")
            await asyncio.sleep(10)


def get_latest_kline(symbol: str) -> Optional[dict]:
    """Get the latest kline data for a symbol. Returns None if not available."""
    return _latest_klines.get(symbol.upper())


def subscribe_kline(symbol: str, callback: Callable):
    """Subscribe to kline updates for a symbol."""
    sym = symbol.upper()
    if sym not in _subscribers:
        _subscribers[sym] = []
    _subscribers[sym].append(callback)


async def start_crypto_ws_feed(symbols: list[str] = None, intervals: list[str] = None):
    """Start the Binance WebSocket feed. Call once at startup."""
    if symbols is None:
        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    if intervals is None:
        intervals = ["1m"]

    asyncio.create_task(_connect_binance_ws(symbols, intervals))
    logger.info(f"[crypto_ws] Started Binance WS feed for {symbols}")
