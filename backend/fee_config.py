"""Single source of truth for all venue fee rates.
Import from here instead of hardcoding fee rates in settlement, strategies, or providers.

Polymarket fee formula: fee = qty × feeRate × p × (1-p)
- fee is proportional to uncertainty (highest at 0.50, near zero at extremes)
- Crypto markets: 70bps or 700bps feeRate
- Non-crypto markets: 30-500bps feeRate
- Maker fees = 0, maker rebates = 20-25% of fee equivalent
"""

# Polymarket
TAKER_FEE_RATE = 0.003  # 30bps (non-crypto default)
MAKER_FEE_RATE = 0.00  # Polymarket maker fee is 0
TAKER_FEE_BPS = 30  # 30 basis points


def polymarket_fee(qty: float, price: float, fee_rate_bps: float = 30.0) -> float:
    """Calculate Polymarket taker fee using exact formula.

    fee = qty × (fee_rate_bps / 10000) × min(p, 1-p)

    Fee is proportional to uncertainty: highest at 0.50, near zero at extremes.
    At 0.95: min(0.95, 0.05) = 0.05 (10x lower than at 0.50).
    """
    fee_rate = fee_rate_bps / 10_000
    return qty * fee_rate * min(price, 1.0 - price)


def polymarket_maker_rebate(qty: float, price: float, fee_rate_bps: float = 30.0, rebate_pct: float = 0.25) -> float:
    """Calculate Polymarket maker rebate (negative fee).

    Rebate = fee_equivalent × rebate_share
    - Non-crypto: 25% rebate
    - Crypto: 20% rebate
    """
    fee_equiv = polymarket_fee(qty, price, fee_rate_bps)
    return -(fee_equiv * rebate_pct)

# Kalshi
KALSHI_TAKER_FEE_RATE = 0.07  # Kalshi taker fee (7%)
KALSHI_MAKER_FEE_RATE = 0.0175  # Kalshi maker fee (1.75%)

# Settlement
FEE_USE_STORED = True  # Prefer trade.fee over recalculation
FEE_FALLBACK_RATE = 0.01  # Used when trade.fee is None
SETTLEMENT_USE_FILLED = True  # Prefer filled_size/fill_price over size/entry_price
SETTLEMENT_VALUE_WIN = 1.0  # Redeem value for winning side
SETTLEMENT_VALUE_LOSS = 0.0  # Redeem value for losing side
PNL_INCLUDE_FEE = True  # Whether PnL already includes fee (prevents double-count)
