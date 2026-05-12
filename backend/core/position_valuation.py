"""
Position valuation module for calculating market value of open positions.

Extracts position calculation logic from system.py into a reusable module
with fallback pricing, error handling, and telemetry tracking.
"""

import asyncio
import time
from typing import Dict, List, Optional, Any
from sqlalchemy.orm import Session
import httpx

from loguru import logger

from backend.models.database import Trade
from backend.config import settings
from backend.core.alert_manager import AlertManager

# Price cache with 60-second TTL
_ticker_price_cache: Dict[str, Dict[str, float]] = {}
_ticker_price_cache_timestamps: Dict[str, float] = {}
_CACHE_TTL_SECONDS = 60


async def calculate_position_market_value(
    mode: str, db: Session, http_client: Optional[httpx.AsyncClient] = None
) -> dict:
    """
    Calculate position market value for a specific trading mode.

    Args:
        mode: Trading mode ("paper", "testnet", or "live")
        db: SQLAlchemy database session
        http_client: Optional httpx client (creates new one if not provided)

    Returns:
        dict with keys:
            - position_cost: Total USD spent on open positions
            - position_market_value: Current market value of positions
            - unrealized_pnl: Difference between market value and cost
            - telemetry: Dict with pricing stats and error details
    """
    alert_manager = AlertManager(db)
    mode_trades = db.query(Trade).filter(~Trade.settled, Trade.trading_mode == mode).all()

    position_cost = 0.0
    position_market_value = 0.0
    unrealized_pnl = 0.0

    # Telemetry tracking
    telemetry = {
        "prices_fetched": 0,
        "prices_cached": 0,
        "fallbacks_used": 0,
        "failures": [],
        "errors": [],
    }

    if not mode_trades:
        return {
            "position_cost": 0.0,
            "position_market_value": 0.0,
            "unrealized_pnl": 0.0,
            "telemetry": telemetry,
            "price_certainty": "actual",
        }

    # Extract unique tickers
    tickers = list({t.market_ticker for t in mode_trades if t.market_ticker})

    if not tickers:
        # No tickers to fetch, but we have trades - calculate cost only
        position_cost = sum((t.size or 0.0) for t in mode_trades)
        logger.warning(
            f"Mode {mode}: {len(mode_trades)} open trades but no market_ticker set"
        )
        return {
            "position_cost": round(position_cost, 2),
            "position_market_value": 0.0,
            "unrealized_pnl": round(-position_cost, 2),
            "telemetry": telemetry,
            "price_certainty": "actual",
        }

    # Fetch prices with fallback strategy
    ticker_to_price = await _fetch_prices_with_fallback(
        tickers, http_client, telemetry
    )

    # Calculate position values
    for t in mode_trades:
        size = t.size or 0.0
        position_cost += size

        if not t.market_ticker:
            continue

        # Get current price with fallback chain
        current_price = None

        if t.market_ticker in ticker_to_price:
            prices = ticker_to_price[t.market_ticker]
            direction = t.direction
            if direction == "up":
                current_price = prices.get("yes_price")
            else:
                # For "down" positions, use 1 - no_price (equivalent to yes_price)
                no_price = prices.get("no_price")
                if no_price is not None:
                    current_price = 1.0 - no_price
                else:
                    current_price = None

        # Fallback chain: cached → entry_price → 0.5 (mid-price)
        if current_price is None:
            # Fallback to entry_price
            if t.entry_price and 0 < t.entry_price < 1:
                current_price = t.entry_price
                telemetry["fallbacks_used"] += 1
                logger.warning(
                    f"Using entry_price fallback for {t.market_ticker}: {current_price}"
                )
            else:
                # Last resort: mid-price
                current_price = 0.5
                telemetry["fallbacks_used"] += 1
                logger.warning(
                    f"Using mid-price fallback (0.5) for {t.market_ticker}"
                )

        # Calculate market value using exact formula from system.py:259-282
        entry = t.entry_price or 0.5
        direction = t.direction

        if entry > 0 and entry < 1:
            shares = size / entry
            mkt_val = shares * current_price
        else:
            # Edge case: invalid entry_price
            mkt_val = size
            logger.warning(
                f"Invalid entry_price {entry} for trade {t.id}, using size as market value"
            )

        position_market_value += mkt_val

    # Calculate unrealized P&L
    unrealized_pnl = round(position_market_value - position_cost, 2)
    position_cost = round(position_cost, 2)
    position_market_value = round(position_market_value, 2)

    # Validation: warn if positions exist but value is 0.0
    if len(mode_trades) > 0 and position_market_value == 0.0:
        warning_msg = (
            f"SUSPICIOUS: {len(mode_trades)} open trades in {mode} mode "
            f"but position_market_value=0.0. Check price fetching."
        )
        logger.warning(warning_msg)
        telemetry["errors"].append(
            {"type": "validation", "message": warning_msg, "timestamp": time.time()}
        )

        alert_manager.check_position_discrepancy(
            position_id=f"{mode}_portfolio",
            db_value=position_cost,
            blockchain_value=0.0,
            mode=mode,
        )

    # Circuit breaker: alert if >50% of tickers failed
    if tickers:
        failure_rate = len(telemetry["failures"]) / len(tickers)
        if failure_rate > 0.5:
            critical_msg = (
                f"CRITICAL: {len(telemetry['failures'])}/{len(tickers)} "
                f"({failure_rate:.1%}) tickers failed to fetch prices in {mode} mode"
            )
            logger.critical(critical_msg)
            telemetry["errors"].append(
                {
                    "type": "circuit_breaker",
                    "message": critical_msg,
                    "timestamp": time.time(),
                }
            )

    return {
        "position_cost": position_cost,
        "position_market_value": position_market_value,
        "unrealized_pnl": unrealized_pnl,
        "price_certainty": "estimated" if telemetry["fallbacks_used"] > 0 else "actual",
        "telemetry": telemetry,
    }


