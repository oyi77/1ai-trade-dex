"""Single source of truth for all venue fee rates.
Import from here instead of hardcoding fee rates in settlement, strategies, or providers.
"""

# Polymarket
TAKER_FEE_RATE = 0.01          # Polymarket actual taker fee (1%)
MAKER_FEE_RATE = 0.00          # Polymarket maker rebate
TAKER_FEE_BPS = 100            # Same as TAKER_FEE_RATE in basis points

# Kalshi
KALSHI_TAKER_FEE_RATE = 0.07   # Kalshi taker fee (7%)
KALSHI_MAKER_FEE_RATE = 0.0175 # Kalshi maker fee (1.75%)

# Settlement
FEE_USE_STORED = True          # Prefer trade.fee over recalculation
FEE_FALLBACK_RATE = 0.01       # Used when trade.fee is None
SETTLEMENT_USE_FILLED = True   # Prefer filled_size/fill_price over size/entry_price
SETTLEMENT_VALUE_WIN = 1.0     # Redeem value for winning side
SETTLEMENT_VALUE_LOSS = 0.0    # Redeem value for losing side
PNL_INCLUDE_FEE = True         # Whether PnL already includes fee (prevents double-count)
