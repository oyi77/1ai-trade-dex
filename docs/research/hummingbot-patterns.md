# Hummingbot Patterns for Prediction Market Market-Making

## Overview

Hummingbot is an open-source market-making bot that provides battle-tested patterns applicable to prediction market market-making. This document extracts key patterns relevant to Polymarket/Kalshi-style binary outcome markets.

## 1. Inventory Management

### Pattern: Symmetric Inventory Skew

Hummingbot adjusts bid/ask spreads based on current inventory position to avoid accumulating excessive directional exposure.

```
Inventory ratio = current_base / target_base
Skew factor = (inventory_ratio - 0.5) * skew_strength
Bid spread += skew_factor  (widen bids when long, tighten when short)
Ask spread -= skew_factor  (tighten asks when long, widen when short)
```

**Application to prediction markets:**
- YES/NO positions are symmetric (buying NO = selling YES)
- Track net YES inventory across all open orders
- Skew spreads toward reducing inventory imbalance
- In binary markets, inventory risk is bounded (0-1 price range)

### Pattern: Target Inventory Rebalancing

Set a target inventory split (e.g., 50/50 YES/NO) and adjust order sizes to converge toward it.

```
if yes_inventory > target:
    reduce_yes_order_size()
    increase_no_order_size()
```

## 2. Spread Calculation

### Pattern: Multi-Factor Spread

Hummingbot combines multiple spread components:

```
Total spread = Base spread
             + Volatility spread (from recent price movement)
             + Inventory spread (from inventory skew)
             + Competition spread (from order book depth)
```

**Application to prediction markets:**
- **Base spread**: Minimum profitable spread accounting for fees (Polymarket: 2% taker fee)
- **Volatility spread**: Widen during high-uncertainty events (pre-announcement, live sports)
- **Inventory spread**: Asymmetric adjustment based on YES/NO balance
- **Competition spread**: Tighten when order book is thin, widen when thick

### Pattern: Minimum Profitable Spread

```
min_spread = 2 * taker_fee_rate / (1 - taker_fee_rate)
# For Polymarket (2% fee): min_spread ≈ 0.0408 (4.08%)
```

## 3. Order Book Management

### Pattern: Hanging Orders

Orders that persist across refresh cycles, only cancelled when:
- Price moves beyond a threshold from the hanging order
- Hanging order age exceeds maximum
- Inventory limit would be breached

**Application:** Keep resting limit orders on Polymarket CLOB to earn maker rebates.

### Pattern: Order Refresh

Periodically refresh orders to:
- Update spreads based on new information
- Maintain position in the order book queue
- Avoid stale orders after price movements

```
every ORDER_REFRESH_TIME:
    cancel_all_orders()
    create_new_orders_with_current_spreads()
```

### Pattern: Price Ceiling and Floor

Set absolute price boundaries beyond which the bot won't place orders:

```
bid_price = max(bid_price, PRICE_FLOOR)  # Don't bid below 0.02
ask_price = min(ask_price, PRICE_CEILING)  # Don't ask above 0.98
```

**Application:** In prediction markets, prices below 0.02 or above 0.98 have extreme risk/reward. Set boundaries at 0.03/0.97 to avoid extreme positions.

## 4. Risk Management

### Pattern: Maximum Order Age

Cancel and replace orders older than a threshold to avoid adverse selection:

```
if order.age > MAX_ORDER_AGE:
    cancel(order)
    place_new_order()
```

### Pattern: Filled Order Delay

After a fill, wait before placing the next order to:
- Avoid chasing the price
- Let the market stabilize
- Prevent rapid inventory accumulation

```
if just_filled:
    wait(FILLED_ORDER_DELAY)
    place_new_order()
```

### Pattern: Volatility-Adjusted Order Size

Reduce order size during high volatility:

```
volatility = compute_recent_volatility()
order_size = base_order_size * (1 / (1 + volatility * vol_scale_factor))
```

## 5. Cross-Market Considerations

### Pattern: Correlated Market Awareness

When market-making on correlated markets (e.g., "Will X happen?" and "Will X happen by Y?"):
- Track combined exposure across correlated markets
- Reduce position limits per market when correlation is high
- Use correlation for hedging opportunities

### Pattern: Event-Driven Spread Adjustment

Tighten spreads before known events (earnings, votes) to capture flow, widen after to manage resolution risk:

```
if event_imminent:
    tighten_spreads(factor=0.5)
    reduce_position_limits(factor=0.3)
elif event_just_passed:
    widen_spreads(factor=2.0)
    pause_until_resolution()
```

## 6. Fee Optimization

### Pattern: Maker vs Taker Optimization

Prefer maker orders (limit orders that rest on the book) over taker orders:

```
Expected profit (maker) = spread - maker_fee
Expected profit (taker) = spread - taker_fee  # Always worse
```

On Polymarket: maker fee = 0%, taker fee = 2%. Always use limit orders.

### Pattern: Batch Settlement

Accumulate multiple small positions and settle them together to reduce per-trade overhead.

## References

- [Hummingbot Documentation](https://hummingbot.org/)
- [Hummingbot GitHub](https://github.com/hummingbot/hummingbot)
- [Polymarket CLOB Documentation](https://docs.polymarket.com/)
