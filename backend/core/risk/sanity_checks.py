"""
Sanity Checks — Pre-trade market and source validation.

quick_sanity_check: ~100ms, market health
deep_sanity_check: source wallet quality
"""
from dataclasses import dataclass
from typing import List, Tuple, Optional
import time


@dataclass
class MarketHealth:
    """Market data for sanity checking."""
    market_id: str
    end_date: Optional[float] = None  # Unix timestamp
    book_depth_usd: float = 0.0  # Total order book depth
    spread_cents: float = 0.0  # Bid-ask spread in cents
    last_trade_ts: Optional[float] = None  # Last trade timestamp
    yes_price: float = 0.0
    no_price: float = 0.0


@dataclass
class SourceWallet:
    """Source wallet for deep checking."""
    wallet_address: str
    last_trade_ts: Optional[float] = None
    total_trades: int = 0
    recent_win_rate: float = 0.0  # Last 30 days
    historical_win_rate: float = 0.0  # All time
    wallet_age_days: int = 0
    total_pnl: float = 0.0


def quick_sanity_check(market: MarketHealth) -> Tuple[bool, str]:
    """
    Fast pre-trade sanity check (~100ms).
    Checks: market open, book depth, spread, recent activity, time to expiry.
    """
    now = time.time()

    # Market expired
    if market.end_date and market.end_date < now:
        return False, "Market already resolved/expired"

    # End date too close (< 1 hour)
    if market.end_date and (market.end_date - now) < 3600:
        return False, "Market expires in less than 1 hour"

    # Thin order book
    if market.book_depth_usd < 100:
        return False, f"Order book too thin: ${market.book_depth_usd:.0f} < $100"

    # Wide spread
    if market.spread_cents > 5:
        return False, f"Spread too wide: {market.spread_cents:.1f}c > 5c"

    # No recent trades (24h)
    if market.last_trade_ts and (now - market.last_trade_ts) > 86400:
        return False, "No trades in last 24 hours"

    # Price sanity (YES + NO should be near 1.0)
    total = market.yes_price + market.no_price
    if total > 0 and abs(total - 1.0) > 0.10:
        return False, f"Prices don't sum to ~1.0: {total:.3f}"

    return True, "OK"


def deep_sanity_check(wallet: SourceWallet) -> Tuple[bool, List[str]]:
    """
    Deep validation of a copy trade source wallet.
    Checks: activity, performance, consistency, age, sample size.
    """
    issues = []
    now = time.time()

    # Wallet age
    if wallet.wallet_age_days < 30:
        issues.append(f"Wallet too new: {wallet.wallet_age_days} days < 30")

    # Minimum trades
    if wallet.total_trades < 20:
        issues.append(f"Too few trades: {wallet.total_trades} < 20")

    # Recent activity (7 days)
    if wallet.last_trade_ts and (now - wallet.last_trade_ts) > 604800:
        issues.append("Wallet inactive for > 7 days")

    # Win rate check
    if wallet.historical_win_rate < 0.30:
        issues.append(f"Historical WR too low: {wallet.historical_win_rate:.1%} < 30%")

    # Performance degradation
    if (wallet.recent_win_rate < wallet.historical_win_rate * 0.7 and
        wallet.total_trades > 50):
        issues.append(
            f"Recent WR degraded: {wallet.recent_win_rate:.1%} vs "
            f"historical {wallet.historical_win_rate:.1%}"
        )

    # Negative PnL
    if wallet.total_pnl < -100:
        issues.append(f"Net negative PnL: ${wallet.total_pnl:.2f}")

    is_valid = len(issues) == 0
    return is_valid, issues
