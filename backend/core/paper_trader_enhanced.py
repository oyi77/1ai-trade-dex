"""Enhanced Paper Trader — paper trading with real order book simulation.

Extends basic paper trading with realistic order book depth simulation,
partial fills, slippage modeling, and latency simulation.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger


@dataclass
class SimulatedFill:
    """Result of simulating a fill against the order book."""
    price: float
    size: float
    slippage: float
    latency_ms: float
    partial: bool
    timestamp: float


@dataclass
class PaperPosition:
    """A paper trading position."""
    market_id: str
    direction: str  # "yes" or "no"
    entry_price: float
    size: float
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    opened_at: float = field(default_factory=time.time)
    fills: list[SimulatedFill] = field(default_factory=list)


@dataclass
class PaperTradeResult:
    """Result of a paper trade execution."""
    success: bool
    position: Optional[PaperPosition] = None
    fill: Optional[SimulatedFill] = None
    rejection_reason: Optional[str] = None
    order_value: float = 0.0
    fee: float = 0.0


class EnhancedPaperTrader:
    """Paper trader with real order book simulation.

    Simulates realistic execution against live order book data,
    including partial fills, slippage, latency, and platform fees.
    """

    def __init__(
        self,
        initial_bankroll: float = 100.0,
        platform_fee_pct: float = 0.01,
        simulated_latency_ms: float = 50.0,
        max_slippage_pct: float = 0.02,
    ):
        self.bankroll = initial_bankroll
        self.initial_bankroll = initial_bankroll
        self.platform_fee_pct = platform_fee_pct
        self.simulated_latency_ms = simulated_latency_ms
        self.max_slippage_pct = max_slippage_pct
        self.positions: dict[str, PaperPosition] = {}
        self.trade_history: list[PaperTradeResult] = []
        self._order_book: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_order_book(self, market_id: str, bids: list[dict], asks: list[dict]) -> None:
        """Update the simulated order book for a market."""
        self._order_book[market_id] = {
            "bids": sorted(bids, key=lambda x: float(x.get("price", 0)), reverse=True),
            "asks": sorted(asks, key=lambda x: float(x.get("price", 0))),
            "updated_at": time.time(),
        }

    def execute_trade(
        self,
        market_id: str,
        direction: str,
        size: float,
        limit_price: Optional[float] = None,
    ) -> PaperTradeResult:
        """Execute a paper trade against the simulated order book.

        Args:
            market_id: Market identifier.
            direction: "yes" or "no".
            size: Position size in dollars.
            limit_price: Optional limit price (None for market order).

        Returns:
            PaperTradeResult with fill details or rejection reason.
        """
        if size <= 0:
            return PaperTradeResult(success=False, rejection_reason="Size must be positive")

        if size > self.bankroll:
            return PaperTradeResult(
                success=False,
                rejection_reason=f"Insufficient bankroll: ${self.bankroll:.2f} < ${size:.2f}",
            )

        book = self._order_book.get(market_id)
        if not book or not book.get("asks") or not book.get("bids"):
            return PaperTradeResult(
                success=False,
                rejection_reason=f"No order book data for {market_id}",
            )

        # Simulate latency
        self._simulate_latency()

        # Simulate fill against order book
        fill = self._simulate_fill(market_id, direction, size, limit_price)
        if fill is None:
            return PaperTradeResult(
                success=False,
                rejection_reason="Could not fill order at acceptable price",
            )

        # Calculate fee
        fee = fill.price * fill.size * self.platform_fee_pct
        total_cost = fill.price * fill.size + fee

        if total_cost > self.bankroll:
            affordable_size = (self.bankroll / (fill.price * (1 + self.platform_fee_pct)))
            if affordable_size < 1.0:
                return PaperTradeResult(
                    success=False,
                    rejection_reason="Bankroll too small for minimum trade",
                )
            fill = SimulatedFill(
                price=fill.price,
                size=affordable_size,
                slippage=fill.slippage,
                latency_ms=fill.latency_ms,
                partial=True,
                timestamp=time.time(),
            )
            fee = fill.price * fill.size * self.platform_fee_pct
            total_cost = fill.price * fill.size + fee

        # Deduct from bankroll
        self.bankroll -= total_cost

        # Create or update position
        pos_key = f"{market_id}_{direction}"
        if pos_key in self.positions:
            pos = self.positions[pos_key]
            old_cost = pos.entry_price * pos.size
            new_cost = fill.price * fill.size
            pos.size += fill.size
            pos.entry_price = (old_cost + new_cost) / pos.size
            pos.fills.append(fill)
        else:
            pos = PaperPosition(
                market_id=market_id,
                direction=direction,
                entry_price=fill.price,
                size=fill.size,
                current_price=fill.price,
                fills=[fill],
            )
            self.positions[pos_key] = pos

        result = PaperTradeResult(
            success=True,
            position=pos,
            fill=fill,
            order_value=fill.price * fill.size,
            fee=fee,
        )
        self.trade_history.append(result)

        logger.info(
            f"Paper trade: {direction} {market_id} "
            f"${fill.size:.2f} @ {fill.price:.4f} "
            f"(slip={fill.slippage:.4f}, lat={fill.latency_ms:.0f}ms)"
        )
        return result

    def close_position(self, market_id: str, direction: str) -> PaperTradeResult:
        """Close a paper position at current order book price."""
        pos_key = f"{market_id}_{direction}"
        pos = self.positions.get(pos_key)
        if not pos:
            return PaperTradeResult(
                success=False,
                rejection_reason=f"No position for {pos_key}",
            )

        book = self._order_book.get(market_id)
        if not book:
            return PaperTradeResult(
                success=False,
                rejection_reason=f"No order book for {market_id}",
            )

        bids = book.get("bids", [])
        if not bids:
            return PaperTradeResult(
                success=False,
                rejection_reason="No bids to sell into",
            )

        exit_price = float(bids[0].get("price", 0))
        fee = exit_price * pos.size * self.platform_fee_pct
        proceeds = exit_price * pos.size - fee
        self.bankroll += proceeds

        pnl = (exit_price - pos.entry_price) * pos.size - fee
        pos.realized_pnl = pnl

        fill = SimulatedFill(
            price=exit_price,
            size=pos.size,
            slippage=abs(exit_price - pos.entry_price) / pos.entry_price if pos.entry_price > 0 else 0,
            latency_ms=self._simulate_latency(),
            partial=False,
            timestamp=time.time(),
        )

        del self.positions[pos_key]

        result = PaperTradeResult(
            success=True,
            position=pos,
            fill=fill,
            order_value=exit_price * pos.size,
            fee=fee,
        )
        self.trade_history.append(result)

        logger.info(
            f"Paper close: {direction} {market_id} "
            f"${pos.size:.2f} @ {exit_price:.4f} PnL=${pnl:.2f}"
        )
        return result

    def update_positions(self) -> None:
        """Update unrealized PnL for all open positions from current order book."""
        for _key, pos in self.positions.items():
            book = self._order_book.get(pos.market_id)
            if not book:
                continue
            bids = book.get("bids", [])
            asks = book.get("asks", [])
            if pos.direction == "yes" and bids:
                pos.current_price = float(bids[0].get("price", pos.entry_price))
            elif pos.direction == "no" and asks:
                pos.current_price = float(asks[0].get("price", pos.entry_price))
            pos.unrealized_pnl = (pos.current_price - pos.entry_price) * pos.size

    def get_portfolio_summary(self) -> dict:
        """Get current portfolio summary."""
        self.update_positions()
        total_unrealized = sum(p.unrealized_pnl for p in self.positions.values())
        total_realized = sum(p.realized_pnl for p in self.positions.values())
        total_exposure = sum(p.entry_price * p.size for p in self.positions.values())
        return {
            "bankroll": self.bankroll,
            "initial_bankroll": self.initial_bankroll,
            "total_pnl": self.bankroll - self.initial_bankroll + total_unrealized,
            "realized_pnl": total_realized,
            "unrealized_pnl": total_unrealized,
            "positions": len(self.positions),
            "total_exposure": total_exposure,
            "trades_executed": len(self.trade_history),
            "exposure_pct": total_exposure / self.bankroll * 100 if self.bankroll > 0 else 0,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _simulate_fill(
        self,
        market_id: str,
        direction: str,
        size: float,
        limit_price: Optional[float],
    ) -> Optional[SimulatedFill]:
        """Simulate filling an order against the order book."""
        book = self._order_book.get(market_id)
        if not book:
            return None

        if direction == "yes":
            levels = book.get("asks", [])
        else:
            levels = book.get("bids", [])

        if not levels:
            return None

        remaining = size
        total_cost = 0.0
        total_filled = 0.0
        float(levels[0].get("price", 0))

        for level in levels:
            price = float(level.get("price", 0))
            available = float(level.get("size", 0))

            if limit_price is not None:
                if direction == "yes" and price > limit_price:
                    break
                if direction == "no" and price < limit_price:
                    break

            fill_size = min(remaining, available)
            total_cost += price * fill_size
            total_filled += fill_size
            remaining -= fill_size

            if remaining <= 0:
                break

        if total_filled <= 0:
            return None

        avg_price = total_cost / total_filled
        best_price = float(levels[0].get("price", avg_price))
        slippage = abs(avg_price - best_price) / best_price if best_price > 0 else 0

        if slippage > self.max_slippage_pct:
            return None

        return SimulatedFill(
            price=avg_price,
            size=total_filled,
            slippage=slippage,
            latency_ms=self._simulate_latency(),
            partial=remaining > 0,
            timestamp=time.time(),
        )

    def _simulate_latency(self) -> float:
        """Simulate network latency with jitter."""
        jitter = random.gauss(0, self.simulated_latency_ms * 0.2)
        return max(1.0, self.simulated_latency_ms + jitter)
