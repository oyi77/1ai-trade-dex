"""Settlement helper functions - API resolution, P&L calculation, weather calibration."""

import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session, sessionmaker

import httpx
from cachetools import TTLCache

from backend.models.database import Trade, Signal, SettlementEvent, TradeContext
from backend.config import settings

from loguru import logger
# Module-level: track consecutive 404s per market_id (bounded TTLCache: 1000 entries, 1 hour TTL)
_market_404_counts: TTLCache = TTLCache(maxsize=1000, ttl=3600)

# Module-level: cache already-resolved markets to skip redundant gamma REST calls
# TTL=3600s (1h) — resolved markets don't change; prevents 429 on repeated settlement cycles
_resolved_market_cache: TTLCache = TTLCache(maxsize=2000, ttl=3600)

# Semaphore: cap concurrent gamma API calls to avoid 429 rate limiting
# Initialized lazily in _resolve_markets (asyncio event loop must be running)
_gamma_semaphore: Optional[asyncio.Semaphore] = None

# In-flight deduplication: maps ticker -> asyncio.Event
# Prevents thundering-herd cache stampede when multiple coroutines resolve
# the same conditionId concurrently before any result is cached.
_gamma_inflight: dict = {}


def _looks_like_token_id(value: str) -> bool:
    """Detect Polymarket CLOB token IDs.

    Token IDs are long decimal strings (typically 70+ digits, ERC1155 token IDs
    derived from conditionId + outcome index). They're distinct from:
      - Numeric Gamma market IDs (short, < 12 digits)
      - Slugs (contain hyphens / non-digit chars)
      - Condition IDs (start with 0x)
    """
    if not value or not isinstance(value, str):
        return False
    if not value.isdigit():
        return False
    return len(value) >= 20


async def _resolve_pm_by_token_id(token_id: str) -> Tuple[bool, Optional[float]]:
    """Resolve a Polymarket market via CLOB token_id (Gamma API).

    Uses ``gamma-api.polymarket.com/markets?clob_token_ids={tid}&closed=true``
    which is the only reliable path when we only have a token_id (no slug, no
    numeric market id).

    Picks the outcome index by matching the token_id's position inside the
    market's ``clobTokenIds`` array, then reads the corresponding
    ``outcomePrices[i]``. settlement_value is the price of OUR token's outcome
    (1.0 = our outcome won, 0.0 = our outcome lost). The caller's calculate_pnl
    treats settlement_value=1.0 as YES/UP-wins.

    Note: this returns the value from the *token's* perspective normalized to
    yes/up semantics — i.e. if the trade's token is the "Yes" leg and Yes wins,
    we return 1.0; if the token is the "No" leg and No wins, we still return
    1.0 because *our* outcome won. This matches how stuck trades are stored:
    direction='up' simply means "the token we bought".
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            for closed_flag in ("true", "false"):
                try:
                    resp = await client.get(
                        f"{settings.GAMMA_API_URL}/markets",
                        params={
                            "clob_token_ids": token_id,
                            "closed": closed_flag,
                            "limit": 1,
                        },
                        timeout=10.0,
                    )
                except (httpx.TimeoutException, httpx.ConnectTimeout):
                    continue

                if resp.status_code != 200:
                    continue

                data = resp.json()
                if not data or not isinstance(data, list):
                    continue

                market = data[0]
                clob_token_ids = market.get("clobTokenIds", [])
                outcome_prices = market.get("outcomePrices", [])

                if isinstance(clob_token_ids, str):
                    try:
                        clob_token_ids = json.loads(clob_token_ids)
                    except (ValueError, TypeError):
                        clob_token_ids = []
                if isinstance(outcome_prices, str):
                    try:
                        outcome_prices = json.loads(outcome_prices)
                    except (ValueError, TypeError):
                        outcome_prices = []

                if not clob_token_ids or not outcome_prices:
                    continue
                if len(clob_token_ids) != len(outcome_prices):
                    continue

                idx = None
                for i, tid in enumerate(clob_token_ids):
                    if str(tid) == str(token_id):
                        idx = i
                        break
                if idx is None:
                    continue

                is_closed = bool(market.get("closed", False))
                uma_status = (market.get("umaResolutionStatus") or "").lower()
                resolved = is_closed or uma_status == "resolved"
                if not resolved:
                    continue

                try:
                    our_price = float(outcome_prices[idx])
                except (ValueError, TypeError):
                    continue

                if our_price >= 0.99:
                    logger.info(
                        f"PM token-id {token_id[:16]}... resolved: WON "
                        f"(idx={idx}, price={our_price})"
                    )
                    return True, 1.0
                if our_price <= 0.01:
                    logger.info(
                        f"PM token-id {token_id[:16]}... resolved: LOST "
                        f"(idx={idx}, price={our_price})"
                    )
                    return True, 0.0

                return False, None

            return False, None

    except Exception as e:
        logger.warning(
            f"[settlement_helpers._resolve_pm_by_token_id] {type(e).__name__}: "
            f"Failed for token {token_id[:16]}...: {e}"
        )
        return False, None


async def fetch_polymarket_resolution(
    market_id: str, event_slug: Optional[str] = None, condition_id: Optional[str] = None
) -> Tuple[bool, Optional[float]]:
    """
    Fetch actual market resolution from Polymarket API.

    For BTC 5-min markets, uses event slug to find the market.
    When condition_id is provided, queries Gamma by condition_id directly.

    Returns: (is_resolved, settlement_value)
        - settlement_value: 1.0 if our outcome (Up/Yes leg) won, 0.0 if it lost.

    For wallet-reconciliation imports the market_ticker is often a CLOB
    token_id (long decimal string). In that case we route through
    ``_resolve_pm_by_token_id`` which handles outcome-index mapping correctly.
    """
    # New: try condition_id first (most reliable for settlement)
    if condition_id:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{settings.GAMMA_API_URL}/markets",
                    params={"condition_id": condition_id},
                )
                if resp.status_code == 200:
                    markets = resp.json()
                    if isinstance(markets, list) and markets:
                        result = _parse_market_resolution(markets[0])
                        if result[0]:
                            return result
        except Exception:
            pass

    if _looks_like_token_id(market_id):
        resolved, value = await _resolve_pm_by_token_id(market_id)
        if resolved:
            return resolved, value

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Try event slug first (more reliable for BTC 5-min markets)
            if event_slug:
                response = await client.get(
                    f"{settings.GAMMA_API_URL}/events",
                    params={"slug": event_slug},
                )
                response.raise_for_status()
                events = response.json()

                if events:
                    event = events[0] if isinstance(events, list) else events
                    markets = event.get("markets", [])
                    if markets:
                        return _parse_market_resolution(markets[0])

            # Try slug-based query first (market_id may be a slug, not numeric ID)
            try:
                slug_response = await client.get(
                    f"{settings.GAMMA_API_URL}/markets",
                    params={"slug": market_id},
                    timeout=5.0,
                )
                if slug_response.status_code == 200:
                    slug_results = slug_response.json()
                    if isinstance(slug_results, list) and slug_results:
                        result = _parse_market_resolution(slug_results[0])
                        # If Gamma says unresolved but prices are 0/null, check CLOB
                        if not result[0] and _has_invalid_prices(slug_results[0]):
                            clob_result = await _check_clob_resolution(market_id)
                            if clob_result[0]:
                                return clob_result
                        return result
            except (httpx.TimeoutException, httpx.ConnectTimeout):
                logger.debug(
                    f"Market query timeout for {market_id}, trying event query"
                )

            # If market query times out, try querying by event slug
            # Extract event slug by removing the last suffix (e.g., -scf, -cel4, -draw)
            if "-" in market_id:
                parts = market_id.rsplit("-", 1)
                if len(parts) == 2 and len(parts[1]) <= 5:
                    event_slug = parts[0]
                    try:
                        event_response = await client.get(
                            f"{settings.GAMMA_API_URL}/events",
                            params={"slug": event_slug},
                            timeout=5.0,
                        )
                        if event_response.status_code == 200:
                            events = event_response.json()
                            if events and isinstance(events, list):
                                event = events[0]
                                markets = event.get("markets", [])
                                for market in markets:
                                    if market.get("slug") == market_id:
                                        return _parse_market_resolution(market)
                    except Exception as e:
                        logger.debug(
                            f"[settlement_helpers.fetch_polymarket_resolution] {type(e).__name__}: Event query failed for {event_slug}: {e}",
                            exc_info=True
                        )

            # Fallback: try market ID directly (works for numeric IDs)
            url = f"{settings.GAMMA_API_URL}/markets/{market_id}"
            response = await client.get(url)

            if response.status_code in (404, 422):
                _market_404_counts[market_id] = _market_404_counts.get(market_id, 0) + 1
                if _market_404_counts[market_id] >= 3:
                    logger.debug(
                        f"Skipping market {market_id} — 3+ consecutive 404/422s"
                    )
                    # Try CLOB as last resort before giving up
                    clob_result = await _check_clob_resolution(market_id)
                    if clob_result[0]:
                        return clob_result
                    return False, None
                return await _search_market_in_events(market_id)

            response.raise_for_status()
            market = response.json()
            return _parse_market_resolution(market)

    except Exception as e:
        logger.warning(
            f"[settlement_helpers.fetch_polymarket_resolution] {type(e).__name__}: Failed to fetch resolution for {event_slug or market_id}: {e}"
        )
        return False, None


def _has_invalid_prices(market: dict) -> bool:
    """Check if market has invalid/zero prices that suggest delisted market."""
    outcome_prices = market.get("outcomePrices", [])
    if not outcome_prices:
        return True
    try:
        if isinstance(outcome_prices, str):
            outcome_prices = json.loads(outcome_prices)
        prices = [float(p) for p in outcome_prices if p]
        if not prices or all(p == 0 for p in prices):
            return True
    except (ValueError, TypeError):
        return True
    return False


async def _check_clob_resolution(market_id: str) -> Tuple[bool, Optional[float]]:
    """Check CLOB API for market closed status."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{settings.CLOB_API_URL}/markets?slug={market_id}"
            )
            if response.status_code == 200:
                data = response.json()
                if data and isinstance(data, dict) and "data" in data:
                    markets = data["data"]
                    if markets and isinstance(markets, list):
                        market = markets[0]
                        if market.get("closed"):
                            logger.info(f"CLOB confirms market {market_id} is closed")
                            return True, None
    except Exception as e:
        logger.debug(
            f"[settlement_helpers._check_clob_resolution] {type(e).__name__}: CLOB resolution check failed for {market_id}: {e}",
            exc_info=True
        )
    return False, None