async def _fetch_prices_with_fallback(
    tickers: List[str],
    http_client: Optional[httpx.AsyncClient],
    telemetry: Dict[str, Any],
) -> Dict[str, Dict[str, float]]:
    """
    Fetch prices from Gamma API with caching and error tracking.

    Args:
        tickers: List of market tickers to fetch
        http_client: Optional httpx client
        telemetry: Telemetry dict to update with stats

    Returns:
        Dict mapping ticker to price data {"yes_price": float, "no_price": float}
    """
    ticker_to_price = {}
    now = time.time()

    async def fetch_ticker_price(ticker: str, client: httpx.AsyncClient):
        """Fetch price for a single ticker with caching."""
        # Check cache first
        if ticker in _ticker_price_cache:
            cache_time = _ticker_price_cache_timestamps.get(ticker, 0)
            if now - cache_time < _CACHE_TTL_SECONDS:
                telemetry["prices_cached"] += 1
                return ticker, _ticker_price_cache[ticker], None

        # Fetch from API
        try:
            if ticker.isdigit():
                # Token ID - use CLOB API midpoint
                r = await client.get(
                    f"{settings.CLOB_API_URL}/midpoint?token_id={ticker}",
                    timeout=5.0,
                )
                r.raise_for_status()
                data = r.json()
                mid = float(data.get("mid", 0.5))
                price_data = {
                    "yes_price": mid,
                    "no_price": mid,
                }

                # Update cache
                _ticker_price_cache[ticker] = price_data
                _ticker_price_cache_timestamps[ticker] = now
                telemetry["prices_fetched"] += 1
                return ticker, price_data, None
            else:
                # Slug - use Gamma API
                r = await client.get(
                    f"{settings.GAMMA_API_URL}/markets?slug={ticker}",
                    timeout=5.0,
                )
                r.raise_for_status()
                data = r.json()

                if data and isinstance(data, list) and len(data) > 0:
                    m = data[0]
                    price_data = {
                        "yes_price": float(m.get("yes_price") or 0.5),
                        "no_price": float(m.get("no_price") or 0.5),
                    }
                    # Update cache
                    _ticker_price_cache[ticker] = price_data
                    _ticker_price_cache_timestamps[ticker] = now
                    telemetry["prices_fetched"] += 1
                    return ticker, price_data, None
                else:
                    error_msg = f"Empty or invalid response for {ticker}"
                    logger.error(error_msg)
                    return ticker, None, "invalid_response"

        except httpx.TimeoutException as e:
            error_msg = f"Timeout fetching price for {ticker}: {e}"
            logger.error(error_msg)
            telemetry["failures"].append(
                {"ticker": ticker, "reason": "timeout", "timestamp": now}
            )
            return ticker, None, "timeout"

        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP {e.response.status_code} for {ticker}: {e}"
            logger.error(error_msg)
            telemetry["failures"].append(
                {
                    "ticker": ticker,
                    "reason": f"http_{e.response.status_code}",
                    "timestamp": now,
                }
            )
            return ticker, None, f"http_{e.response.status_code}"

        except Exception as e:
            error_msg = f"Unexpected error fetching {ticker}: {e}"
            logger.error(error_msg)
            telemetry["failures"].append(
                {"ticker": ticker, "reason": "unknown", "timestamp": now}
            )
            return ticker, None, "unknown"

    # Create client if not provided
    should_close_client = http_client is None
    if http_client is None:
        http_client = httpx.AsyncClient(timeout=5.0)

    try:
        # Fetch all tickers in parallel (limit to 20 to avoid overwhelming API)
        tasks = [fetch_ticker_price(ticker, http_client) for ticker in tickers[:20]]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Task exception: {result}")
                continue

            ticker, price_data, error_reason = result
            if price_data:
                ticker_to_price[ticker] = price_data
            elif error_reason:
                telemetry["errors"].append(
                    {
                        "ticker": ticker,
                        "reason": error_reason,
                        "timestamp": now,
                    }
                )

    finally:
        if should_close_client:
            await http_client.aclose()

    return ticker_to_price
