"""OrderbookSignalGenerator — orderbook imbalance signals.

Detects orderbook imbalance: when bid/ask depth is heavily skewed,
it signals directional pressure before the price moves.
"""

from __future__ import annotations

from typing import Any


from backend.strategies.signal_generators.base import Signal, SignalGenerator


class OrderbookSignalGenerator(SignalGenerator):
    """Generates signals from orderbook imbalance.

    Expects each market dict to contain:
        - 'ticker': str
        - 'bids': list of {'price': float, 'size': float} (sorted high to low)
        - 'asks': list of {'price': float, 'size': float} (sorted low to high)
        - 'yes_price': float (current yes price)
    """

    @property
    def name(self) -> str:
        return "orderbook"

    @property
    def description(self) -> str:
        return (
            "Orderbook imbalance signals. Detects when bid/ask depth is "
            "heavily skewed, indicating directional pressure."
        )

    async def generate(
        self,
        markets: list[dict[str, Any]],
        params: dict[str, Any] | None = None,
    ) -> list[Signal]:
        params = params or {}
        signals: list[Signal] = []
        min_imbalance = params.get("min_orderbook_imbalance", 0.3)

        for market in markets:
            ticker = market.get("ticker", "")
            bids = market.get("bids", [])
            asks = market.get("asks", [])

            if not bids or not asks:
                continue

            # Aggregate depth within configurable range (default: top 5 levels)
            depth_levels = params.get("depth_levels", 5)
            bid_depth = sum(b.get("size", 0.0) for b in bids[:depth_levels])
            ask_depth = sum(a.get("size", 0.0) for a in asks[:depth_levels])
            total_depth = bid_depth + ask_depth

            if total_depth == 0:
                continue

            # Imbalance ratio: +1 = all bids, -1 = all asks
            imbalance = (bid_depth - ask_depth) / total_depth

            if abs(imbalance) < min_imbalance:
                continue

            # Spread info
            best_bid = bids[0].get("price", 0.0)
            best_ask = asks[0].get("price", 1.0)
            spread = best_ask - best_bid

            signals.append(
                Signal(
                    signal_type="orderbook_imbalance",
                    strength=imbalance,  # -1 to +1
                    confidence=min(1.0, abs(imbalance)),
                    market_ticker=ticker,
                    data={
                        "bid_depth": bid_depth,
                        "ask_depth": ask_depth,
                        "imbalance": imbalance,
                        "best_bid": best_bid,
                        "best_ask": best_ask,
                        "spread": spread,
                    },
                    reasoning=(
                        f"Orderbook imbalance: {imbalance:+.3f} "
                        f"(bid_depth={bid_depth:.1f}, ask_depth={ask_depth:.1f}, "
                        f"spread={spread:.4f})"
                    ),
                )
            )

        return signals
