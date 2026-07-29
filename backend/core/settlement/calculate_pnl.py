"""
PnL calculation math for trade settlement.

Extracted from settlement_helpers.py.
"""

from typing import Optional

from backend.models.database import Trade

from loguru import logger


def total_loss_settlement_value(direction: Optional[str]) -> float:
    """settlement_value that makes a position with this direction worthless.

    Used when force-closing a trade as result="loss" without a real market
    resolution: the chosen value must make calculate_pnl() return
    -cost_basis (a real loss) rather than a win payout, for either side of
    the bet. yes/up/buy positions are worthless when settlement_value=0.0;
    no/down/sell positions are worthless when settlement_value=1.0.
    """
    normalized = (direction or "yes").strip().lower()
    return 1.0 if normalized in ("no", "down", "sell") else 0.0


def calculate_pnl(trade: Trade, settlement_value: float) -> float:
    """
    Calculate P&L for a trade given the settlement value.

    settlement_value: 1.0 if Up/Yes outcome, 0.0 if Down/No outcome

    Maps up->yes, down->no internally:
    - UP position wins when settlement = 1.0
    - DOWN position wins when settlement = 0.0

    IMPORTANT: The execution pipeline stores `size` as SHARES (number of contracts),
    NOT dollars. `entry_price` is the cost per share (0.0-1.0).
    On a win, each share pays $1: net profit = (1.0 - entry_price) * shares.
    On a loss, shares are worth $0: net loss = -(entry_price * shares).
    """
    # Normalize direction — binary venues use YES/NO semantics even when
    # strategies call them UP/DOWN. Keep this venue-neutral for Polymarket,
    # Kalshi, SX.bet-style contracts, etc.
    direction = (trade.direction or "yes").strip().lower()
    if direction in ("up", "buy"):
        direction = "yes"
    elif direction in ("down", "sell"):
        direction = "no"

    _fill_price = getattr(trade, "fill_price", None)
    entry_price = (
        float(_fill_price)
        if isinstance(_fill_price, (int, float))
        else float(trade.entry_price or 0.0)
    )

    # `Trade.size` is SHARES (number of contracts), NOT dollars.
    # `Trade.filled_size`, when present, is the actual filled shares (should equal size).
    shares = float(trade.size or 0.0)
    _filled = getattr(trade, "filled_size", None)
    _filled = getattr(trade, "filled_size", None)
    has_filled_shares = isinstance(_filled, (int, float)) and float(_filled) > 0
    if has_filled_shares:
        shares = float(_filled)

    # Notional USD value of the position
    notional = shares * entry_price if 0 < entry_price < 1.0 else 0.0

    # Fee calculation (taker fee on notional)
    stored_fee = getattr(trade, "fee", None)
    if isinstance(stored_fee, (int, float)):
        fee = float(stored_fee)
    else:
        from backend.fee_config import TAKER_FEE_BPS

        uncertainty = (
            min(entry_price, 1.0 - entry_price) if 0 < entry_price < 1.0 else 0.0
        )
        fee = (TAKER_FEE_BPS / 10000.0) * uncertainty * (shares * entry_price) if 0 < entry_price < 1.0 else 0.0

    # Dollar cost = notional + fee
    dollar_cost = shares * entry_price + fee if 0 < entry_price < 1.0 else 0.0

    if not entry_price or entry_price <= 0 or entry_price >= 1.0:
        if entry_price and entry_price >= 1.0:
            if direction == "yes":
                return 0.0 if settlement_value == 1.0 else round(-dollar_cost, 2)
            else:
                return 0.0 if settlement_value == 0.0 else round(-dollar_cost, 2)
        if direction == "yes":
            return round(dollar_cost if settlement_value == 1.0 else -dollar_cost, 2)
        else:
            return round(dollar_cost if settlement_value == 0.0 else -dollar_cost, 2)

    if direction == "yes":
        if settlement_value == 1.0:
            pnl = shares * (1.0 - entry_price) - fee
        else:
            pnl = -shares * entry_price - fee
    else:
        if settlement_value == 0.0:
            pnl = shares * (1.0 - entry_price) - fee
        else:
            pnl = -shares * entry_price - fee

    return round(pnl, 2)


def calculate_exit_pnl(trade: Trade, exit_price: float) -> tuple[float, float]:
    """Calculate realized P&L for closing `trade` early at `exit_price`.

    `exit_price` is the current price of `trade.token_id` — APEX edge
    scanners record `entry_price` as the price of the held token at entry
    (see backend/core/edge/scanners/*), so both prices are in the same
    "held-token" terms and the P&L is direction-independent:

        pnl = shares * (exit_price - entry_price) - entry_fee - exit_fee

    Unlike binary settlement (`calculate_pnl`), an early exit requires a
    real CLOB sell order, so a second taker fee is charged on the exit leg.

    Returns (pnl, total_fee), both rounded to 2 decimals.
    """
    _fill_price = getattr(trade, "fill_price", None)
    entry_price = (
        float(_fill_price)
        if isinstance(_fill_price, (int, float))
        else float(trade.entry_price or 0.0)
    )

    shares = float(trade.size or 0.0)
    _filled = getattr(trade, "filled_size", None)
    if isinstance(_filled, (int, float)) and float(_filled) > 0:
        shares = float(_filled)

    exit_price = max(0.0, min(1.0, float(exit_price)))

    from backend.fee_config import TAKER_FEE_BPS

    stored_fee = getattr(trade, "fee", None)
    if isinstance(stored_fee, (int, float)):
        entry_fee = float(stored_fee)
    else:
        entry_uncertainty = (
            min(entry_price, 1.0 - entry_price) if 0 < entry_price < 1.0 else 0.0
        )
        entry_fee = (TAKER_FEE_BPS / 10000.0) * entry_uncertainty * (shares * entry_price)

    exit_uncertainty = min(exit_price, 1.0 - exit_price) if 0 < exit_price < 1.0 else 0.0
    exit_fee = (TAKER_FEE_BPS / 10000.0) * exit_uncertainty * (shares * exit_price)

    pnl = shares * (exit_price - entry_price) - entry_fee - exit_fee
    return round(pnl, 2), round(entry_fee + exit_fee, 2)