async def _search_market_in_events(market_id: str) -> Tuple[bool, Optional[float]]:
    """Search for market in events (both active and closed)."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            for closed in [True, False]:
                params = {"closed": str(closed).lower(), "limit": 200}
                response = await client.get(
                    f"{settings.GAMMA_API_URL}/events", params=params
                )
                response.raise_for_status()
                events = response.json()

                for event in events:
                    for market in event.get("markets", []):
                        if str(market.get("id")) == str(market_id):
                            return _parse_market_resolution(market)

        return False, None

    except Exception as e:
        logger.warning(
            f"[settlement_helpers._search_market_in_events] {type(e).__name__}: Failed to search for market {market_id}: {e}"
        )
        return False, None


def _parse_market_resolution(market: dict) -> Tuple[bool, Optional[float]]:
    """
    Parse market data to determine if resolved and outcome.

    Handles both Yes/No and Up/Down outcomes.
    - outcomePrices[0] > 0.99 -> first outcome won (Yes or Up)
    - outcomePrices[0] < 0.01 -> second outcome won (No or Down)

    Also supports early resolution heuristic: if the market is not yet
    officially closed but prices are extreme AND the event appears to have
    concluded, treat it as resolved so we don't wait hours for Polymarket
    to flip the closed flag.
    """
    is_closed = market.get("closed", False)

    outcome_prices = market.get("outcomePrices", [])
    if not outcome_prices:
        return False, None

    try:
        if isinstance(outcome_prices, str):
            outcome_prices = json.loads(outcome_prices)

        first_price = float(outcome_prices[0]) if outcome_prices else 0.5

        # --- Officially closed: use tight thresholds (existing logic) ---
        if is_closed:
            if first_price > 0.99:
                logger.info(f"Market {market.get('id')} resolved: UP/YES won")
                return True, 1.0
            elif first_price < 0.01:
                logger.info(f"Market {market.get('id')} resolved: DOWN/NO won")
                return True, 0.0
            else:
                return False, None

        # --- Early resolution heuristic (market not yet closed) ---
        # Graduated thresholds based on how strong the resolution signal is:
        #
        # Tier 1: events[0].ended == True → 0.90/0.10 (confirmed ended)
        # Tier 2: endDate passed + 30min → 0.90/0.10 (likely ended, not flagged)
        # Tier 3: endDate passed + 2h   → 0.80/0.20 (definitely over, slow resolution)
        # Tier 4: endDate passed + 6h   → 0.70/0.30 (stale market, force resolve)
        #
        # The key insight: if endDate has passed, the event is OVER — prices
        # reflect the known outcome, not speculation. Polymarket is just slow
        # to officially close/resolve.

        events = market.get("events", [])
        has_ended_flag = False
        is_live = False
        if events and isinstance(events, list):
            ev = events[0] if isinstance(events[0], dict) else {}
            has_ended_flag = ev.get("ended") is True
            is_live = ev.get("live") is True and not has_ended_flag

        # Compute hours_past_end BEFORE the is_live check so we can
        # override the live flag for games that are clearly over.
        now = datetime.now(timezone.utc)
        end_date_str = market.get("endDate")
        hours_past_end = 0.0
        if end_date_str:
            try:
                end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                if now > end_date:
                    hours_past_end = (now - end_date).total_seconds() / 3600.0
            except (ValueError, TypeError):
                pass

        # If the game is explicitly live AND the endDate hasn't been
        # surpassed by a wide margin, don't early-resolve.
        # Polymarket's `live` flag often stays True for HOURS after a
        # game ends, so we only trust it when endDate hasn't passed by
        # much (< 30 minutes).
        if is_live and hours_past_end < 0.5:
            return False, None

        # Gamma API endDate can reference a group/series date, not the
        # actual market resolution.  Only block the ZOMBIE tier (48h+)
        # when the market is still actively trading — because the loose
        # 0.55/0.45 thresholds can misfire on misleading endDates.
        # Tiers 2-4 are fine because they require strong price signals
        # (≥0.65 or ≤0.35) that only occur on genuinely finished markets.
        market_still_open = (
            market.get("active", False)
            and not market.get("closed", False)
            and not has_ended_flag
        )

        # Select threshold based on strongest signal
        # Graduated tiers: more time past endDate = looser thresholds.
        # Rationale: once endDate passes, the price IS the outcome —
        # Polymarket is just slow to officially close. We can resolve
        # earlier to free up capital.
        if has_ended_flag:
            # Tier 1: API confirms event ended
            early_threshold_high = 0.90
            early_threshold_low = 0.10
            tier = "ended-flag"
        elif hours_past_end >= 48.0:
            # Tier 6: 48+ hours past endDate — extremely stale.
            logger.info(
                f"Market {market.get('id')} Tier6 check: market_still_open={market_still_open}, "
                f"hours_past_end={hours_past_end:.0f}, first_price={first_price:.4f}"
            )
            if market_still_open:
                # Market is still flagged active — Gamma API endDate may be
                # misleading (group/series date).  But if the price is
                # extremely decisive (≥0.95/≤0.05), the outcome is clear
                # regardless of the active flag.  Otherwise, skip.
                if first_price >= 0.95 or first_price <= 0.05:
                    early_threshold_high = 0.95
                    early_threshold_low = 0.05
                    tier = f"zombie-forced-{hours_past_end:.0f}h"
                else:
                    logger.info(
                        f"Market {market.get('id')} skipping zombie resolution: "
                        f"still active, endDate {hours_past_end:.0f}h ago (likely misleading)"
                    )
                    return False, None
            else:
                # Market not actively open but still not officially closed
                early_threshold_high = 0.70
                early_threshold_low = 0.30
                tier = f"zombie-{hours_past_end:.0f}h"
        elif hours_past_end >= 12.0:
            if market_still_open:
                # Still-open markets 12h+ past endDate: resolve only if
                # price is extremely decisive — Polymarket often leaves
                # the active flag on for hours after resolution.
                if first_price >= 0.95 or first_price <= 0.05:
                    early_threshold_high = 0.95
                    early_threshold_low = 0.05
                    tier = f"very-stale-forced-{hours_past_end:.1f}h"
                else:
                    return False, None
            else:
                early_threshold_high = 0.70
                early_threshold_low = 0.30
                tier = f"very-stale-{hours_past_end:.1f}h"
        elif hours_past_end >= 6.0:
            if market_still_open:
                # 6h+ past endDate and still "active": only force-resolve
                # on very strong signals (≥0.95/≤0.05).
                if first_price >= 0.95 or first_price <= 0.05:
                    early_threshold_high = 0.95
                    early_threshold_low = 0.05
                    tier = f"stale-forced-{hours_past_end:.1f}h"
                else:
                    return False, None
            else:
                early_threshold_high = 0.75
                early_threshold_low = 0.25
                tier = f"stale-{hours_past_end:.1f}h"
        elif hours_past_end >= 2.0:
            if market_still_open:
                # 2-6h past endDate: only resolve on extreme prices
                if first_price >= 0.97 or first_price <= 0.03:
                    early_threshold_high = 0.97
                    early_threshold_low = 0.03
                    tier = f"overdue-forced-{hours_past_end:.1f}h"
                else:
                    return False, None
            else:
                early_threshold_high = 0.70
                early_threshold_low = 0.30
                tier = f"overdue-{hours_past_end:.1f}h"
        elif hours_past_end >= 0.5:
            # Tier 2: 30min-2h past endDate
            early_threshold_high = 0.85
            early_threshold_low = 0.15
            tier = f"recent-{hours_past_end:.1f}h"
        else:
            # Event hasn't ended yet — use very strict thresholds
            early_threshold_high = 0.97
            early_threshold_low = 0.03
            tier = "pre-end"

        if first_price > early_threshold_high:
            # Only require event_concluded check for pre-end tier
            if tier == "pre-end":
                event_concluded = _check_event_concluded(market)
                if not event_concluded:
                    return False, None
            logger.info(
                f"Market {market.get('id')} early-resolved (price={first_price:.3f}, "
                f"tier={tier}, threshold={early_threshold_high}): UP/YES won"
            )
            return True, 1.0
        elif first_price < early_threshold_low:
            if tier == "pre-end":
                event_concluded = _check_event_concluded(market)
                if not event_concluded:
                    return False, None
            logger.info(
                f"Market {market.get('id')} early-resolved (price={first_price:.3f}, "
                f"tier={tier}, threshold={early_threshold_low}): DOWN/NO won"
            )
            return True, 0.0

        return False, None

    except (ValueError, IndexError, TypeError) as e:
        logger.warning(f"Failed to parse outcome prices: {e}")
        return False, None


def _check_event_concluded(market: dict) -> bool:
    """
    Determine whether the underlying event has concluded, even if Polymarket
    hasn't set closed=True yet.

    For sports markets: checks ``events[0].ended`` flag.
    For non-sports:     checks whether ``endDate`` has passed by ≥2 hours.
    """
    now = datetime.now(timezone.utc)

    events = market.get("events", [])
    if events and isinstance(events, list):
        event = events[0] if isinstance(events[0], dict) else {}
        if event.get("ended") is True:
            return True

    end_date_str = market.get("endDate")
    if end_date_str:
        try:
            end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
            hours_past = (
                (now - end_date).total_seconds() / 3600.0 if now > end_date else 0.0
            )
            if hours_past >= 2.0:
                return True
            # Only trust is_live flag when endDate hasn't been exceeded
            if events and isinstance(events, list):
                ev = events[0] if isinstance(events[0], dict) else {}
                if (
                    ev.get("live") is True
                    and ev.get("ended") is not True
                    and hours_past < 0.5
                ):
                    return False
        except (ValueError, TypeError):
            pass

    return False


async def _resolve_btc_updown_via_binance(ticker: str) -> Optional[float]:
    """
    Resolve BTC up/down 5-min market via Binance price data.
    Slug format: btc-updown-5m-TIMESTAMP
    Returns 1.0 if BTC went up, 0.0 if down. None if unable to determine.
    """
    import httpx

    parts = ticker.split("-")
    if len(parts) < 4:
        return None
    try:
        market_ts = int(parts[-1])
    except ValueError:
        return None

    start_ms = market_ts * 1000
    end_ms = (market_ts + 300) * 1000
    url = f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1m&startTime={start_ms}&endTime={end_ms}&limit=5"

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=10.0)
        data = resp.json()
        if not data:
            return None
        open_price = float(data[0][1])
        close_price = float(data[-1][4])
        result = 1.0 if close_price > open_price else 0.0
        logger.info(
            f"[settlement] BTC Binance fallback: {ticker} open=${open_price:.2f} close=${close_price:.2f} -> {'up' if result == 1.0 else 'down'}"
        )
        return result


async def _fetch_kalshi_resolution(ticker: str) -> Tuple[bool, Optional[float]]:
    """Fetch resolution status for a Kalshi market."""
    try:
        from backend.data.kalshi_client import KalshiClient, kalshi_credentials_present

        if not kalshi_credentials_present():
            return False, None

        client = KalshiClient()
        data = await client.get_market(ticker)
        market = data.get("market", data)

        status = market.get("status", "")
        result = market.get("result", "")

        if status in ("finalized", "determined") and result:
            if result == "yes":
                return True, 1.0
            elif result == "no":
                return True, 0.0

        return False, None

    except Exception as e:
        logger.warning(
            f"[settlement_helpers._fetch_kalshi_resolution] {type(e).__name__}: Failed to fetch Kalshi resolution for {ticker}: {e}"
        )
        return False, None


async def fetch_resolution_for_trade(trade: Trade) -> Tuple[bool, Optional[float]]:
    """Platform-aware resolution dispatch via market registry.

    Returns: (is_resolved, settlement_value) where settlement_value ∈ {0.0, 1.0}.
    Routes to Kalshi or Polymarket based on trade.platform; defaults to polymarket
    when platform is missing (legacy rows).

    Tries market provider registry first, falls back to legacy platform-specific
    resolution functions when registry is unavailable.
    """
    platform = (getattr(trade, "platform", None) or "polymarket").lower()

    # Try registered provider first
    try:
        from backend.markets.provider_registry import market_registry
        provider = market_registry.get(platform)
        if provider and hasattr(provider, 'resolve_market'):
            is_resolved, value = await provider.resolve_market(trade.market_ticker)
            if is_resolved:
                return True, value
    except Exception:
        pass

    # Legacy fallback — wrap in error handling to prevent scheduler hang on API timeout
    try:
        if platform == "kalshi":
            return await _fetch_kalshi_resolution(trade.market_ticker)
        return await fetch_polymarket_resolution(
            trade.market_ticker,
            event_slug=getattr(trade, "event_slug", None),
            condition_id=getattr(trade, "condition_id", None),
        )
    except Exception as e:
        logger.warning(
            f"[settlement] Resolution fetch failed for {trade.market_ticker} (platform={platform}): {type(e).__name__}: {e}"
        )

    # BTC up/down 5-min fallback: resolve via Binance price data
    ticker = getattr(trade, "market_ticker", "") or ""
    if ticker.startswith("btc-updown-5m-"):
        try:
            result = await _resolve_btc_updown_via_binance(ticker)
            if result is not None:
                return True, result
        except Exception as e:
            logger.warning(f"[settlement] BTC Binance fallback failed for {ticker}: {e}")

    # Return unresolved status — trade will be marked as expired_unresolved to avoid PnL misreports
    return False, None


def calculate_pnl(trade: Trade, settlement_value: float) -> float:
    """
    Calculate P&L for a trade given the settlement value.

    settlement_value: 1.0 if Up/Yes outcome, 0.0 if Down/No outcome

    Maps up->yes, down->no internally:
    - UP position wins when settlement = 1.0
    - DOWN position wins when settlement = 0.0

    IMPORTANT: `size` is the number of shares purchased (not dollars spent).
    `entry_price` is the cost per share (0.0–1.0).
    On a win, each share pays $1: net profit = (1.0 - entry_price) * size.
    On a loss, shares are worth $0: net loss = -(entry_price * size).
    Verified against real CLOB fills: entry=0.505, size=24.75 → win pnl=12.25, loss pnl=-12.50.
    """
    # Map up/down to yes/no logic
    direction = trade.direction
    if direction == "up":
        direction = "yes"
    elif direction == "down":
        direction = "no"

    _filled = getattr(trade, "filled_size", None)
    size = float(_filled) if isinstance(_filled, (int, float)) else trade.size

    _fill_price = getattr(trade, "fill_price", None)
    entry_price = float(_fill_price) if isinstance(_fill_price, (int, float)) else trade.entry_price

    if not entry_price or entry_price <= 0 or entry_price >= 1.0:
        if entry_price and entry_price >= 1.0:
            # Entry at $1.00+: win gives 0 profit (bought at $1, get $1 back),
            # loss costs the full size (bought at $1, get $0 back).
            if direction == "yes":
                return 0.0 if settlement_value == 1.0 else round(-size, 2)
            else:
                return 0.0 if settlement_value == 0.0 else round(-size, 2)
        if direction == "yes":
            return round(size if settlement_value == 1.0 else -size, 2)
        else:
            return round(size if settlement_value == 0.0 else -size, 2)

    if direction == "yes":
        if settlement_value == 1.0:
            pnl = (1.0 - entry_price) * size
        else:
            pnl = -(entry_price * size)
    else:
        if settlement_value == 0.0:
            pnl = (1.0 - entry_price) * size
        else:
            pnl = -(entry_price * size)

    return round(pnl, 2)


async def check_market_settlement(
    trade: Trade,
) -> Tuple[bool, Optional[float], Optional[float]]:
    """
    Check if a trade's market has settled.

    Returns: (is_settled, settlement_value, pnl)
    """
    is_resolved, settlement_value = await fetch_polymarket_resolution(
        trade.market_ticker,
        event_slug=trade.event_slug,
        condition_id=getattr(trade, "condition_id", None),
    )

    if not is_resolved or settlement_value is None:
        return False, None, None

    pnl = calculate_pnl(trade, settlement_value)

    mapped_dir = "UP" if trade.direction in ("up", "yes") else "DOWN"
    outcome = "UP" if settlement_value == 1.0 else "DOWN"
    result = "WIN" if mapped_dir == outcome else "LOSS"

    logger.info(
        f"Trade {trade.id} settled: {mapped_dir} @ {trade.entry_price:.0%} -> "
        f"{result} P&L: ${pnl:+.2f}"
    )

    return True, settlement_value, pnl


async def check_weather_settlement(
    trade: Trade,
) -> Tuple[bool, Optional[float], Optional[float]]:
    """
    Check if a weather trade's market has settled.
    Routes to the correct platform's resolution method.
    """
    platform = getattr(trade, "platform", "polymarket") or "polymarket"

    if platform == "kalshi":
        is_resolved, settlement_value = await _fetch_kalshi_resolution(
            trade.market_ticker
        )
    else:
        is_resolved, settlement_value = await fetch_polymarket_resolution(
            trade.market_ticker,
            event_slug=trade.event_slug,
            condition_id=getattr(trade, "condition_id", None),
        )

    if is_resolved and settlement_value is not None:
        pnl = calculate_pnl(trade, settlement_value)
        return True, settlement_value, pnl

    return False, None, None


async def _resolve_markets(
    normal_tickers: set,
    weather_tickers: set,
    trade_slugs: dict,
    trade_platforms: dict,
) -> dict:
    """
    Resolve all unique market tickers concurrently.

    Returns a dict mapping ticker -> (is_resolved, settlement_value).
    normal_tickers: set of tickers for BTC/standard markets.
    weather_tickers: set of tickers for weather markets.
    trade_slugs: dict mapping ticker -> event_slug (may be None).
    trade_platforms: dict mapping ticker -> platform string.
    """

    global _gamma_semaphore
    if _gamma_semaphore is None:
        _gamma_semaphore = asyncio.Semaphore(5)

    async def _resolve_one(ticker: str, is_weather: bool):
        if ticker in _resolved_market_cache:
            return ticker, _resolved_market_cache[ticker]

        if ticker in _gamma_inflight:
            await _gamma_inflight[ticker].wait()
            return ticker, _resolved_market_cache.get(ticker)

        event = asyncio.Event()
        _gamma_inflight[ticker] = event
        try:
            platform = trade_platforms.get(ticker, "polymarket") or "polymarket"
            async with _gamma_semaphore:
                metar_observed = None
                if is_weather:
                    try:
                        from backend.data.weather import CITY_CONFIG, fetch_noaa_metar
                        city_key = ticker if ticker in CITY_CONFIG else next(
                            (k for k in CITY_CONFIG if k in (ticker or "").lower()),
                            None,
                        )
                        if city_key and CITY_CONFIG[city_key].get("nws_station"):
                            station_id = CITY_CONFIG[city_key]["nws_station"]
                            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                            metar_observed = await fetch_noaa_metar(station_id, today_str)
                    except Exception as metar_err:
                        logger.debug(
                            f"[settlement_helpers._resolve_one] METAR lookup skipped for {ticker}: {metar_err}"
                        )

                if is_weather and platform == "kalshi":
                    result = await _fetch_kalshi_resolution(ticker)
                else:
                    result = await fetch_polymarket_resolution(
                        ticker, event_slug=trade_slugs.get(ticker)
                    )

                if is_weather and metar_observed:
                    logger.info(
                        f"Weather settlement {ticker}: METAR observation used as primary source "
                        f"(station={metar_observed.get('station_id')}, temp_c={metar_observed.get('temp_c')})"
                    )
                elif is_weather:
                    logger.info(
                        f"Weather settlement {ticker}: METAR unavailable, falling back to NWS/platform forecast"
                    )
                await asyncio.sleep(0.1)
            if result and result[0]:
                _resolved_market_cache[ticker] = result
            return ticker, result
        finally:
            event.set()
            _gamma_inflight.pop(ticker, None)

    tasks = [_resolve_one(t, False) for t in normal_tickers] + [
        _resolve_one(t, True) for t in weather_tickers
    ]
    gathered = await asyncio.gather(*tasks, return_exceptions=True)

    resolutions = {}
    for item in gathered:
        if isinstance(item, Exception):
            logger.warning(
                f"[settlement_helpers._resolve_markets] {type(item).__name__}: partial settlement: {item}",
                exc_info=item,
            )
            continue
        ticker, result = item
        resolutions[ticker] = result
    return resolutions


async def _get_actual_temp_from_openmeteo(
    city_key: str, target_date: str
) -> Optional[float]:
    try:
        from backend.data.weather import CITY_CONFIG

        cfg = CITY_CONFIG.get(city_key, {})
        lat = cfg.get("lat")
        lon = cfg.get("lon")
        if not lat or not lon:
            return None

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                settings.OPEN_METEO_ARCHIVE_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "start_date": target_date,
                    "end_date": target_date,
                    "daily": "temperature_2m_max"
                    if cfg.get("metric") != "low"
                    else "temperature_2m_min",
                },
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            daily = data.get("daily", {})
            temps = daily.get("temperature_2m_max") or daily.get("temperature_2m_min")
            if temps and len(temps) > 0:
                return float(temps[0])
    except Exception as e:
        logger.debug(
            f"[settlement_helpers._get_actual_temp_from_openmeteo] {type(e).__name__}: Failed to fetch temperature for {city_key} on {target_date}: {e}",
            exc_info=True
        )
    return None


async def _try_calibrate_weather(signal, settlement_value: float) -> None:
    try:
        from backend.core.calibration import update_calibration

        sources = signal.sources or []
        city_key = next(
            (s.split(":", 1)[1] for s in sources if s.startswith("city:")),
            None,
        )
        if not city_key:
            return

        m = re.search(r"Ensemble:\s*([\d.]+)F", signal.reasoning or "")
        if not m:
            return
        forecast_temp_f = float(m.group(1))

        m2 = re.search(r"(?:above|below)\s*([\d.]+)F", signal.reasoning)
        threshold_f = float(m2.group(1)) if m2 else forecast_temp_f

        target_date_match = re.search(
            r"on\s+(\d{4}-\d{2}-\d{2})", signal.reasoning or ""
        )
        actual_temp_f = None

        if target_date_match:
            target_date = target_date_match.group(1)
            actual_temp_f = await _get_actual_temp_from_openmeteo(city_key, target_date)

        if actual_temp_f is None:
            direction_above = "above" in (signal.reasoning or "").lower().split("|")[0]
            if settlement_value == 1.0:
                actual_temp_f = (
                    threshold_f + 1.0 if direction_above else threshold_f - 1.0
                )
            else:
                actual_temp_f = (
                    threshold_f - 1.0 if direction_above else threshold_f + 1.0
                )

        update_calibration(
            city_key,
            source="gefs",
            forecast_temp_f=forecast_temp_f,
            actual_temp_f=actual_temp_f,
        )
        logger.debug(
            f"Calibration updated: {city_key} forecast={forecast_temp_f:.1f} actual≈{actual_temp_f:.1f}"
        )

    except Exception as e:
        logger.debug(
            f"[settlement_helpers._try_calibrate_weather] {type(e).__name__}: Calibration update skipped (best-effort): {e}"
        )


async def _record_weather_observation(trade, settlement_value: float, db) -> None:
    from backend.modules.scanners.weather_emos import (
        load_calibration_states,
        save_calibration_states,
        CalibrationState,
    )

    signal_data = getattr(trade, "signal_data", None)
    if not signal_data:
        try:
            ctx = (
                db.query(TradeContext).filter(TradeContext.trade_id == trade.id).first()
            )
            if ctx and ctx.signal_source:
                try:
                    signal_data = json.loads(ctx.signal_source)
                except Exception as e:
                    logger.debug(
                        f"[settlement_helpers._record_weather_observation] {type(e).__name__}: JSON parse of signal_source failed: {e}",
                        exc_info=True
                    )
        except Exception as e:
            logger.debug(
                f"[settlement_helpers._record_weather_observation] {type(e).__name__}: DB query for TradeContext failed: {e}",
                exc_info=True
            )

    if not signal_data:
        logger.debug(f"Weather calibration: no signal_data for trade {trade.id}")
        return

    if isinstance(signal_data, str):
        try:
            signal_data = json.loads(signal_data)
        except Exception as e:
            logger.debug(
                f"[settlement_helpers._record_weather_observation] {type(e).__name__}: Could not parse signal_data for trade {trade.id}: {e}",
                exc_info=True
            )
            return

    forecast_mean_f = signal_data.get("forecast_mean_f") or signal_data.get(
        "forecast_temp"
    )
    calibrated_std_f = signal_data.get("calibrated_std_f", 5.0)
    city = signal_data.get("city")
    direction = signal_data.get("direction", "above")
    threshold_f = signal_data.get("threshold_f")

    if not forecast_mean_f or not city:
        logger.debug(
            f"Weather calibration: missing forecast_mean_f or city for trade {trade.id}"
        )
        return

    if threshold_f:
        if settlement_value == 1.0:
            if direction == "above":
                actual_temp_f = threshold_f + 2.0
            else:
                actual_temp_f = threshold_f - 2.0
        else:
            if direction == "above":
                actual_temp_f = threshold_f - 2.0
            else:
                actual_temp_f = threshold_f + 2.0
    else:
        actual_temp_f = forecast_mean_f + (2.0 if settlement_value == 1.0 else -2.0)

    cal_states = load_calibration_states(db, "weather_emos")
    cal = cal_states.get(city, CalibrationState())
    cal.add_observation(forecast_mean_f, calibrated_std_f, actual_temp_f)
    cal_states[city] = cal
    save_calibration_states(db, "weather_emos", cal_states)
    logger.info(
        f"Weather EMOS: recorded obs for {city}: forecast={forecast_mean_f:.1f}F actual~{actual_temp_f:.1f}F"
    )


async def process_settled_trade(
    trade: Trade,
    is_settled: bool,
    settlement_value: Optional[float],
    pnl: Optional[float],
    db: Session,
) -> bool:
    """
    Process a settled trade - update trade record, broadcast event, create settlement event,
    backfill decision log, and update signal.

    Returns True if trade was successfully processed and added to settled_trades list.
    """
    if not is_settled or settlement_value is None:
        return False

    if getattr(trade, "settled", False) and trade.pnl is not None:
        logger.debug(
            f"[settlement_helpers.process_settled_trade] Trade {trade.id} already settled (pnl={trade.pnl}), skipping"
        )
        return False

    trade.settled = True
    trade.settlement_value = settlement_value
    trade.pnl = pnl
    trade.settlement_time = datetime.now(timezone.utc)
    trade.settlement_source = "market_resolution"
    if pnl is not None and pnl > 0:
        trade.result = "win"
    elif pnl is not None and pnl < 0:
        trade.result = "loss"
    else:
        trade.result = "push"

    # Broadcast event
    try:
        from backend.core.event_bus import _broadcast_event

        _broadcast_event(
            "trade_settled",
            {
                "trade_id": trade.id,
                "market_ticker": trade.market_ticker,
                "result": trade.result,
                "pnl": trade.pnl,
                "mode": getattr(trade, "trading_mode", "paper"),
            },
        )
    except Exception as e:
        logger.debug(
            f"[settlement_helpers.process_settled_trade] {type(e).__name__}: Broadcast event failed: {e}",
            exc_info=True
        )

    # Create settlement event
    platform = getattr(trade, "platform", "polymarket") or "polymarket"
    resolved_outcome = "up" if settlement_value == 1.0 else "down"
    db.add(
        SettlementEvent(
            trade_id=trade.id,
            market_ticker=trade.market_ticker,
            resolved_outcome=resolved_outcome,
            pnl=pnl,
            source=platform,
        )
    )

    # Backfill DecisionLog outcome for this trade
    try:
        from backend.models.database import DecisionLog

        outcome = (
            "WIN"
            if trade.result == "win"
            else ("LOSS" if trade.result == "loss" else "PUSH")
        )
        # Try to get strategy from TradeContext
        trade_ctx = (
            db.query(TradeContext).filter(TradeContext.trade_id == trade.id).first()
        )
        dl_query = db.query(DecisionLog).filter(
            DecisionLog.market_ticker == trade.market_ticker,
            DecisionLog.outcome.is_(None),
            DecisionLog.decision == "BUY",
        )
        if trade_ctx and trade_ctx.strategy:
            dl_query = dl_query.filter(DecisionLog.strategy == trade_ctx.strategy)
        decisions = dl_query.all()
        for decision in decisions:
            decision.outcome = outcome
    except Exception as e:
        logger.opt(exception=True).debug(
            "[settlement_helpers.process_settled_trade] {}: DecisionLog outcome backfill failed for {}: {!r}",
            type(e).__name__,
            trade.market_ticker,
            e,
        )

    # Update linked signal
    if trade.signal_id:
        linked_signal = db.query(Signal).filter(Signal.id == trade.signal_id).first()
        if linked_signal:
            actual_outcome = "up" if settlement_value == 1.0 else "down"
            linked_signal.actual_outcome = actual_outcome
            linked_signal.outcome_correct = linked_signal.direction == actual_outcome
            linked_signal.settlement_value = settlement_value
            linked_signal.settled_at = datetime.now(timezone.utc)
            market_type = getattr(trade, "market_type", "btc") or "btc"
            if market_type == "weather" and linked_signal.sources:
                await _try_calibrate_weather(linked_signal, settlement_value)

            if market_type == "weather":
                try:
                    await _record_weather_observation(trade, settlement_value, db)
                except Exception as e:
                    logger.opt(exception=True).debug(
                        "[settlement_helpers.process_settled_trade] {}: Weather calibration update skipped for {}: {!r}",
                        type(e).__name__,
                        trade.market_ticker,
                        e,
                    )

    # Write outcome to BigBrain (unified memory)
    try:
        from backend.clients.bigbrain import get_bigbrain

        brain = get_bigbrain()
        await brain.write_trade_outcome(
            {
                "strategy": getattr(trade, "strategy", "unknown"),
                "market": trade.market_ticker,
                "direction": trade.direction,
                "result": trade.result,
                "pnl": pnl,
                "edge": getattr(trade, "edge_at_entry", 0.0),
                "confidence": getattr(trade, "confidence", 0.5),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
    except Exception as e:
        logger.opt(exception=True).debug(
            "[settlement_helpers.process_settled_trade] {}: BigBrain write_trade_outcome failed for trade {}: {!r}",
            type(e).__name__,
            trade.id,
            e,
        )

    # Record calibration outcome for model validation
    try:
        from backend.core.calibration_tracker import calibration_tracker

        calibration_tracker.record_outcome(db, trade.market_ticker, settlement_value)
    except Exception as e:
        logger.opt(exception=True).debug(
            "[settlement_helpers.process_settled_trade] {}: Calibration record failed for {}: {!r}",
            type(e).__name__,
            trade.market_ticker,
            e,
        )

    # Flush settlement state before optional learner work so any learner-session
    # rollback/savepoint cleanup cannot erase the main settlement changes.
    db.flush()

    # Trigger realtime RL learner — fire-and-forget, never blocks settlement
    try:
        from backend.core.online_learner import OnlineLearner

        learner = OnlineLearner()
        learner_session_factory = sessionmaker(
            bind=db.connection(),
            autocommit=False,
            autoflush=False,
            join_transaction_mode="create_savepoint",
        )
        learner_db = learner_session_factory()
        try:
            learner_trade = learner_db.query(Trade).filter(Trade.id == trade.id).first()
            if learner_trade is not None:
                learner.on_trade_settled(learner_trade, learner_db)
        except Exception:
            learner_db.rollback()
            raise
        finally:
            learner_db.close()
    except Exception as e:
        logger.warning(
            "[settlement_helpers.process_settled_trade] {}: online_learner hook failed for trade {}: {}",
            type(e).__name__,
            getattr(trade, "id", "?"),
            e,
        )

    # Trade forensics: analyze losing trades for patterns (non-blocking)
    if trade.result == "loss":
        try:
            from backend.core.trade_forensics import trade_forensics
            await trade_forensics.analyze_losing_trade(trade.id)
        except Exception as e:
            logger.opt(exception=True).debug(
                "[settlement_helpers] Trade forensics failed for trade {}: {!r}",
                trade.id,
                e,
            )

    if trade.strategy:
        try:
            from backend.core.strategy_performance_registry import strategy_performance_registry
            strategy_performance_registry.update_from_settlement(trade.strategy, db=db)
        except Exception as e:
            logger.opt(exception=True).debug(
                "[settlement_helpers] Performance registry update failed for {}: {!r}",
                trade.strategy,
                e,
            )

    # Record TransactionEvent for settlement P&L (ledger entry)
    try:
        from backend.models.database import TransactionEvent, BotState
        event_type = "settlement_win" if trade.result == "win" else "settlement_loss"
        bot = db.query(BotState).first()
        prior_balance = bot.bankroll if bot else 0.0
        estimated_balance = prior_balance + pnl
        event = TransactionEvent(
            type=event_type,
            amount=pnl,
            balance_after=estimated_balance,
            context={
                "trade_id": trade.id,
                "strategy": trade.strategy,
                "market_ticker": trade.market_ticker,
                "direction": trade.direction,
            },
            note=f"Trade {trade.id} settled {trade.result} (P&L: {pnl:.2f})",
        )
        db.add(event)
    except Exception as e:
        logger.opt(exception=True).debug(
            "[settlement_helpers] TransactionEvent recording failed for trade {}: {!r}",
            trade.id,
            e,
        )

    return True


async def reconcile_positions(db: Session) -> List[int]:
    """
    Reconcile open trades with actual Polymarket positions.

    Fetches current positions from Polymarket and compares with open trades in DB.
    Returns list of trade IDs that should be marked as "closed" (position no longer exists).

    This catches:
    - Orders that were filled then sold manually
    - Orders that expired unfilled
    - Positions closed outside the bot
    """
    from backend.data.polymarket_clob import clob_from_settings
    from backend.config import settings
    from backend.models.database import Trade

    effective_mode = settings.TRADING_MODE
    if effective_mode == "paper":
        logger.debug("Skipping position reconciliation in paper mode")
        return []

    wallet_address = settings.POLYMARKET_BUILDER_ADDRESS

    if not wallet_address:
        logger.debug("No wallet address available for position reconciliation")
        return []

    try:
        async with clob_from_settings(mode=effective_mode) as clob:
            positions = await clob.get_trader_positions(wallet_address)

        active_positions = set()
        for pos in positions:
            market_ticker = pos.get("slug")

            if market_ticker and float(pos.get("size", 0)) > 0:
                active_positions.add(market_ticker)

        logger.info(
            f"Position reconciliation: found {len(active_positions)} active positions on Polymarket"
        )

        open_trades = (
            db.query(Trade)
            .filter(
                Trade.settled.is_(False),
                Trade.trading_mode == effective_mode,
                Trade.platform == "polymarket",
            )
            .all()
        )

        logger.info(
            f"Position reconciliation: found {len(open_trades)} open trades in DB"
        )

        trades_to_close = []
        for trade in open_trades:
            if trade.market_ticker not in active_positions:
                trades_to_close.append(trade.id)
                logger.info(
                    f"Trade {trade.id} marked for closure: {trade.market_ticker} "
                    f"{trade.direction.upper()} (position not found on Polymarket)"
                )

        logger.info(
            f"Position reconciliation: {len(trades_to_close)} trades to mark as closed"
        )
        return trades_to_close

    except Exception as e:
        logger.error(
            f"[settlement_helpers.reconcile_positions] {type(e).__name__}: "
            f"Position reconciliation failed: {e}",
            exc_info=True,
        )
        return []


async def resolve_paper_trades(db) -> List[Trade]:
    """
    Resolve pending paper trades via Gamma API outcome prices.
    Paper trades are marked settled=True but result='pending' — this
    queries Gamma for actual market outcomes and updates PnL accordingly.
    """
    from backend.models.database import Trade
    from datetime import datetime, timezone
    import httpx

    # Find paper trades still pending resolution
    pending = (
        db.query(Trade)
        .filter(
            Trade.trading_mode == "paper",
            Trade.settled == True,
            Trade.pnl.is_(None),
        )
        .all()
    )

    if not pending:
        return []

    settled = []
    now = datetime.now(timezone.utc)

    # Deduplicate by market_ticker
    tickers = list(set(t.market_ticker for t in pending))

    async with httpx.AsyncClient(timeout=10) as client:
        for ticker in tickers:
            try:
                r = await client.get(
                    f"{settings.GAMMA_API_URL}/markets",
                    params={"slug": ticker},
                )
                if r.status_code != 200:
                    continue
                data = r.json()
                if not isinstance(data, list) or not data:
                    continue

                market = data[0]
                prices = market.get("outcomePrices", [])
                if not prices:
                    continue

                p0 = float(prices[0]) if prices[0] is not None else None
                p1 = float(prices[1]) if len(prices) > 1 and prices[1] is not None else None

                if p0 is None or p1 is None:
                    continue

                # Determine settlement value from extreme prices
                threshold = 0.005
                if p0 <= threshold and p1 >= (1.0 - threshold):
                    settlement_value = 0.0  # outcome index 0 won (NO)
                elif p1 <= threshold and p0 >= (1.0 - threshold):
                    settlement_value = 1.0  # outcome index 1 won (YES)
                else:
                    continue  # market still open

                condition_id = market.get("conditionId", "")

                # Update all trades for this ticker
                for trade in pending:
                    if trade.market_ticker == ticker:
                        dir_yes = trade.direction in ("yes", "up")
                        is_win = (dir_yes and settlement_value == 1.0) or (not dir_yes and settlement_value == 0.0)

                        trade.result = "win" if is_win else "loss"
                        trade.settlement_value = settlement_value
                        trade.settlement_time = now
                        trade.settlement_source = "gamma_outcome"

                        if is_win:
                            trade.pnl = round((1.0 - trade.entry_price) * trade.size, 2)
                        else:
                            trade.pnl = round(-(trade.entry_price * trade.size), 2)

                        if condition_id:
                            trade.condition_id = condition_id

                        settled.append(trade)
            except Exception as e:
                logger.warning(f"Paper settlement failed for {ticker}: {e}")
                continue

    if settled:
        try:
            db.commit()
        except Exception as e:
            logger.error(f"Failed to commit paper settlements: {e}")
            db.rollback()
            return []

        # Update bot_state inline to avoid circular import
        if settled:
            try:
                for trade in settled:
                    if trade.pnl is None:
                        continue
                    state = db.query(type("BotState", (object,), {})).filter_by(mode="paper").first()
                    if state and hasattr(state, "paper_pnl"):
                        state.paper_pnl = (state.paper_pnl or 0) + trade.pnl
                        state.paper_trades = (state.paper_trades or 0) + 1
                        if trade.result == "win":
                            state.paper_wins = (state.paper_wins or 0) + 1
                db.commit()
            except Exception as e:
                logger.error(f"Failed to update paper bot_state: {e}")

    return settled
