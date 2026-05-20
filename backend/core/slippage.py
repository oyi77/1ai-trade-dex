"""
Slippage calculator for Polymarket CLOB order books.

Walks the order book to estimate execution price (VWAP) and slippage
for a given order side and size.
"""

from dataclasses import dataclass

from backend.data.orderbook_ws import LiveOrderBook


@dataclass
class SlippageEstimate:
    execution_price: float  # VWAP across filled levels
    slippage: float  # execution_price - mid_price (as fraction of mid)
    filled_amount: float  # total size actually filled
    fully_filled: bool
    levels_consumed: int


def calculate_slippage(book: LiveOrderBook, side: str, size: float) -> SlippageEstimate:
    """
    Walk the order book to estimate execution price and slippage.

    Args:
        book: The live order book to walk.
        side: "BUY" or "SELL". BUY walks asks; SELL walks bids.
        size: Desired fill size (in units matching the book).

    Returns:
        SlippageEstimate with VWAP, slippage fraction, and fill details.
    """
    side_upper = side.upper()
    if side_upper == "BUY":
        levels = book.asks  # sorted asc: best ask first
    else:
        levels = book.bids  # sorted desc: best bid first

    mid = book.mid_price
    remaining = size
    total_cost = 0.0
    total_filled = 0.0
    levels_consumed = 0

    for price, level_size in levels:
        if remaining <= 0:
            break
        fill = min(remaining, level_size)
        total_cost += fill * price
        total_filled += fill
        remaining -= fill
        levels_consumed += 1

    if total_filled == 0:
        return SlippageEstimate(
            execution_price=mid,
            slippage=0.0,
            filled_amount=0.0,
            fully_filled=False,
            levels_consumed=0,
        )

    execution_price = total_cost / total_filled
    slippage = abs(execution_price - mid) / mid if mid > 0 else 0.0

    return SlippageEstimate(
        execution_price=execution_price,
        slippage=slippage,
        filled_amount=total_filled,
        fully_filled=(remaining <= 0),
        levels_consumed=levels_consumed,
    )
