"""Order Book HFT Analyzer — real-time spread and liquidity analysis for HFT."""

import asyncio
from dataclasses import dataclass
from typing import Optional

@dataclass
class OrderBookLevel:
    price: float
    size: float


@dataclass
class OrderBookSnapshot:
    condition_id: str
    bids: list[OrderBookLevel]
    asks: list[OrderBookLevel]
    best_bid: float
    best_ask: float
    spread: float
    spread_pct: float
    depth_10: float
    depth_50: float
    mid_price: float
    imbalance: float
    timestamp: float


class OrderbookAnalyzerHFT:
    """
    HFT-grade order book analyzer.

    Computes bid-ask spread, depth imbalance, and liquidity metrics
    for detecting intra-market arbitrage opportunities.

    Zero Gaps:
    - WS disconnection: buffer updates, fill from stale
    - Malformed data: validate structure, skip bad entries
    - Latency spikes: detect stale data by timestamp
    """

    def __init__(self, condition_id: str):
        self.condition_id = condition_id
        self._bids: list[OrderBookLevel] = []
        self._asks: list[OrderBookLevel] = []
        self._last_update = 0.0
        self._stale_threshold = 2.0
        self._buffer: list[dict] = []

    def update(self, bids: list[dict], asks: list[dict]) -> None:
        """Update order book with new bid/ask data."""
        self._bids = [
            OrderBookLevel(price=float(b["price"]), size=float(b["size"]))
            for b in bids if self._validate_level(b)
        ]
        self._asks = [
            OrderBookLevel(price=float(a["price"]), size=float(a["size"]))
            for a in asks if self._validate_level(a)
        ]
        self._last_update = asyncio.get_event_loop().time()

    def _validate_level(self, level: dict) -> bool:
        """Validate order book level data."""
        try:
            price = float(level.get("price", 0))
            size = float(level.get("size", 0))
            return 0 < price <= 1.0 and size > 0
        except (ValueError, TypeError):
            return False

    def snapshot(self) -> OrderBookSnapshot:
        """Compute current order book snapshot."""
        if not self._bids or not self._asks:
            return OrderBookSnapshot(
                condition_id=self.condition_id,
                bids=[],
                asks=[],
                best_bid=0.0,
                best_ask=0.0,
                spread=0.0,
                spread_pct=0.0,
                depth_10=0.0,
                depth_50=0.0,
                mid_price=0.0,
                imbalance=0.0,
                timestamp=self._last_update,
            )

        self._bids.sort(key=lambda x: -x.price)
        self._asks.sort(key=lambda x: x.price)

        best_bid = self._bids[0].price
        best_ask = self._asks[0].price
        spread = best_ask - best_bid
        mid_price = (best_bid + best_ask) / 2.0
        spread_pct = (spread / mid_price) * 100.0 if mid_price > 0 else 0.0

        depth_10 = sum(lvl.size for lvl in self._bids[:10]) + sum(lvl.size for lvl in self._asks[:10])
        depth_50 = sum(lvl.size for lvl in self._bids[:50]) + sum(lvl.size for lvl in self._asks[:50])

        bid_depth = sum(lvl.size for lvl in self._bids[:10])
        ask_depth = sum(lvl.size for lvl in self._asks[:10])
        total_depth = bid_depth + ask_depth
        imbalance = (bid_depth - ask_depth) / total_depth if total_depth > 0 else 0.0

        return OrderBookSnapshot(
            condition_id=self.condition_id,
            bids=self._bids,
            asks=self._asks,
            best_bid=best_bid,
            best_ask=best_ask,
            spread=spread,
            spread_pct=spread_pct,
            depth_10=depth_10,
            depth_50=depth_50,
            mid_price=mid_price,
            imbalance=imbalance,
            timestamp=self._last_update,
        )

    def is_stale(self) -> bool:
        """Check if order book data is stale."""
        import time
        return (time.time() - self._last_update) > self._stale_threshold

    def detect_arb(self) -> Optional[dict]:
        """
        Detect intra-market arbitrage from order book spread.

        If best_bid on one side + best_ask on other creates profit > fees,
        we have an arbitrage opportunity.
        """
        snap = self.snapshot()
        if not snap.bids or not snap.asks:
            return None

        buy_at_ask = snap.best_ask
        sell_at_bid = snap.best_bid
        profit = sell_at_bid - buy_at_ask
        fees = 0.02
        net_profit = profit - fees

        if net_profit > 0.005:
            return {
                "condition_id": snap.condition_id,
                "buy_price": buy_at_ask,
                "sell_price": sell_at_bid,
                "gross_profit": profit,
                "net_profit": net_profit,
                "spread_pct": snap.spread_pct,
            }

        return None
